-- 10_private.sql — schemas, caller identity, per-caller quota, request log.
-- Everything here is private plumbing used by the generated functions in 20_generated.sql.

create schema if not exists serpapi;
create schema if not exists serpapi_private;

revoke all on schema serpapi_private from public;
revoke all on schema serpapi from public;

-- ---------------------------------------------------------------- settings

create table if not exists serpapi_private.settings (
  key   text primary key,
  value text not null,
  doc   text
);

insert into serpapi_private.settings (key, value, doc) values
  ('daily_quota_per_caller', '20',  'Searches per calendar day (UTC) per authenticated user or per anonymous role'),
  ('allow_anon',             'off', 'Whether the anon role may call search functions at all'),
  ('quota_exempt',           'role:postgres,role:service_role,role:supabase_admin', 'Callers that bypass the per-caller quota (the account-wide cap in the wrapper still applies)')
on conflict (key) do nothing;

create or replace function serpapi_private.setting(k text, fallback text default null)
returns text language sql stable set search_path = '' as $$
  select coalesce((select s.value from serpapi_private.settings s where s.key = k), fallback);
$$;

-- ---------------------------------------------------------------- who is calling

-- 'user:<auth.uid()>' on Supabase with a JWT, 'role:<jwt role>' for anon/service calls,
-- 'role:<session_user>' for direct connections (psql, SQL editor, pg_cron).
create or replace function serpapi_private.caller()
returns text language plpgsql stable set search_path = '' as $$
declare
  uid  text;
  role text;
begin
  if to_regprocedure('auth.uid()') is not null then
    execute 'select auth.uid()::text' into uid;
  end if;
  if uid is not null then
    return 'user:' || uid;
  end if;
  if to_regprocedure('auth.role()') is not null then
    execute 'select auth.role()' into role;
  end if;
  return 'role:' || coalesce(role, session_user);
end $$;

-- ---------------------------------------------------------------- per-caller quota

create table if not exists serpapi_private.user_quota (
  caller text not null,
  day    date not null,
  used   int  not null default 0,
  primary key (caller, day)
);

-- Raises if the caller would exceed today's quota; otherwise records n searches.
-- The wrapper enforces the account-wide hourly/monthly caps independently.
create or replace function serpapi_private.check_quota(n int)
returns void language plpgsql volatile set search_path = '' as $$
declare
  c      text := serpapi_private.caller();
  quota  int  := serpapi_private.setting('daily_quota_per_caller', '20')::int;
  exempt text[] := string_to_array(serpapi_private.setting('quota_exempt', ''), ',');
  cur    int;
begin
  if c = any (exempt) then
    return;
  end if;
  if c = 'role:anon' and serpapi_private.setting('allow_anon', 'off') <> 'on' then
    raise exception 'serpapi: anonymous callers are not allowed (set serpapi_private.settings allow_anon = on to permit)'
      using errcode = '42501';
  end if;
  insert into serpapi_private.user_quota (caller, day, used)
    values (c, (now() at time zone 'utc')::date, 0)
    on conflict do nothing;
  select used into cur
    from serpapi_private.user_quota
    where caller = c and day = (now() at time zone 'utc')::date
    for update;
  if cur + n > quota then
    raise exception 'serpapi: daily quota exceeded for this caller (%/% searches today)', cur, quota
      using errcode = '53400', hint = 'Use serpapi.replay_*(search_id) for free re-reads, or raise daily_quota_per_caller.';
  end if;
  update serpapi_private.user_quota
    set used = used + n
    where caller = c and day = (now() at time zone 'utc')::date;
end $$;

-- ---------------------------------------------------------------- request log

create table if not exists serpapi_private.request_log (
  id         bigserial primary key,
  at         timestamptz not null default now(),
  caller     text not null,
  engine     text not null,
  params     jsonb,
  rows       int,
  elapsed_ms int
);
create index if not exists request_log_at_idx on serpapi_private.request_log (at desc);

create or replace function serpapi_private.log_request(engine text, params jsonb, rows int, elapsed_ms int)
returns void language sql volatile set search_path = '' as $$
  insert into serpapi_private.request_log (caller, engine, params, rows, elapsed_ms)
  values (serpapi_private.caller(), engine, params, rows, elapsed_ms);
$$;

-- ---------------------------------------------------------------- wrapper metadata access

-- The Wasm host persists the wrapper's budget counters in wrappers_fdw_stats.metadata.
-- The table lives in whichever schema the `wrappers` extension was installed into.
create or replace function serpapi_private.fdw_metadata()
returns jsonb language plpgsql stable set search_path = '' as $$
declare
  rel regclass := coalesce(to_regclass('extensions.wrappers_fdw_stats'), to_regclass('public.wrappers_fdw_stats'));
  md  jsonb;
begin
  if rel is null then
    return null;
  end if;
  execute format('select metadata from %s where fdw_name = %L', rel, 'serpapi_fdw') into md;
  return md;
end $$;

-- Server options of the `serpapi` foreign server as a jsonb object.
create or replace function serpapi_private.server_options()
returns jsonb language sql stable set search_path = '' as $$
  select coalesce(jsonb_object_agg(o.option_name, o.option_value), '{}'::jsonb)
  from pg_foreign_server s
  cross join lateral pg_options_to_table(s.srvoptions) o
  where s.srvname = 'serpapi'
    and o.option_name not in ('api_key');
$$;
