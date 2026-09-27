//! DDL generation for `import foreign schema`. Postgres executes the returned statements
//! inside the target schema itself, so table names must NOT be schema-qualified.
//!
//! Column order is the contract shared with `scripts/gen.py` (which emits the matching
//! composite types and public functions):
//!   [params in catalog order] pages int, search_id text, page int, [result columns], raw jsonb

use crate::catalog::{
    Catalog, EngineSpec, PgType, STD_COL_PAGE, STD_COL_RAW, STD_PARAM_PAGES, STD_PARAM_SEARCH_ID,
};

pub fn quote_ident(s: &str) -> String {
    format!("\"{}\"", s.replace('"', "\"\""))
}

pub fn typed_table_ddl(cat: &Catalog, name: &str, spec: &EngineSpec, server: &str) -> String {
    let mut cols: Vec<String> = Vec::new();
    for p in cat.param_specs(spec) {
        cols.push(format!("  {} {}", quote_ident(&p.name), p.ty.sql()));
    }
    cols.push(format!(
        "  {} {}",
        quote_ident(STD_PARAM_PAGES),
        PgType::Int.sql()
    ));
    cols.push(format!(
        "  {} {}",
        quote_ident(STD_PARAM_SEARCH_ID),
        PgType::Text.sql()
    ));
    cols.push(format!(
        "  {} {}",
        quote_ident(STD_COL_PAGE),
        PgType::Int.sql()
    ));
    for c in &spec.columns {
        cols.push(format!("  {} {}", quote_ident(&c.name), c.ty.sql()));
    }
    cols.push(format!(
        "  {} {}",
        quote_ident(STD_COL_RAW),
        PgType::Jsonb.sql()
    ));
    format!(
        "create foreign table if not exists {} (\n{}\n) server {} options (\n  engine '{}'\n)",
        quote_ident(name),
        cols.join(",\n"),
        quote_ident(server),
        name
    )
}

pub fn object_table_ddl(cat: &Catalog, object: &str, server: &str) -> Option<String> {
    let spec = cat.objects.get(object)?;
    Some(format!(
        "create foreign table if not exists {} (\n  {}\n) server {} options (\n  object '{}'\n)",
        quote_ident(&spec.table),
        spec.columns_sql.replace(", ", ",\n  "),
        quote_ident(server),
        object
    ))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ListType {
    All,
    LimitTo,
    Except,
}

/// All DDL statements for the import, honouring LIMIT TO / EXCEPT.
pub fn import_ddl(cat: &Catalog, server: &str, list: ListType, tables: &[String]) -> Vec<String> {
    let wanted = |name: &str| match list {
        ListType::All => true,
        ListType::LimitTo => tables.iter().any(|t| t == name),
        ListType::Except => !tables.iter().any(|t| t == name),
    };
    let mut out = Vec::new();
    for (name, spec) in &cat.engines {
        if wanted(name) {
            out.push(typed_table_ddl(cat, name, spec, server));
        }
    }
    for (object, spec) in &cat.objects {
        if wanted(&spec.table)
            && let Some(ddl) = object_table_ddl(cat, object, server)
        {
            out.push(ddl);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shopping_ddl_has_contract_column_order_and_no_schema() {
        let c = Catalog::load().unwrap();
        let ddl = typed_table_ddl(
            &c,
            "google_shopping",
            c.engine("google_shopping").unwrap(),
            "serpapi",
        );
        assert!(
            ddl.starts_with("create foreign table if not exists \"google_shopping\" ("),
            "{ddl}"
        );
        let q = ddl.find("\"q\" text").unwrap();
        let gl = ddl.find("\"gl\" text").unwrap();
        let pages = ddl.find("\"pages\" int").unwrap();
        let sid = ddl.find("\"search_id\" text").unwrap();
        let page = ddl.find("\"page\" int").unwrap();
        let title = ddl.find("\"title\" text").unwrap();
        let raw = ddl.find("\"raw\" jsonb").unwrap();
        assert!(
            q < gl && gl < pages && pages < sid && sid < page && page < title && title < raw,
            "{ddl}"
        );
        assert!(ddl.contains("options (\n  engine 'google_shopping'\n)"));
    }

    #[test]
    fn limit_to_and_except_filter() {
        let c = Catalog::load().unwrap();
        let all = import_ddl(&c, "s", ListType::All, &[]);
        assert_eq!(all.len(), c.engines.len() + c.objects.len());
        let two = import_ddl(
            &c,
            "s",
            ListType::LimitTo,
            &["google_jobs".into(), "search".into()],
        );
        assert_eq!(two.len(), 2);
        let except = import_ddl(&c, "s", ListType::Except, &["account".into()]);
        assert_eq!(except.len(), all.len() - 1);
    }
}
