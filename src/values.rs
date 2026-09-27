//! Host-independent value types so the core logic is unit-testable without Wasm bindings.

use crate::catalog::PgType;
use serde_json::Value;

/// A scalar as it crosses the Postgres boundary (subset of the host `cell` variants we use).
#[derive(Debug, Clone, PartialEq)]
pub enum PgValue {
    Text(String),
    Int(i64),
    Num(f64),
    Bool(bool),
    Json(String),
}

impl PgValue {
    /// The "unset" convention for optional parameters: '' / -1 / false.
    pub fn is_unset(&self) -> bool {
        match self {
            PgValue::Text(s) => s.is_empty(),
            PgValue::Int(i) => *i < 0,
            PgValue::Num(n) => *n < 0.0,
            PgValue::Bool(b) => !*b,
            PgValue::Json(s) => s.is_empty() || s == "null",
        }
    }

    /// Render for a URL query parameter.
    pub fn as_query_string(&self) -> String {
        match self {
            PgValue::Text(s) => s.clone(),
            PgValue::Int(i) => i.to_string(),
            PgValue::Num(n) => {
                if n.fract() == 0.0 {
                    format!("{}", *n as i64)
                } else {
                    n.to_string()
                }
            }
            PgValue::Bool(b) => b.to_string(),
            PgValue::Json(s) => s.clone(),
        }
    }
}

/// Walk a dotted path (`a.b.c`) into a JSON value.
pub fn json_at<'a>(v: &'a Value, path: &str) -> Option<&'a Value> {
    let mut cur = v;
    for seg in path.split('.') {
        cur = match cur {
            Value::Object(m) => m.get(seg)?,
            Value::Array(a) => a.get(seg.parse::<usize>().ok()?)?,
            _ => return None,
        };
    }
    if cur.is_null() { None } else { Some(cur) }
}

/// Coerce a JSON value into the Postgres type the column declares. Lenient on purpose:
/// SerpApi shapes drift (numbers as strings, strings as numbers).
pub fn json_to_pg(v: Option<&Value>, ty: PgType) -> Option<PgValue> {
    let v = v?;
    match ty {
        PgType::Text => Some(PgValue::Text(match v {
            Value::String(s) => s.clone(),
            other => other.to_string(),
        })),
        PgType::Int | PgType::Bigint => match v {
            Value::Number(n) => n
                .as_i64()
                .or_else(|| n.as_f64().map(|f| f as i64))
                .map(PgValue::Int),
            Value::String(s) => s
                .trim()
                .replace(',', "")
                .parse::<i64>()
                .ok()
                .map(PgValue::Int),
            Value::Bool(b) => Some(PgValue::Int(*b as i64)),
            _ => None,
        },
        PgType::Numeric => match v {
            Value::Number(n) => n.as_f64().map(PgValue::Num),
            Value::String(s) => s
                .trim()
                .replace(',', "")
                .parse::<f64>()
                .ok()
                .map(PgValue::Num),
            _ => None,
        },
        PgType::Bool => match v {
            Value::Bool(b) => Some(PgValue::Bool(*b)),
            Value::String(s) => match s.to_ascii_lowercase().as_str() {
                "true" | "t" | "yes" | "1" => Some(PgValue::Bool(true)),
                "false" | "f" | "no" | "0" => Some(PgValue::Bool(false)),
                _ => None,
            },
            Value::Number(n) => Some(PgValue::Bool(n.as_f64().unwrap_or(0.0) != 0.0)),
            _ => None,
        },
        PgType::Jsonb => Some(PgValue::Json(v.to_string())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn dotted_path_walks_objects_and_arrays() {
        let v = json!({"a": {"b": [ {"c": 7} ]}, "n": null});
        assert_eq!(json_at(&v, "a.b.0.c"), Some(&json!(7)));
        assert_eq!(json_at(&v, "a.x"), None);
        assert_eq!(json_at(&v, "n"), None, "null is treated as absent");
    }

    #[test]
    fn coercions_are_lenient() {
        assert_eq!(
            json_to_pg(Some(&json!("1,299")), PgType::Numeric),
            Some(PgValue::Num(1299.0))
        );
        assert_eq!(
            json_to_pg(Some(&json!(42)), PgType::Text),
            Some(PgValue::Text("42".into()))
        );
        assert_eq!(
            json_to_pg(Some(&json!("true")), PgType::Bool),
            Some(PgValue::Bool(true))
        );
        assert_eq!(
            json_to_pg(Some(&json!({"a":1})), PgType::Jsonb),
            Some(PgValue::Json("{\"a\":1}".into()))
        );
        assert_eq!(json_to_pg(None, PgType::Int), None);
    }

    #[test]
    fn unset_convention() {
        assert!(PgValue::Text(String::new()).is_unset());
        assert!(PgValue::Int(-1).is_unset());
        assert!(PgValue::Bool(false).is_unset());
        assert!(!PgValue::Text("in".into()).is_unset());
        assert!(!PgValue::Int(0).is_unset());
    }
}
