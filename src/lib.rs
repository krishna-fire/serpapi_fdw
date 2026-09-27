//! serpapi_fdw — SerpApi as Postgres foreign tables for Supabase Wrappers (Wasm FDW).
//!
//! This file is the only place that touches the host bindings. All decision logic lives in
//! the pure modules (`params`, `request`, `budget`, `schema`, `values`, `catalog`) so it can
//! be unit-tested on the host target without a Wasm runtime.

#[allow(warnings)]
#[rustfmt::skip]
mod bindings;

mod budget;
mod catalog;
mod params;
mod request;
mod schema;
mod values;

use bindings::{
    exports::supabase::wrappers::routines::Guest,
    supabase::wrappers::{
        http, stats, time,
        types::{
            Cell, Context, FdwError, FdwResult, ImportForeignSchemaStmt, ImportSchemaType,
            OptionsType, Row, TypeOid, Value as QualValue,
        },
        utils,
    },
};
use budget::Budget;
use catalog::{
    Catalog, ColumnSpec, PaginationKind, PgType, STD_COL_PAGE, STD_COL_RAW, STD_PARAM_PAGES,
    STD_PARAM_SEARCH_ID,
};
use params::{GenericParams, QualLite, ScanParams, ServerDefaults};
use std::collections::BTreeMap;
use values::{PgValue, json_at, json_to_pg};

const FDW_NAME: &str = "serpapi_fdw";
const USER_AGENT: &str = concat!("serpapi_fdw/", env!("CARGO_PKG_VERSION"));

// ---------------------------------------------------------------------------------------------
// configuration
// ---------------------------------------------------------------------------------------------

#[derive(Debug, Default)]
struct ServerCfg {
    api_url: String,
    key_name: Option<String>,
    key_id: Option<String>,
    key_plain: Option<String>,
    defaults: ServerDefaults,
    hourly_cap: u32,
    monthly_cap: u32,
    max_pages: u32,
    json_restrictor: bool,
}

#[derive(Debug, Clone)]
enum Mode {
    Typed(String),
    Generic,
    Account,
}

struct ColMeta {
    name: String,
    oid: TypeOid,
}

#[derive(Default)]
struct Scan {
    mode: Option<Mode>,
    cols: Vec<ColMeta>,
    col_specs: BTreeMap<String, ColumnSpec>,
    sp: Option<ScanParams>,
    gp: Option<GenericParams>,
    q_idx: usize,
    page_idx: u32,
    next_token: Option<String>,
    rows: Vec<serde_json::Value>,
    row_idx: usize,
    cur_search_id: Option<String>,
    cur_search_params: Option<serde_json::Value>,
    limit: Option<i64>,
    emitted: i64,
    markdown_cache: Option<(String, String)>,
}

struct SerpApiFdw {
    cat: Catalog,
    cfg: ServerCfg,
    key: Option<String>,
    scan: Scan,
}

static mut INSTANCE: *mut SerpApiFdw = std::ptr::null_mut::<SerpApiFdw>();

impl SerpApiFdw {
    fn init_instance(cat: Catalog) {
        let instance = SerpApiFdw {
            cat,
            cfg: ServerCfg::default(),
            key: None,
            scan: Scan::default(),
        };
        unsafe {
            INSTANCE = Box::leak(Box::new(instance));
        }
    }

    fn this_mut() -> &'static mut Self {
        unsafe { &mut (*INSTANCE) }
    }

    // ------------------------------------------------------------------ options & key

    fn load_server_options(&mut self, ctx: &Context) -> Result<(), FdwError> {
        let opts = ctx.get_options(&OptionsType::Server);
        let cat_default = |k: &str| self.cat.server_default(k).unwrap_or("").to_string();
        let get_or = |k: &str| opts.get(k).unwrap_or_else(|| cat_default(k));

        self.cfg.api_url = get_or("api_url");
        if !(self.cfg.api_url.starts_with("https://") || self.cfg.api_url.starts_with("http://")) {
            return Err("serpapi: api_url must start with http:// or https://".into());
        }
        self.cfg.key_name = opts.get("api_key_name");
        self.cfg.key_id = opts.get("api_key_id");
        self.cfg.key_plain = opts.get("api_key");

        let mut defaults = BTreeMap::new();
        for k in self
            .cat
            .server_options
            .keys()
            .filter(|k| k.starts_with("default_"))
        {
            let v = get_or(k);
            if !v.is_empty() {
                defaults.insert(k.clone(), v);
            }
        }
        self.cfg.defaults = ServerDefaults(defaults);

        let parse_u32 = |k: &str| -> Result<u32, FdwError> {
            let s = get_or(k);
            s.trim().parse::<u32>().map_err(|_| {
                format!("serpapi: server option {k} must be a non-negative integer (got '{s}')")
            })
        };
        self.cfg.hourly_cap = parse_u32("hourly_cap")?;
        self.cfg.monthly_cap = parse_u32("monthly_cap")?;
        self.cfg.max_pages = parse_u32("max_pages")?.max(1);
        if let Some(g) =
            utils::query_setting("serpapi.max_pages").and_then(|s| s.trim().parse::<u32>().ok())
        {
            self.cfg.max_pages = self.cfg.max_pages.min(g.max(1));
        }
        self.cfg.json_restrictor = !matches!(
            get_or("json_restrictor").to_ascii_lowercase().as_str(),
            "off" | "false" | "0"
        );
        Ok(())
    }

    fn api_key(&mut self) -> Result<String, FdwError> {
        if let Some(k) = &self.key {
            return Ok(k.clone());
        }
        let key = if let Some(name) = &self.cfg.key_name {
            utils::get_vault_secret_by_name(name)
                .ok_or_else(|| format!("serpapi: Vault secret '{name}' not found (api_key_name)"))?
        } else if let Some(id) = &self.cfg.key_id {
            utils::get_vault_secret(id)
                .ok_or_else(|| "serpapi: Vault secret for api_key_id not found".to_string())?
        } else if let Some(plain) = &self.cfg.key_plain {
            let allowed = utils::query_setting("serpapi.allow_plain_key")
                .map(|v| matches!(v.to_ascii_lowercase().as_str(), "on" | "true" | "1"))
                .unwrap_or(false);
            if !allowed {
                return Err("serpapi: a plain api_key server option is only honoured when `set serpapi.allow_plain_key = on` (local development). Prefer api_key_name with a Vault secret.".into());
            }
            plain.clone()
        } else {
            return Err("serpapi: no API key configured. Create a Vault secret and set api_key_name on the foreign server.".into());
        };
        if key.trim().is_empty() {
            return Err("serpapi: API key is empty".into());
        }
        self.key = Some(key.clone());
        Ok(key)
    }

    // ------------------------------------------------------------------ HTTP

    fn http_get(&self, url: String) -> Result<(u16, String), FdwError> {
        let req = http::Request {
            method: http::Method::Get,
            url,
            headers: vec![
                ("user-agent".into(), USER_AGENT.into()),
                ("accept".into(), "application/json, text/markdown".into()),
            ],
            body: String::new(),
        };
        // Never call http::error_for_status: the host formats the full URL (with api_key) into it.
        let resp =
            http::get(&req).map_err(|e| format!("serpapi: HTTP error: {}", request::redact(&e)))?;
        stats::inc_stats(FDW_NAME, stats::Metric::BytesIn, resp.body.len() as i64);
        Ok((resp.status_code, resp.body))
    }

    /// One `/search` call with budget accounting. Returns the parsed page.
    fn search_page(
        &mut self,
        api_engine: &str,
        api_params: &BTreeMap<String, String>,
        query: Option<(&str, &str)>,
        page: Option<(&str, &str)>,
        block: Option<&str>,
    ) -> Result<request::ParsedSearch, FdwError> {
        let now = time::epoch_secs();
        let mut budget = Budget::load(stats::get_metadata(FDW_NAME).as_deref(), now);
        budget.check(1, self.cfg.hourly_cap, self.cfg.monthly_cap, now)?;

        let key = self.api_key()?;
        let restrictor = match (self.cfg.json_restrictor, block) {
            (true, Some(b)) => Some(request::restrictor_for_block(b)),
            _ => None,
        };
        let url = request::search_url(
            &self.cfg.api_url,
            api_engine,
            api_params,
            query,
            page,
            restrictor.as_deref(),
            &key,
        );
        let (status, body) = self.http_get(url)?;
        if status == 200 {
            budget.record(now);
            stats::set_metadata(FDW_NAME, &Some(budget.to_metadata()));
            stats::inc_stats(FDW_NAME, stats::Metric::CreateTimes, 1);
        }
        let parsed = request::parse_search(status, &body, block)?;
        if parsed.empty {
            utils::report_notice(&format!(
                "serpapi: no results for this query (engine {api_engine}, search_id {})",
                parsed.search_id.as_deref().unwrap_or("?")
            ));
        }
        Ok(parsed)
    }

    fn archive_page(
        &mut self,
        search_id: &str,
        block: Option<&str>,
    ) -> Result<request::ParsedSearch, FdwError> {
        let key = self.api_key()?;
        let url = request::archive_url(&self.cfg.api_url, search_id, "json", &key);
        let (status, body) = self.http_get(url)?;
        request::parse_search(status, &body, block).map_err(|e| {
            if status == 404 {
                format!("serpapi: search_id '{search_id}' not found in the archive (kept 31 days)")
            } else {
                e
            }
        })
    }

    fn archive_markdown(&mut self, search_id: &str) -> Result<String, FdwError> {
        if let Some((sid, md)) = &self.scan.markdown_cache
            && sid == search_id
        {
            return Ok(md.clone());
        }
        let key = self.api_key()?;
        let url = request::archive_url(&self.cfg.api_url, search_id, "md", &key);
        let (status, body) = self.http_get(url)?;
        if status != 200 {
            return Err(format!(
                "serpapi: could not fetch Markdown for search_id '{search_id}' (HTTP {status})"
            ));
        }
        self.scan.markdown_cache = Some((search_id.to_string(), body.clone()));
        Ok(body)
    }

    // ------------------------------------------------------------------ scan driving

    fn typed_spec(&self) -> Result<(&catalog::EngineSpec, &ScanParams), FdwError> {
        let name = match &self.scan.mode {
            Some(Mode::Typed(n)) => n,
            _ => return Err("serpapi: internal: not a typed scan".into()),
        };
        let spec = self
            .cat
            .engine(name)
            .ok_or_else(|| format!("serpapi: unknown engine '{name}'"))?;
        let sp = self
            .scan
            .sp
            .as_ref()
            .ok_or_else(|| "serpapi: internal: scan params missing".to_string())?;
        Ok((spec, sp))
    }

    fn fetch_current(&mut self) -> Result<(), FdwError> {
        self.scan.rows.clear();
        self.scan.row_idx = 0;
        match self.scan.mode.clone() {
            Some(Mode::Typed(_)) => {
                let (spec, sp) = self.typed_spec()?;
                let block = spec.block.clone();
                let api_engine = spec.api_engine.clone();
                let kind = spec.pagination.kind;
                let step = spec.pagination.step.unwrap_or(10);
                let sp = sp.clone();

                if let Some(sid) = &sp.search_id {
                    let parsed = self.archive_page(sid, Some(&block))?;
                    self.scan.cur_search_id = Some(sid.clone());
                    self.scan.cur_search_params = parsed.search_parameters;
                    self.scan.rows = parsed.rows;
                    self.scan.next_token = None;
                    return Ok(());
                }

                let page_val: Option<String> = match (kind, self.scan.page_idx) {
                    (_, 0) => None,
                    (PaginationKind::None, _) => None,
                    (PaginationKind::Start, i) => Some((i * step).to_string()),
                    (PaginationKind::Page, i) => Some((i + 1).to_string()),
                    (PaginationKind::NextPageToken, _) => self.scan.next_token.clone(),
                };
                let page_param = match kind {
                    PaginationKind::Start => "start",
                    PaginationKind::Page => "page",
                    PaginationKind::NextPageToken => "next_page_token",
                    PaginationKind::None => "",
                };
                let page = page_val.as_deref().map(|v| (page_param, v));
                let qv = sp.query_values.get(self.scan.q_idx).cloned();
                let query = match (&sp.query_api_name, &qv) {
                    (Some(k), Some(v)) => Some((k.as_str(), v.as_str())),
                    _ => None,
                };
                let parsed =
                    self.search_page(&api_engine, &sp.api_params, query, page, Some(&block))?;
                self.scan.cur_search_id = parsed.search_id;
                self.scan.cur_search_params = parsed.search_parameters;
                self.scan.next_token = parsed.next_page_token;
                self.scan.rows = parsed.rows;
                Ok(())
            }
            Some(Mode::Generic) => {
                let gp = self
                    .scan
                    .gp
                    .clone()
                    .ok_or_else(|| "serpapi: internal: generic params missing".to_string())?;
                if let Some(sid) = &gp.search_id {
                    let parsed = self.archive_page(sid, None)?;
                    self.scan.cur_search_id = Some(sid.clone());
                    self.scan.cur_search_params = parsed.search_parameters;
                    self.scan.rows = parsed.rows;
                    self.scan.next_token = None;
                    return Ok(());
                }
                let engine = gp.engine.clone().unwrap_or_default();
                let page = match (self.scan.page_idx, &self.scan.next_token) {
                    (0, _) => None,
                    (_, Some(t)) => Some(("next_page_token", t.as_str())),
                    (_, None) => None,
                };
                let page_owned = page.map(|(k, v)| (k, v.to_string()));
                let page_ref = page_owned.as_ref().map(|(k, v)| (*k, v.as_str()));
                let parsed = self.search_page(&engine, &gp.api_params, None, page_ref, None)?;
                self.scan.cur_search_id = parsed.search_id;
                self.scan.cur_search_params = parsed.search_parameters;
                self.scan.next_token = parsed.next_page_token;
                self.scan.rows = parsed.rows;
                Ok(())
            }
            Some(Mode::Account) => {
                let key = self.api_key()?;
                let url = request::account_url(&self.cfg.api_url, &key);
                let (status, body) = self.http_get(url)?;
                let v = request::parse_account(status, &body)?;
                self.scan.rows = vec![v];
                Ok(())
            }
            None => Err("serpapi: internal: scan mode not set".into()),
        }
    }

    /// Whether another page for the current query is allowed and likely to exist.
    fn can_page(&self) -> bool {
        let (pages, kind) = match &self.scan.mode {
            Some(Mode::Typed(name)) => {
                let Some(spec) = self.cat.engine(name) else {
                    return false;
                };
                let Some(sp) = &self.scan.sp else {
                    return false;
                };
                if sp.search_id.is_some() {
                    return false;
                }
                (sp.pages, spec.pagination.kind)
            }
            Some(Mode::Generic) => {
                let Some(gp) = &self.scan.gp else {
                    return false;
                };
                if gp.search_id.is_some() {
                    return false;
                }
                (gp.pages, PaginationKind::NextPageToken)
            }
            _ => return false,
        };
        if self.scan.page_idx + 1 >= pages || self.scan.rows.is_empty() {
            return false;
        }
        match kind {
            PaginationKind::None => false,
            PaginationKind::Start | PaginationKind::Page => true,
            PaginationKind::NextPageToken => self.scan.next_token.is_some(),
        }
    }

    fn advance(&mut self) -> Result<bool, FdwError> {
        if let Some(l) = self.scan.limit
            && self.scan.emitted >= l
        {
            return Ok(false);
        }
        if self.can_page() {
            self.scan.page_idx += 1;
            self.fetch_current()?;
            return Ok(true);
        }
        if let (Some(Mode::Typed(_)), Some(sp)) = (&self.scan.mode, &self.scan.sp)
            && sp.search_id.is_none()
            && self.scan.q_idx + 1 < sp.query_values.len()
        {
            self.scan.q_idx += 1;
            self.scan.page_idx = 0;
            self.scan.next_token = None;
            self.fetch_current()?;
            return Ok(true);
        }
        Ok(false)
    }

    // ------------------------------------------------------------------ row emission

    fn emit_typed(&mut self, row: &Row) -> Result<(), FdwError> {
        let (_, sp) = self.typed_spec()?;
        let sp = sp.clone();
        let src = self.scan.rows[self.scan.row_idx].clone();
        let cur_q = sp.query_values.get(self.scan.q_idx).cloned();
        for i in 0..self.scan.cols.len() {
            let name = self.scan.cols[i].name.clone();
            let oid = self.scan.cols[i].oid.clone();
            let val: Option<PgValue> = if Some(&name) == sp.query_column.as_ref() {
                cur_q.clone().map(PgValue::Text)
            } else if name == STD_PARAM_PAGES {
                Some(PgValue::Int(sp.pages as i64))
            } else if name == STD_PARAM_SEARCH_ID {
                sp.search_id
                    .clone()
                    .or_else(|| self.scan.cur_search_id.clone())
                    .map(PgValue::Text)
            } else if name == STD_COL_PAGE {
                Some(PgValue::Int(self.scan.page_idx as i64 + 1))
            } else if name == STD_COL_RAW {
                Some(PgValue::Json(src.to_string()))
            } else if let Some(echo) = sp.echo.get(&name) {
                echo.clone()
            } else if let Some(spec) = self.scan.col_specs.get(&name) {
                json_to_pg(json_at(&src, &spec.path), spec.ty)
            } else {
                None
            };
            let cell = val.map(|v| to_cell(&v, &oid));
            row.push(cell.as_ref());
        }
        Ok(())
    }

    fn emit_generic(&mut self, row: &Row) -> Result<(), FdwError> {
        let gp = self
            .scan
            .gp
            .clone()
            .ok_or_else(|| "serpapi: internal: generic params missing".to_string())?;
        let src = self.scan.rows[self.scan.row_idx].clone();
        let sid = gp
            .search_id
            .clone()
            .or_else(|| self.scan.cur_search_id.clone());
        for i in 0..self.scan.cols.len() {
            let name = self.scan.cols[i].name.clone();
            let oid = self.scan.cols[i].oid.clone();
            let val: Option<PgValue> = match name.as_str() {
                "engine" => gp
                    .engine
                    .clone()
                    .or_else(|| {
                        self.scan
                            .cur_search_params
                            .as_ref()
                            .and_then(|p| p.get("engine"))
                            .and_then(|e| e.as_str())
                            .map(str::to_string)
                    })
                    .map(PgValue::Text),
                "params" => gp.params_given.clone().map(PgValue::Json).or_else(|| {
                    self.scan.cur_search_params.clone().map(|mut p| {
                        if let Some(o) = p.as_object_mut() {
                            o.remove("engine");
                            o.remove("api_key");
                        }
                        PgValue::Json(p.to_string())
                    })
                }),
                STD_PARAM_PAGES => Some(PgValue::Int(gp.pages as i64)),
                STD_PARAM_SEARCH_ID => sid.clone().map(PgValue::Text),
                STD_COL_PAGE => Some(PgValue::Int(self.scan.page_idx as i64 + 1)),
                "result" => Some(PgValue::Json(src.to_string())),
                "markdown" => match &sid {
                    Some(s) => Some(PgValue::Text(self.archive_markdown(s)?)),
                    None => None,
                },
                _ => None,
            };
            let cell = val.map(|v| to_cell(&v, &oid));
            row.push(cell.as_ref());
        }
        Ok(())
    }

    fn emit_account(&mut self, row: &Row) -> Result<(), FdwError> {
        let src = self.scan.rows[self.scan.row_idx].clone();
        for i in 0..self.scan.cols.len() {
            let name = self.scan.cols[i].name.clone();
            let oid = self.scan.cols[i].oid.clone();
            let val = if name == STD_COL_RAW {
                Some(PgValue::Json(src.to_string()))
            } else {
                json_to_pg(src.get(&name), oid_to_pgtype(&oid))
            };
            let cell = val.map(|v| to_cell(&v, &oid));
            row.push(cell.as_ref());
        }
        Ok(())
    }
}

// ---------------------------------------------------------------------------------------------
// conversions between host cells and our value types
// ---------------------------------------------------------------------------------------------

fn cell_to_pg(c: &Cell) -> PgValue {
    match c {
        Cell::String(s) => PgValue::Text(s.clone()),
        Cell::I8(i) => PgValue::Int(*i as i64),
        Cell::I16(i) => PgValue::Int(*i as i64),
        Cell::I32(i) => PgValue::Int(*i as i64),
        Cell::I64(i) => PgValue::Int(*i),
        Cell::F32(f) => PgValue::Num(*f as f64),
        Cell::F64(f) => PgValue::Num(*f),
        Cell::Numeric(f) => PgValue::Num(*f),
        Cell::Bool(b) => PgValue::Bool(*b),
        Cell::Json(s) => PgValue::Json(s.clone()),
        other => PgValue::Text(utils::cell_to_string(Some(other))),
    }
}

fn oid_to_pgtype(oid: &TypeOid) -> PgType {
    match oid {
        TypeOid::Bool => PgType::Bool,
        TypeOid::I8 | TypeOid::I16 | TypeOid::I32 => PgType::Int,
        TypeOid::I64 => PgType::Bigint,
        TypeOid::F32 | TypeOid::F64 | TypeOid::Numeric => PgType::Numeric,
        TypeOid::Json => PgType::Jsonb,
        _ => PgType::Text,
    }
}

fn as_text(v: &PgValue) -> String {
    match v {
        PgValue::Text(s) | PgValue::Json(s) => s.clone(),
        other => other.as_query_string(),
    }
}

fn as_f64(v: &PgValue) -> f64 {
    match v {
        PgValue::Int(i) => *i as f64,
        PgValue::Num(n) => *n,
        PgValue::Bool(b) => *b as i64 as f64,
        PgValue::Text(s) | PgValue::Json(s) => s.trim().parse().unwrap_or(0.0),
    }
}

fn to_cell(v: &PgValue, oid: &TypeOid) -> Cell {
    match oid {
        TypeOid::Bool => Cell::Bool(match v {
            PgValue::Bool(b) => *b,
            PgValue::Int(i) => *i != 0,
            PgValue::Num(n) => *n != 0.0,
            PgValue::Text(s) | PgValue::Json(s) => {
                matches!(s.to_ascii_lowercase().as_str(), "true" | "t" | "1")
            }
        }),
        TypeOid::I8 => Cell::I8(as_f64(v) as i8),
        TypeOid::I16 => Cell::I16(as_f64(v) as i16),
        TypeOid::I32 => Cell::I32(as_f64(v) as i32),
        TypeOid::I64 => Cell::I64(as_f64(v) as i64),
        TypeOid::F32 => Cell::F32(as_f64(v) as f32),
        TypeOid::F64 => Cell::F64(as_f64(v)),
        TypeOid::Numeric => Cell::Numeric(as_f64(v)),
        TypeOid::Json => Cell::Json(match v {
            PgValue::Json(s) => s.clone(),
            PgValue::Text(s) => serde_json::Value::String(s.clone()).to_string(),
            PgValue::Int(i) => i.to_string(),
            PgValue::Num(n) => n.to_string(),
            PgValue::Bool(b) => b.to_string(),
        }),
        _ => Cell::String(as_text(v)),
    }
}

fn quals_lite(ctx: &Context) -> Vec<QualLite> {
    ctx.get_quals()
        .iter()
        .map(|q| {
            let (values, is_array) = match q.value() {
                QualValue::Cell(c) => (vec![cell_to_pg(&c)], false),
                QualValue::Array(cs) => (cs.iter().map(cell_to_pg).collect(), true),
            };
            QualLite {
                field: q.field(),
                op: q.operator(),
                values,
                is_array,
            }
        })
        .collect()
}

// ---------------------------------------------------------------------------------------------
// Guest implementation
// ---------------------------------------------------------------------------------------------

impl Guest for SerpApiFdw {
    fn host_version_requirement() -> String {
        "^0.1.0".to_string()
    }

    fn init(ctx: &Context) -> FdwResult {
        let cat = Catalog::load()?;
        Self::init_instance(cat);
        let this = Self::this_mut();
        this.load_server_options(ctx)?;
        // Make sure our row in wrappers_fdw_stats exists before the first get_metadata, which
        // otherwise logs a host-side "SpiTupleTable positioned before the start" warning.
        stats::inc_stats(FDW_NAME, stats::Metric::CreateTimes, 0);
        Ok(())
    }

    fn begin_scan(ctx: &Context) -> FdwResult {
        let this = Self::this_mut();
        this.scan = Scan::default();

        let topts = ctx.get_options(&OptionsType::Table);
        let mode =
            match (topts.get("engine"), topts.get("object")) {
                (Some(e), _) => Mode::Typed(e),
                (None, Some(o)) if o == "search" => Mode::Generic,
                (None, Some(o)) if o == "account" => Mode::Account,
                (None, Some(o)) => {
                    return Err(format!(
                        "serpapi: unknown table option object '{o}' (expected search or account)"
                    ));
                }
                (None, None) => return Err(
                    "serpapi: foreign table needs an `engine '<name>'` or `object '<name>'` option"
                        .into(),
                ),
            };

        this.scan.cols = ctx
            .get_columns()
            .iter()
            .map(|c| ColMeta {
                name: c.name(),
                oid: c.type_oid(),
            })
            .collect();
        this.scan.limit = ctx.get_limit().map(|l| l.offset() + l.count());
        let quals = quals_lite(ctx);

        match &mode {
            Mode::Typed(name) => {
                let spec = this.cat.engine(name).ok_or_else(|| {
                    format!(
                        "serpapi: engine '{name}' is not in the typed catalog; use the generic `search` table for it"
                    )
                })?;
                let sp = params::collect_typed(
                    &quals,
                    &this.cat,
                    spec,
                    &this.cfg.defaults,
                    this.cfg.max_pages,
                )?;
                this.scan.col_specs = spec
                    .columns
                    .iter()
                    .map(|c| (c.name.clone(), c.clone()))
                    .collect();
                this.scan.sp = Some(sp);
            }
            Mode::Generic => {
                this.scan.gp = Some(params::collect_generic(&quals, this.cfg.max_pages)?);
            }
            Mode::Account => {}
        }
        this.scan.mode = Some(mode);
        this.fetch_current()?;
        Ok(())
    }

    fn iter_scan(_ctx: &Context, row: &Row) -> Result<Option<u32>, FdwError> {
        let this = Self::this_mut();
        loop {
            if this.scan.row_idx < this.scan.rows.len() {
                match this.scan.mode.clone() {
                    Some(Mode::Typed(_)) => this.emit_typed(row)?,
                    Some(Mode::Generic) => this.emit_generic(row)?,
                    Some(Mode::Account) => this.emit_account(row)?,
                    None => return Err("serpapi: internal: scan mode not set".into()),
                }
                this.scan.row_idx += 1;
                this.scan.emitted += 1;
                stats::inc_stats(FDW_NAME, stats::Metric::RowsOut, 1);
                return Ok(Some(0));
            }
            if !this.advance()? {
                return Ok(None);
            }
        }
    }

    fn re_scan(_ctx: &Context) -> FdwResult {
        let this = Self::this_mut();
        this.scan.q_idx = 0;
        this.scan.page_idx = 0;
        this.scan.next_token = None;
        this.scan.emitted = 0;
        this.fetch_current()
    }

    fn end_scan(_ctx: &Context) -> FdwResult {
        let this = Self::this_mut();
        this.scan = Scan::default();
        Ok(())
    }

    fn begin_modify(_ctx: &Context) -> FdwResult {
        Err("serpapi: foreign tables are read-only".to_owned())
    }

    fn insert(_ctx: &Context, _row: &Row) -> FdwResult {
        Err("serpapi: foreign tables are read-only".to_owned())
    }

    fn update(_ctx: &Context, _rowid: Cell, _row: &Row) -> FdwResult {
        Err("serpapi: foreign tables are read-only".to_owned())
    }

    fn delete(_ctx: &Context, _rowid: Cell) -> FdwResult {
        Err("serpapi: foreign tables are read-only".to_owned())
    }

    fn end_modify(_ctx: &Context) -> FdwResult {
        Ok(())
    }

    fn import_foreign_schema(
        _ctx: &Context,
        stmt: ImportForeignSchemaStmt,
    ) -> Result<Vec<String>, FdwError> {
        let this = Self::this_mut();
        let list = match stmt.list_type {
            ImportSchemaType::All => schema::ListType::All,
            ImportSchemaType::LimitTo => schema::ListType::LimitTo,
            ImportSchemaType::Except => schema::ListType::Except,
        };
        let ddl = schema::import_ddl(&this.cat, &stmt.server_name, list, &stmt.table_list);
        if ddl.is_empty() {
            return Err(format!(
                "serpapi: nothing to import; known tables are {}, search, account",
                this.cat
                    .engines
                    .keys()
                    .cloned()
                    .collect::<Vec<_>>()
                    .join(", ")
            ));
        }
        Ok(ddl)
    }
}

bindings::export!(SerpApiFdw with_types_in bindings);
