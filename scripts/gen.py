#!/usr/bin/env python3
"""Generate sql/20_generated.sql from catalog/engines.json.

One source of truth, three consumers:
  * the Rust wrapper embeds the catalog (import foreign schema DDL + row mapping),
  * this script emits the public SQL surface (composite types + functions),
  * docs/engines.md (also emitted here) documents both.

Column contract with the wrapper's import foreign schema DDL (see src/schema.rs):
  [params in catalog order] pages int, search_id text, page int, [result columns], raw jsonb

Public functions never expose the foreign tables; they live in serpapi_private and are
queried only from security-definer functions in serpapi.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "catalog" / "engines.json"
OUT_SQL = ROOT / "sql" / "20_generated.sql"
OUT_DOC = ROOT / "docs" / "engines.md"

PG = {"text": "text", "int": "int", "bigint": "bigint", "numeric": "numeric", "bool": "boolean", "jsonb": "jsonb"}
# "unset" sentinel per type: what the function passes when the argument is NULL/omitted.
UNSET = {"text": "''", "int": "-1", "bigint": "-1", "numeric": "-1", "bool": "false", "jsonb": "'{}'::jsonb"}
ARG_DEFAULT = {"text": "null", "int": "null", "bigint": "null", "numeric": "null", "bool": "false", "jsonb": "null"}


def qi(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


def param_specs(cat: dict, spec: dict) -> list[dict]:
    ps = list(spec["params"])
    out = ps[:1] + list(cat.get("common_params", [])) + ps[1:]
    return out


def result_type_name(engine: str) -> str:
    return f"{engine}_result"


def gen_engine(cat: dict, name: str, spec: dict) -> tuple[str, str]:
    params = param_specs(cat, spec)
    cols = spec["columns"]
    rt = result_type_name(name)

    # composite type: search_id, page, result columns, raw
    type_cols = ["search_id text", "page int"] + [f"{qi(c['name'])} {PG[c['type']]}" for c in cols] + ["raw jsonb"]
    type_sql = f"create type serpapi.{qi(rt)} as (\n  " + ",\n  ".join(type_cols) + "\n);"

    # function args: params (first one required, others default null), pages
    args = []
    for i, p in enumerate(params):
        default = "" if (i == 0 and p["name"] in spec.get("required", [])) else f" default {ARG_DEFAULT[p['type']]}"
        args.append(f"  {qi(p['name'])} {PG[p['type']]}{default}")
    args.append("  pages int default 1")
    args_sql = ",\n".join(args)

    select_cols = ["f.search_id", "f.page"] + [f"f.{qi(c['name'])}" for c in cols] + ["f.raw"]
    where = []
    for p in params:
        n = qi(p["name"])
        if p["type"] == "bool":
            where.append(f"f.{n} = coalesce({n}, false)")
        else:
            where.append(f"f.{n} = coalesce({n}, {UNSET[p['type']]})")
    where.append("f.pages = coalesce(pages, 1)")

    params_json = ", ".join(f"'{p['name']}', {qi(p['name'])}" for p in params)

    doc = (spec.get("doc") or "").replace("'", "''")
    fn_sql = f"""create function serpapi.{qi(name)}(
{args_sql}
) returns setof serpapi.{qi(rt)}
language plpgsql volatile security definer
set search_path = ''
set statement_timeout = '25s'
set plan_cache_mode = 'force_custom_plan'
as $$
#variable_conflict use_variable
declare
  t0 timestamptz := clock_timestamp();
  n int;
begin
  perform serpapi_private.check_quota(coalesce(pages, 1));
  return query
    select {", ".join(select_cols)}
    from serpapi_private.{qi(name)} f
    where {"\n      and ".join(where)};
  get diagnostics n = row_count;
  perform serpapi_private.log_request('{name}', jsonb_strip_nulls(jsonb_build_object({params_json}, 'pages', pages)), n, extract(milliseconds from clock_timestamp() - t0)::int);
end $$;
comment on function serpapi.{qi(name)} is '{doc}';
revoke execute on function serpapi.{qi(name)} from public;
"""

    replay_sql = f"""create function serpapi.{qi("replay_" + name)}(search_id text)
returns setof serpapi.{qi(rt)}
language plpgsql stable security definer
set search_path = ''
set statement_timeout = '25s'
set plan_cache_mode = 'force_custom_plan'
as $$
#variable_conflict use_variable
begin
  return query
    select {", ".join(select_cols)}
    from serpapi_private.{qi(name)} f
    where f.search_id = search_id;
end $$;
comment on function serpapi.{qi("replay_" + name)} is 'Re-read a past {name} search from the SerpApi archive (free for 31 days).';
revoke execute on function serpapi.{qi("replay_" + name)} from public;
"""

    # docs
    lines = [f"## `serpapi.{name}(...)`", "", spec.get("doc", ""), "", "**Arguments**", ""]
    for i, p in enumerate(params):
        req = " (required)" if (i == 0 and p["name"] in spec.get("required", [])) else ""
        d = p.get("doc") or ""
        sd = p.get("default")
        srv = f" default from server option `{sd.split(':',1)[1]}`" if sd and sd.startswith("server:") else ""
        api = f" → `{p['api']}`" if p.get("api") else ""
        lines.append(f"- `{p['name']} {PG[p['type']]}`{req}{api}{srv} {d}".rstrip())
    lines.append(f"- `pages int` default 1 (capped by server `max_pages`); pagination: `{spec['pagination']['kind']}`")
    lines += ["", "**Returns** `setof serpapi." + rt + "`: `search_id`, `page`, " + ", ".join(f"`{c['name']}`" for c in cols) + ", `raw`", ""]
    lines.append(f"Replay: `select * from serpapi.replay_{name}('<search_id>')`")
    lines.append("")
    return "\n".join([type_sql, "", fn_sql, replay_sql]), "\n".join(lines)


def gen_generic() -> str:
    return """-- generic access to any engine: one row per page
create function serpapi.search(engine text, params jsonb default '{}'::jsonb, pages int default 1)
returns table (search_id text, page int, result jsonb)
language plpgsql volatile security definer
set search_path = ''
set statement_timeout = '25s'
set plan_cache_mode = 'force_custom_plan'
as $$
#variable_conflict use_variable
declare
  t0 timestamptz := clock_timestamp();
  n int;
begin
  perform serpapi_private.check_quota(coalesce(pages, 1));
  return query
    select f.search_id, f.page, f.result
    from serpapi_private.search f
    where f.engine = engine
      and f.params = coalesce(params, '{}'::jsonb)
      and f.pages = coalesce(pages, 1);
  get diagnostics n = row_count;
  perform serpapi_private.log_request(engine, coalesce(params, '{}'::jsonb) || jsonb_build_object('pages', pages), n, extract(milliseconds from clock_timestamp() - t0)::int);
end $$;
comment on function serpapi.search is 'Any SerpApi engine. params are passed through as query parameters (api_key/engine/output are ignored).';
revoke execute on function serpapi.search from public;

-- same, but the response rendered as Markdown (fetched free from the archive)
create function serpapi.search_md(engine text, params jsonb default '{}'::jsonb)
returns table (search_id text, markdown text)
language plpgsql volatile security definer
set search_path = ''
set statement_timeout = '25s'
set plan_cache_mode = 'force_custom_plan'
as $$
#variable_conflict use_variable
begin
  perform serpapi_private.check_quota(1);
  return query
    select f.search_id, f.markdown
    from serpapi_private.search f
    where f.engine = engine
      and f.params = coalesce(params, '{}'::jsonb)
      and f.pages = 1;
end $$;
revoke execute on function serpapi.search_md from public;

-- free re-read of any past search, whatever the engine
create function serpapi.replay(search_id text)
returns jsonb
language plpgsql stable security definer
set search_path = ''
set statement_timeout = '25s'
set plan_cache_mode = 'force_custom_plan'
as $$
#variable_conflict use_variable
declare r jsonb;
begin
  select f.result into r from serpapi_private.search f where f.search_id = search_id limit 1;
  return r;
end $$;
revoke execute on function serpapi.replay from public;

create function serpapi.replay_md(search_id text)
returns text
language plpgsql stable security definer
set search_path = ''
set statement_timeout = '25s'
set plan_cache_mode = 'force_custom_plan'
as $$
#variable_conflict use_variable
declare r text;
begin
  select f.markdown into r from serpapi_private.search f where f.search_id = search_id limit 1;
  return r;
end $$;
revoke execute on function serpapi.replay_md from public;

-- live account status (never returns the api key)
create function serpapi.account()
returns table (
  account_email text, plan_name text, searches_per_month int, plan_searches_left int,
  extra_credits int, total_searches_left int, this_month_usage int, this_hour_searches int,
  account_rate_limit_per_hour int
)
language sql volatile security definer
set search_path = ''
set statement_timeout = '15s'
as $$
  select a.account_email, a.plan_name, a.searches_per_month, a.plan_searches_left,
         a.extra_credits, a.total_searches_left, a.this_month_usage, a.this_hour_searches,
         a.account_rate_limit_per_hour
  from serpapi_private.account a;
$$;
revoke execute on function serpapi.account from public;
"""


def main() -> int:
    cat = json.loads(CATALOG.read_text())
    engines = cat["engines"]
    parts = [
        "-- GENERATED by scripts/gen.py from catalog/engines.json. Do not edit by hand.",
        "-- Requires: 00_wrappers.sql (extension + fdw), a foreign server named `serpapi`, and 10_private.sql.",
        "",
        "-- private foreign tables, one per engine plus `search` and `account`",
        "import foreign schema serpapi from server serpapi into serpapi_private;",
        "",
    ]
    docs = ["# Engines", "", "Generated from `catalog/engines.json`. All functions are `security definer`, check the caller's quota, log the request, and never expose the foreign tables.", ""]
    for name, spec in engines.items():
        sql, doc = gen_engine(cat, name, spec)
        parts += [f"-- ===== {name} =====", sql, ""]
        docs.append(doc)
    parts += ["-- ===== generic =====", gen_generic()]
    OUT_SQL.write_text("\n".join(parts))
    OUT_DOC.write_text("\n".join(docs))
    print(f"wrote {OUT_SQL.relative_to(ROOT)} ({len(engines)} engines) and {OUT_DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
