//! Engine catalog: the single source of truth shared with `scripts/gen.py`.
//! Loaded once from `catalog/engines.json` (embedded at compile time).

use serde::Deserialize;
use std::collections::BTreeMap;

pub const CATALOG_JSON: &str = include_str!("../catalog/engines.json");

/// Postgres-facing scalar types we know how to produce.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum PgType {
    Text,
    Int,
    Bigint,
    Numeric,
    Bool,
    Jsonb,
}

impl PgType {
    pub fn sql(self) -> &'static str {
        match self {
            PgType::Text => "text",
            PgType::Int => "int",
            PgType::Bigint => "bigint",
            PgType::Numeric => "numeric",
            PgType::Bool => "boolean",
            PgType::Jsonb => "jsonb",
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct ParamSpec {
    pub name: String,
    #[serde(rename = "type")]
    pub ty: PgType,
    /// SerpApi query-parameter name when it differs from `name` (e.g. amazon `k`).
    #[serde(default)]
    pub api: Option<String>,
    /// `server:<option>` to pull a default from the foreign server options.
    #[serde(default)]
    pub default: Option<String>,
    #[serde(default)]
    #[allow(dead_code)] // consumed by scripts/gen.py, mirrored here for one schema
    pub doc: Option<String>,
}

impl ParamSpec {
    pub fn api_name(&self) -> &str {
        self.api.as_deref().unwrap_or(&self.name)
    }
    /// Server option this param defaults from, if any.
    pub fn server_default_key(&self) -> Option<&str> {
        self.default
            .as_deref()
            .and_then(|d| d.strip_prefix("server:"))
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct ColumnSpec {
    pub name: String,
    #[serde(rename = "type")]
    pub ty: PgType,
    /// Dotted path inside one result object of `block`.
    pub path: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PaginationKind {
    None,
    Start,
    Page,
    NextPageToken,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Pagination {
    pub kind: PaginationKind,
    #[serde(default)]
    pub step: Option<u32>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct EngineSpec {
    #[serde(default)]
    #[allow(dead_code)]
    pub doc: Option<String>,
    pub api_engine: String,
    pub block: String,
    pub pagination: Pagination,
    #[serde(default)]
    pub required: Vec<String>,
    #[serde(default)]
    pub required_any: Vec<String>,
    #[serde(default)]
    pub fixed_params: BTreeMap<String, String>,
    pub params: Vec<ParamSpec>,
    pub columns: Vec<ColumnSpec>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ObjectSpec {
    #[serde(default)]
    #[allow(dead_code)]
    pub doc: Option<String>,
    pub table: String,
    pub columns_sql: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ServerOptionSpec {
    #[serde(default)]
    pub default: Option<String>,
    #[serde(default)]
    #[allow(dead_code)]
    pub doc: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Catalog {
    #[allow(dead_code)]
    pub version: u32,
    #[serde(default)]
    pub common_params: Vec<ParamSpec>,
    pub engines: BTreeMap<String, EngineSpec>,
    pub objects: BTreeMap<String, ObjectSpec>,
    pub server_options: BTreeMap<String, ServerOptionSpec>,
}

impl Catalog {
    pub fn load() -> Result<Catalog, String> {
        serde_json::from_str(CATALOG_JSON)
            .map_err(|e| format!("serpapi: bad embedded catalog: {e}"))
    }

    pub fn engine(&self, name: &str) -> Option<&EngineSpec> {
        self.engines.get(name)
    }

    /// Parameter columns for a typed table, in DDL / function-argument order:
    /// first engine param, then the common params (gl, hl), then the rest.
    pub fn param_specs<'a>(&'a self, spec: &'a EngineSpec) -> Vec<&'a ParamSpec> {
        let mut out: Vec<&ParamSpec> =
            Vec::with_capacity(spec.params.len() + self.common_params.len());
        let mut it = spec.params.iter();
        if let Some(first) = it.next() {
            out.push(first);
        }
        out.extend(self.common_params.iter());
        out.extend(it);
        out
    }

    pub fn server_default(&self, key: &str) -> Option<&str> {
        self.server_options
            .get(key)
            .and_then(|o| o.default.as_deref())
    }
}

/// Standard parameter columns present on every typed table besides the catalog params.
pub const STD_PARAM_PAGES: &str = "pages";
pub const STD_PARAM_SEARCH_ID: &str = "search_id";
/// Standard result columns present on every typed table.
pub const STD_COL_PAGE: &str = "page";
pub const STD_COL_RAW: &str = "raw";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn catalog_parses_and_has_expected_engines() {
        let c = Catalog::load().expect("catalog");
        for e in [
            "google",
            "google_light",
            "google_shopping",
            "amazon",
            "google_jobs",
            "google_maps",
            "google_maps_reviews",
            "google_news",
        ] {
            assert!(c.engine(e).is_some(), "missing engine {e}");
        }
        assert!(c.objects.contains_key("search"));
        assert!(c.objects.contains_key("account"));
        assert_eq!(c.server_default("hourly_cap"), Some("50"));
    }

    #[test]
    fn no_duplicate_column_names_per_engine() {
        let c = Catalog::load().unwrap();
        for (name, spec) in &c.engines {
            let mut seen = std::collections::HashSet::new();
            for p in c.param_specs(spec) {
                assert!(
                    seen.insert(p.name.clone()),
                    "{name}: duplicate param {}",
                    p.name
                );
            }
            for s in [
                STD_PARAM_PAGES,
                STD_PARAM_SEARCH_ID,
                STD_COL_PAGE,
                STD_COL_RAW,
            ] {
                assert!(seen.insert(s.to_string()), "{name}: std column {s} clashes");
            }
            for col in &spec.columns {
                assert!(
                    seen.insert(col.name.clone()),
                    "{name}: duplicate column {}",
                    col.name
                );
            }
        }
    }

    #[test]
    fn amazon_query_param_is_k() {
        let c = Catalog::load().unwrap();
        let a = c.engine("amazon").unwrap();
        assert_eq!(a.params[0].name, "q");
        assert_eq!(a.params[0].api_name(), "k");
    }
}
