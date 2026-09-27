//! Turn WHERE-clause quals into a validated request plan.
//!
//! Rules (documented in README):
//! * Parameter columns accept only `=`; `q` additionally accepts `IN (...)`.
//! * '' / -1 / false mean "unset" and fall back to the server default (or are omitted).
//! * `q`-style required params are enforced before any HTTP call.
//! * `search_id = '...'` switches the scan to archive replay (free, no required params).
//! * Quals on result columns are ignored here; Postgres rechecks them locally.

use crate::catalog::{
    Catalog, EngineSpec, ParamSpec, PgType, STD_PARAM_PAGES, STD_PARAM_SEARCH_ID,
};
use crate::values::PgValue;
use std::collections::BTreeMap;

/// A host-independent view of one qual.
#[derive(Debug, Clone)]
pub struct QualLite {
    pub field: String,
    pub op: String,
    pub values: Vec<PgValue>,
    /// true for `col IN (...)` / `col = ANY(...)`
    pub is_array: bool,
}

/// Non-empty server-level defaults, keyed by option name (e.g. `default_gl`).
#[derive(Debug, Default, Clone)]
pub struct ServerDefaults(pub BTreeMap<String, String>);

impl ServerDefaults {
    pub fn get(&self, key: &str) -> Option<&str> {
        self.0
            .get(key)
            .map(|s| s.as_str())
            .filter(|s| !s.is_empty())
    }
}

#[derive(Debug, Clone)]
pub struct ScanParams {
    /// SerpApi query params (api names) except the query term and pagination.
    pub api_params: BTreeMap<String, String>,
    /// API name of the query-term param (`q` or `k`) when the engine has one.
    pub query_api_name: Option<String>,
    /// One search per value (supports `q IN (...)`). Empty when no query term is set.
    pub query_values: Vec<String>,
    /// Column name of the query-term param, for echo-back per row.
    pub query_column: Option<String>,
    /// Echo values for every parameter column except the query term:
    /// what the user gave, or the effective default when nothing was given.
    pub echo: BTreeMap<String, Option<PgValue>>,
    pub pages: u32,
    pub search_id: Option<String>,
}

fn only_eq(q: &QualLite) -> Result<(), String> {
    if q.op != "=" {
        return Err(format!(
            "serpapi: only '=' is supported on parameter column \"{}\" (got '{}')",
            q.field, q.op
        ));
    }
    Ok(())
}

fn pg_default_value(ty: PgType, s: &str) -> PgValue {
    match ty {
        PgType::Text | PgType::Jsonb => PgValue::Text(s.to_string()),
        PgType::Int | PgType::Bigint => PgValue::Int(s.parse().unwrap_or(-1)),
        PgType::Numeric => PgValue::Num(s.parse().unwrap_or(-1.0)),
        PgType::Bool => PgValue::Bool(matches!(s, "true" | "on" | "1")),
    }
}

/// Resolve quals for a typed engine table.
pub fn collect_typed(
    quals: &[QualLite],
    cat: &Catalog,
    spec: &EngineSpec,
    defaults: &ServerDefaults,
    max_pages: u32,
) -> Result<ScanParams, String> {
    let specs: Vec<&ParamSpec> = cat.param_specs(spec);
    let by_name: BTreeMap<&str, &ParamSpec> = specs.iter().map(|p| (p.name.as_str(), *p)).collect();

    let mut given: BTreeMap<String, &QualLite> = BTreeMap::new();
    let mut pages: u32 = 1;
    let mut search_id: Option<String> = None;

    for q in quals {
        let f = q.field.as_str();
        if f == STD_PARAM_PAGES {
            only_eq(q)?;
            if q.is_array {
                return Err("serpapi: pages does not accept IN (...)".into());
            }
            pages = match q.values.first() {
                Some(PgValue::Int(i)) if *i >= 1 => *i as u32,
                Some(PgValue::Int(i)) if *i < 0 => 1, // unset convention
                Some(other) => {
                    return Err(format!(
                        "serpapi: pages must be a positive integer (got {other:?})"
                    ));
                }
                None => 1,
            };
            if pages > max_pages {
                return Err(format!(
                    "serpapi: pages = {pages} exceeds the server's max_pages ({max_pages}); each page costs one search"
                ));
            }
            continue;
        }
        if f == STD_PARAM_SEARCH_ID {
            only_eq(q)?;
            if let Some(PgValue::Text(s)) = q.values.first()
                && !s.is_empty()
            {
                search_id = Some(s.clone());
            }
            continue;
        }
        if by_name.contains_key(f) {
            only_eq(q)?;
            if q.is_array && f != "q" {
                return Err(format!(
                    "serpapi: IN (...) is only supported on \"q\", not \"{f}\""
                ));
            }
            given.insert(f.to_string(), q);
        }
        // anything else: a result column filter; Postgres applies it locally
    }

    let mut api_params: BTreeMap<String, String> = BTreeMap::new();
    let mut echo: BTreeMap<String, Option<PgValue>> = BTreeMap::new();
    let mut query_api_name: Option<String> = None;
    let mut query_values: Vec<String> = Vec::new();
    let mut query_column: Option<String> = None;
    let mut effective_set: Vec<&str> = Vec::new();

    for p in &specs {
        let is_query = p.name == "q";
        let given_q = given.get(&p.name);

        // effective value: given (unless unset) → server default → none
        let given_val = given_q
            .and_then(|q| q.values.first())
            .filter(|v| !v.is_unset());
        let default_val: Option<String> = p
            .server_default_key()
            .and_then(|k| defaults.get(k))
            .map(|s| s.to_string());

        if is_query {
            query_api_name = Some(p.api_name().to_string());
            query_column = Some(p.name.clone());
            if let Some(q) = given_q {
                let vals: Vec<String> = q
                    .values
                    .iter()
                    .filter(|v| !v.is_unset())
                    .map(|v| v.as_query_string())
                    .collect();
                if !vals.is_empty() {
                    effective_set.push("q");
                }
                query_values = vals;
            }
            continue;
        }

        match (given_val, given_q, default_val) {
            (Some(v), _, _) => {
                api_params.insert(p.api_name().to_string(), v.as_query_string());
                echo.insert(p.name.clone(), Some(v.clone()));
                effective_set.push(p.name.as_str());
            }
            (None, Some(q), Some(d)) => {
                // given but unset ('' / -1 / false): use default, echo what was given
                api_params.insert(p.api_name().to_string(), d.clone());
                echo.insert(p.name.clone(), q.values.first().cloned());
                effective_set.push(p.name.as_str());
            }
            (None, Some(q), None) => {
                echo.insert(p.name.clone(), q.values.first().cloned());
            }
            (None, None, Some(d)) => {
                api_params.insert(p.api_name().to_string(), d.clone());
                echo.insert(p.name.clone(), Some(pg_default_value(p.ty, &d)));
                effective_set.push(p.name.as_str());
            }
            (None, None, None) => {
                echo.insert(p.name.clone(), None);
            }
        }
    }

    for (k, v) in &spec.fixed_params {
        api_params.insert(k.clone(), v.clone());
    }

    if search_id.is_none() {
        for r in &spec.required {
            if !effective_set.contains(&r.as_str()) {
                return Err(format!(
                    "serpapi: \"{r}\" is required for engine {} (add WHERE {r} = '...', or replay with search_id = '...')",
                    spec.api_engine
                ));
            }
        }
        if !spec.required_any.is_empty()
            && !spec
                .required_any
                .iter()
                .any(|r| effective_set.contains(&r.as_str()))
        {
            return Err(format!(
                "serpapi: engine {} needs one of: {}",
                spec.api_engine,
                spec.required_any.join(", ")
            ));
        }
    }

    Ok(ScanParams {
        api_params,
        query_api_name,
        query_values,
        query_column,
        echo,
        pages,
        search_id,
    })
}

/// Resolved quals for the generic `search` table.
#[derive(Debug, Clone)]
pub struct GenericParams {
    pub engine: Option<String>,
    /// The `params` jsonb exactly as given (for echo-back), if given.
    pub params_given: Option<String>,
    pub api_params: BTreeMap<String, String>,
    pub pages: u32,
    pub search_id: Option<String>,
}

const RESERVED_GENERIC_KEYS: &[&str] = &[
    "api_key",
    "engine",
    "output",
    "async",
    "no_cache",
    "json_restrictor",
];

pub fn collect_generic(quals: &[QualLite], max_pages: u32) -> Result<GenericParams, String> {
    let mut out = GenericParams {
        engine: None,
        params_given: None,
        api_params: BTreeMap::new(),
        pages: 1,
        search_id: None,
    };
    for q in quals {
        match q.field.as_str() {
            "engine" => {
                only_eq(q)?;
                if let Some(PgValue::Text(s)) = q.values.first()
                    && !s.is_empty()
                {
                    out.engine = Some(s.clone());
                }
            }
            "params" => {
                only_eq(q)?;
                let raw = match q.values.first() {
                    Some(PgValue::Json(s)) | Some(PgValue::Text(s)) => s.clone(),
                    _ => continue,
                };
                let v: serde_json::Value = serde_json::from_str(&raw)
                    .map_err(|e| format!("serpapi: params must be a JSON object: {e}"))?;
                let obj = v
                    .as_object()
                    .ok_or_else(|| "serpapi: params must be a JSON object".to_string())?;
                for (k, val) in obj {
                    if RESERVED_GENERIC_KEYS.contains(&k.as_str()) {
                        continue;
                    }
                    let s = match val {
                        serde_json::Value::String(s) => s.clone(),
                        serde_json::Value::Null => continue,
                        other => other.to_string(),
                    };
                    if !s.is_empty() {
                        out.api_params.insert(k.clone(), s);
                    }
                }
                out.params_given = Some(raw);
            }
            STD_PARAM_PAGES => {
                only_eq(q)?;
                if let Some(PgValue::Int(i)) = q.values.first() {
                    if *i > max_pages as i64 {
                        return Err(format!(
                            "serpapi: pages = {i} exceeds the server's max_pages ({max_pages})"
                        ));
                    }
                    if *i >= 1 {
                        out.pages = *i as u32;
                    }
                }
            }
            STD_PARAM_SEARCH_ID => {
                only_eq(q)?;
                if let Some(PgValue::Text(s)) = q.values.first()
                    && !s.is_empty()
                {
                    out.search_id = Some(s.clone());
                }
            }
            _ => {}
        }
    }
    if out.search_id.is_none() && out.engine.is_none() {
        return Err("serpapi: engine is required (WHERE engine = 'google_trends' AND params = '{...}'), or replay with search_id".into());
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cat() -> Catalog {
        Catalog::load().unwrap()
    }
    fn eq(field: &str, v: PgValue) -> QualLite {
        QualLite {
            field: field.into(),
            op: "=".into(),
            values: vec![v],
            is_array: false,
        }
    }
    fn defaults() -> ServerDefaults {
        let mut m = BTreeMap::new();
        m.insert("default_gl".to_string(), "in".to_string());
        m.insert(
            "default_location".to_string(),
            "Bengaluru,Karnataka,India".to_string(),
        );
        ServerDefaults(m)
    }

    #[test]
    fn shopping_uses_server_defaults_and_echoes_them() {
        let c = cat();
        let spec = c.engine("google_shopping").unwrap();
        let sp = collect_typed(
            &[eq("q", PgValue::Text("boAt".into()))],
            &c,
            spec,
            &defaults(),
            3,
        )
        .unwrap();
        assert_eq!(sp.query_values, vec!["boAt".to_string()]);
        assert_eq!(sp.api_params.get("gl").map(String::as_str), Some("in"));
        assert_eq!(
            sp.api_params.get("location").map(String::as_str),
            Some("Bengaluru,Karnataka,India")
        );
        assert_eq!(
            sp.echo.get("gl").cloned().flatten(),
            Some(PgValue::Text("in".into()))
        );
        assert_eq!(sp.pages, 1);
    }

    #[test]
    fn unset_given_value_falls_back_but_echoes_given() {
        let c = cat();
        let spec = c.engine("google_shopping").unwrap();
        let sp = collect_typed(
            &[
                eq("q", PgValue::Text("x".into())),
                eq("gl", PgValue::Text(String::new())),
            ],
            &c,
            spec,
            &defaults(),
            3,
        )
        .unwrap();
        assert_eq!(sp.api_params.get("gl").map(String::as_str), Some("in"));
        assert_eq!(
            sp.echo.get("gl").cloned().flatten(),
            Some(PgValue::Text(String::new()))
        );
    }

    #[test]
    fn missing_q_is_rejected_before_any_http() {
        let c = cat();
        let spec = c.engine("google_shopping").unwrap();
        let err = collect_typed(
            &[eq("gl", PgValue::Text("in".into()))],
            &c,
            spec,
            &defaults(),
            3,
        )
        .unwrap_err();
        assert!(err.contains("\"q\" is required"), "{err}");
    }

    #[test]
    fn replay_skips_required_checks() {
        let c = cat();
        let spec = c.engine("google_shopping").unwrap();
        let sp = collect_typed(
            &[eq("search_id", PgValue::Text("abc".into()))],
            &c,
            spec,
            &defaults(),
            3,
        )
        .unwrap();
        assert_eq!(sp.search_id.as_deref(), Some("abc"));
    }

    #[test]
    fn amazon_maps_q_to_k() {
        let c = cat();
        let spec = c.engine("amazon").unwrap();
        let sp = collect_typed(
            &[eq("q", PgValue::Text("airdopes".into()))],
            &c,
            spec,
            &defaults(),
            3,
        )
        .unwrap();
        assert_eq!(sp.query_api_name.as_deref(), Some("k"));
    }

    #[test]
    fn in_list_on_q_and_rejected_elsewhere() {
        let c = cat();
        let spec = c.engine("google_shopping").unwrap();
        let q = QualLite {
            field: "q".into(),
            op: "=".into(),
            values: vec![PgValue::Text("a".into()), PgValue::Text("b".into())],
            is_array: true,
        };
        let sp = collect_typed(&[q], &c, spec, &defaults(), 3).unwrap();
        assert_eq!(sp.query_values.len(), 2);
        let bad = QualLite {
            field: "gl".into(),
            op: "=".into(),
            values: vec![PgValue::Text("in".into())],
            is_array: true,
        };
        assert!(
            collect_typed(
                &[eq("q", PgValue::Text("a".into())), bad],
                &c,
                spec,
                &defaults(),
                3
            )
            .is_err()
        );
    }

    #[test]
    fn pages_is_capped_by_max_pages() {
        let c = cat();
        let spec = c.engine("google_jobs").unwrap();
        let err = collect_typed(
            &[
                eq("q", PgValue::Text("x".into())),
                eq("pages", PgValue::Int(5)),
            ],
            &c,
            spec,
            &defaults(),
            3,
        )
        .unwrap_err();
        assert!(err.contains("max_pages"));
    }

    #[test]
    fn non_eq_operator_on_param_is_rejected() {
        let c = cat();
        let spec = c.engine("google").unwrap();
        let like = QualLite {
            field: "q".into(),
            op: "~~".into(),
            values: vec![PgValue::Text("%x%".into())],
            is_array: false,
        };
        assert!(collect_typed(&[like], &c, spec, &defaults(), 3).is_err());
    }

    #[test]
    fn reviews_requires_data_id_or_place_id() {
        let c = cat();
        let spec = c.engine("google_maps_reviews").unwrap();
        assert!(collect_typed(&[], &c, spec, &defaults(), 3).is_err());
        assert!(
            collect_typed(
                &[eq("data_id", PgValue::Text("0x1:0x2".into()))],
                &c,
                spec,
                &defaults(),
                3
            )
            .is_ok()
        );
    }

    #[test]
    fn generic_strips_reserved_keys() {
        let g = collect_generic(
            &[
                eq("engine", PgValue::Text("google_trends".into())),
                eq(
                    "params",
                    PgValue::Json(
                        r#"{"q":"air fryer","geo":"IN-KA","api_key":"leak","output":"md"}"#.into(),
                    ),
                ),
            ],
            3,
        )
        .unwrap();
        assert_eq!(g.engine.as_deref(), Some("google_trends"));
        assert!(!g.api_params.contains_key("api_key"));
        assert!(!g.api_params.contains_key("output"));
        assert_eq!(g.api_params.get("geo").map(String::as_str), Some("IN-KA"));
    }
}
