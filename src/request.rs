//! URL construction, response parsing and status mapping. Pure functions; the host HTTP call
//! itself lives in lib.rs. Every error string here is safe to surface: none contains a URL.

use serde_json::Value;
use std::collections::BTreeMap;

pub const EMPTY_RESULT_MARKER: &str = "hasn't returned any results";

/// Build the canonical `/search` URL. Parameters are sorted so identical queries produce
/// identical URLs and hit SerpApi's one-hour cache.
pub fn search_url(
    base: &str,
    api_engine: &str,
    api_params: &BTreeMap<String, String>,
    query: Option<(&str, &str)>,
    page: Option<(&str, &str)>,
    json_restrictor: Option<&str>,
    api_key: &str,
) -> String {
    let mut pairs: BTreeMap<&str, &str> = api_params
        .iter()
        .map(|(k, v)| (k.as_str(), v.as_str()))
        .collect();
    if let Some((k, v)) = query {
        pairs.insert(k, v);
    }
    if let Some((k, v)) = page {
        pairs.insert(k, v);
    }
    let mut url = format!(
        "{}/search.json?engine={}",
        base.trim_end_matches('/'),
        urlencoding::encode(api_engine)
    );
    for (k, v) in pairs {
        url.push('&');
        url.push_str(&urlencoding::encode(k));
        url.push('=');
        url.push_str(&urlencoding::encode(v));
    }
    if let Some(r) = json_restrictor {
        url.push_str("&json_restrictor=");
        url.push_str(&urlencoding::encode(r));
    }
    url.push_str("&api_key=");
    url.push_str(&urlencoding::encode(api_key));
    url
}

pub fn archive_url(base: &str, search_id: &str, ext: &str, api_key: &str) -> String {
    format!(
        "{}/searches/{}.{}?api_key={}",
        base.trim_end_matches('/'),
        urlencoding::encode(search_id),
        ext,
        urlencoding::encode(api_key)
    )
}

pub fn account_url(base: &str, api_key: &str) -> String {
    format!(
        "{}/account.json?api_key={}",
        base.trim_end_matches('/'),
        urlencoding::encode(api_key)
    )
}

/// The json_restrictor value for a typed table: keep metadata, pagination, error and the block.
pub fn restrictor_for_block(block: &str) -> String {
    format!("search_metadata,search_parameters,error,serpapi_pagination,{block}")
}

/// Replace the api_key value in a URL (defensive; we never log URLs anyway).
pub fn redact(url: &str) -> String {
    match url.find("api_key=") {
        Some(i) => {
            let start = i + "api_key=".len();
            let end = url[start..]
                .find('&')
                .map(|j| start + j)
                .unwrap_or(url.len());
            format!("{}[REDACTED]{}", &url[..start], &url[end..])
        }
        None => url.to_string(),
    }
}

#[derive(Debug, Clone)]
pub struct ParsedSearch {
    pub search_id: Option<String>,
    pub search_parameters: Option<Value>,
    /// Result rows from `block`, or a single element (the whole response) when block is None.
    pub rows: Vec<Value>,
    pub next_page_token: Option<String>,
    /// SerpApi answered successfully but the engine returned nothing (still costs a credit).
    pub empty: bool,
    #[allow(dead_code)] // kept for debugging / future engines that need the whole response
    pub full: Value,
}

fn status_error(status: u16, body: &str) -> String {
    let msg = serde_json::from_str::<Value>(body)
        .ok()
        .and_then(|v| v.get("error").and_then(|e| e.as_str()).map(str::to_string))
        .unwrap_or_default();
    match status {
        401 => "serpapi: invalid API key (HTTP 401). Check the Vault secret named in api_key_name."
            .to_string(),
        429 => format!(
            "serpapi: rate limited by SerpApi (HTTP 429){}. The free plan allows 50 searches/hour; the wrapper's hourly_cap should normally prevent this.",
            if msg.is_empty() {
                String::new()
            } else {
                format!(": {msg}")
            }
        ),
        400 => format!(
            "serpapi: bad request (HTTP 400){}",
            if msg.is_empty() {
                String::new()
            } else {
                format!(": {msg}")
            }
        ),
        s if s >= 500 => format!("serpapi: upstream error (HTTP {s}); retry later"),
        s => format!(
            "serpapi: unexpected HTTP {s}{}",
            if msg.is_empty() {
                String::new()
            } else {
                format!(": {msg}")
            }
        ),
    }
}

/// Parse a `/search.json` or `/searches/{id}.json` body.
pub fn parse_search(status: u16, body: &str, block: Option<&str>) -> Result<ParsedSearch, String> {
    if status != 200 {
        return Err(status_error(status, body));
    }
    let full: Value = serde_json::from_str(body)
        .map_err(|e| format!("serpapi: could not parse response JSON: {e}"))?;
    let search_id = full
        .get("search_metadata")
        .and_then(|m| m.get("id"))
        .and_then(|v| v.as_str())
        .map(str::to_string);
    let search_parameters = full.get("search_parameters").cloned();
    if let Some(err) = full.get("error").and_then(|e| e.as_str()) {
        if err.contains(EMPTY_RESULT_MARKER) {
            return Ok(ParsedSearch {
                search_id,
                search_parameters,
                rows: vec![],
                next_page_token: None,
                empty: true,
                full,
            });
        }
        return Err(format!("serpapi: {err}"));
    }
    let next_page_token = full
        .get("serpapi_pagination")
        .and_then(|p| p.get("next_page_token"))
        .and_then(|v| v.as_str())
        .map(str::to_string);
    let rows = match block {
        Some(b) => full
            .get(b)
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default(),
        None => vec![full.clone()],
    };
    Ok(ParsedSearch {
        search_id,
        search_parameters,
        rows,
        next_page_token,
        empty: false,
        full,
    })
}

/// Parse `/account.json`, stripping the api_key field so it can never be emitted.
pub fn parse_account(status: u16, body: &str) -> Result<Value, String> {
    if status != 200 {
        return Err(status_error(status, body));
    }
    let mut v: Value = serde_json::from_str(body)
        .map_err(|e| format!("serpapi: could not parse account JSON: {e}"))?;
    if let Some(obj) = v.as_object_mut() {
        obj.remove("api_key");
    }
    Ok(v)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn url_is_canonical_and_sorted() {
        let mut p = BTreeMap::new();
        p.insert(
            "location".to_string(),
            "Bengaluru,Karnataka,India".to_string(),
        );
        p.insert("gl".to_string(), "in".to_string());
        let u = search_url(
            "https://serpapi.com",
            "google_shopping",
            &p,
            Some(("q", "boAt Airdopes 141")),
            None,
            Some("shopping_results"),
            "KEY",
        );
        assert_eq!(
            u,
            "https://serpapi.com/search.json?engine=google_shopping&gl=in&location=Bengaluru%2CKarnataka%2CIndia&q=boAt%20Airdopes%20141&json_restrictor=shopping_results&api_key=KEY"
        );
    }

    #[test]
    fn redaction_hides_the_key() {
        let u = "https://serpapi.com/search.json?q=x&api_key=SECRET&engine=google";
        assert_eq!(
            redact(u),
            "https://serpapi.com/search.json?q=x&api_key=[REDACTED]&engine=google"
        );
        assert!(!redact("https://serpapi.com/searches/1.json?api_key=SECRET").contains("SECRET"));
    }

    #[test]
    fn empty_result_is_not_an_error() {
        let body = r#"{"search_metadata":{"id":"abc","status":"Success"},"error":"Google hasn't returned any results for this query."}"#;
        let p = parse_search(200, body, Some("shopping_results")).unwrap();
        assert!(p.empty);
        assert_eq!(p.search_id.as_deref(), Some("abc"));
        assert!(p.rows.is_empty());
    }

    #[test]
    fn block_rows_and_token() {
        let body = r#"{"search_metadata":{"id":"s1"},"jobs_results":[{"title":"A"},{"title":"B"}],"serpapi_pagination":{"next_page_token":"tok"}}"#;
        let p = parse_search(200, body, Some("jobs_results")).unwrap();
        assert_eq!(p.rows.len(), 2);
        assert_eq!(p.next_page_token.as_deref(), Some("tok"));
        let g = parse_search(200, body, None).unwrap();
        assert_eq!(g.rows.len(), 1, "generic mode yields one row per page");
    }

    #[test]
    fn status_errors_never_contain_urls() {
        for s in [400u16, 401, 429, 500, 503] {
            let e = parse_search(s, r#"{"error":"Invalid API key. Your API key should be here: https://serpapi.com/manage-api-key"}"#, Some("x")).unwrap_err();
            assert!(e.starts_with("serpapi:"));
            assert!(!e.contains("api_key="));
        }
    }

    #[test]
    fn account_strips_key() {
        let v = parse_account(
            200,
            r#"{"account_id":"1","api_key":"SECRET","plan_searches_left":213}"#,
        )
        .unwrap();
        assert!(v.get("api_key").is_none());
        assert_eq!(v["plan_searches_left"], 213);
    }
}
