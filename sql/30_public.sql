-- 30_public.sql — public status functions, the request-log view, and grants.

-- ---------------------------------------------------------------- budget_status()

-- scope        window  used  cap  remaining  resets_at
-- account      hour    37    50   13         2026-09-27 09:00:00+00
-- account      month   188   250  62         2026-10-01 00:00:00+00
-- user:<uuid>  day     4     20   16         2026-09-28 00:00:00+00
create or replace function serpapi.budget_status()
returns table (scope text, "window" text, used int, cap int, remaining int, resets_at timestamptz)
language plpgsql stable security definer
set search_path = ''
as $$
declare
  md    jsonb := serpapi_private.fdw_metadata();
  opts  jsonb := serpapi_private.server_options();
  hcap  int   := coalesce((opts ->> 'hourly_cap')::int, 50);
  mcap  int   := coalesce((opts ->> 'monthly_cap')::int, 250);
  hkey  text  := to_char(now() at time zone 'utc', 'YYYYMMDDHH24');
  mkey  text  := to_char(now() at time zone 'utc', 'YYYYMM');
  hused int   := case when md ->> 'hour_key'  = hkey then coalesce((md ->> 'hour_used')::int, 0)  else 0 end;
  mused int   := case when md ->> 'month_key' = mkey then coalesce((md ->> 'month_used')::int, 0) else 0 end;
  c     text  := serpapi_private.caller();
  quota int   := serpapi_private.setting('daily_quota_per_caller', '20')::int;
  dused int;
begin
  scope := 'account'; "window" := 'hour';  used := hused; cap := hcap; remaining := greatest(hcap - hused, 0);
  resets_at := date_trunc('hour', now() at time zone 'utc') + interval '1 hour';
  return next;

  scope := 'account'; "window" := 'month'; used := mused; cap := mcap; remaining := greatest(mcap - mused, 0);
  resets_at := date_trunc('month', now() at time zone 'utc') + interval '1 month';
  return next;

  select q.used into dused
    from serpapi_private.user_quota q
    where q.caller = c and q.day = (now() at time zone 'utc')::date;
  scope := c; "window" := 'day'; used := coalesce(dused, 0); cap := quota; remaining := greatest(quota - coalesce(dused, 0), 0);
  resets_at := date_trunc('day', now() at time zone 'utc') + interval '1 day';
  return next;
end $$;
comment on function serpapi.budget_status() is 'Account-wide caps (from the wrapper''s metadata) and the caller''s daily quota. Costs nothing.';

-- ---------------------------------------------------------------- admin: reset the wrapper's counters

-- Clears the account-wide hourly/monthly counters kept by the wrapper (e.g. after switching
-- servers, or when developing against the mock). Owner-only: not granted to anyone.
create or replace function serpapi.reset_budget()
returns void language plpgsql volatile security definer set search_path = '' as $$
declare
  rel regclass := coalesce(to_regclass('extensions.wrappers_fdw_stats'), to_regclass('public.wrappers_fdw_stats'));
begin
  if rel is not null then
    execute format('update %s set metadata = null where fdw_name = %L', rel, 'serpapi_fdw');
  end if;
  delete from serpapi_private.user_quota where day = (now() at time zone 'utc')::date;
end $$;
revoke execute on function serpapi.reset_budget() from public;

-- ---------------------------------------------------------------- request log view

-- Callers see their own rows; exempt callers (postgres, service_role) see everything.
create or replace view serpapi.request_log
with (security_invoker = false) as
  select l.at, l.caller, l.engine, l.params, l.rows, l.elapsed_ms
  from serpapi_private.request_log l
  where l.caller = serpapi_private.caller()
     or serpapi_private.caller() = any (string_to_array(serpapi_private.setting('quota_exempt', ''), ','))
  order by l.at desc;

-- ---------------------------------------------------------------- grants

-- Nothing in serpapi is callable by default (20_generated.sql revokes execute from public).
-- Grant what your app needs. Typical Supabase setup:
-- Supabase roles, applied only where they exist (plain Postgres has none of them).
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    grant usage on schema serpapi to authenticated;
    grant execute on function serpapi.budget_status() to authenticated;
    grant select on serpapi.request_log to authenticated;
  end if;
  if exists (select 1 from pg_roles where rolname = 'anon') then
    grant usage on schema serpapi to anon;
    grant execute on function serpapi.budget_status() to anon;
  end if;
  -- service_role is the server-side admin key on Supabase: it may call everything (and is quota-exempt).
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    grant usage on schema serpapi to service_role;
    grant execute on all functions in schema serpapi to service_role;
    grant select on serpapi.request_log to service_role;
  end if;
end $$;
-- Example: let logged-in users run Shopping searches (quota-limited by 10_private.sql):
-- grant execute on function serpapi.google_shopping(text, text, text, text, text, numeric, numeric, text, boolean, int, int) to authenticated;
