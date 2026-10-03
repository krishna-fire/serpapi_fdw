-- 40_snapshots.sql — Strikethrough: a nightly price ledger keyed by product identity (Amazon ASIN
-- or Google Shopping product_id), built from serpapi.amazon() and serpapi.google_shopping(), plus
-- the forensics view that flags manufactured strikethrough prices.
--
-- Cheap by design: one Amazon search for "iPhone" returns dozens of models and variants with
-- ASIN, price and strikethrough in a single credit; a tracked search costs `pages` credits a night.

-- ---------------------------------------------------------------- what we track (edit freely)

create table if not exists public.tracked_searches (
  id           serial primary key,
  engine       text not null check (engine in ('amazon', 'google_shopping')),
  query        text not null,
  title_filter text not null default '',      -- regex; rows whose title does not match are ignored
  pages        int  not null default 1,
  active       boolean not null default true,
  note         text,
  unique (engine, query)
);

insert into public.tracked_searches (engine, query, title_filter, pages, note) values
  ('amazon',          'iPhone',    '^iPhone',           2, 'every current iPhone model/variant on amazon.in (titles start with "iPhone", not "Apple"); 2 credits/night'),
  ('google_shopping', 'iPhone 16', '^(Apple )?iPhone 16', 1, 'cross-merchant (Flipkart, Croma, Reliance, …) for one flagship; 1 credit/night')
on conflict (engine, query) do nothing;

-- ---------------------------------------------------------------- snapshots

create table if not exists public.price_snapshots (
  id            bigserial primary key,
  captured_on   date not null,
  captured_at   timestamptz not null default now(),
  search_id     int references public.tracked_searches (id),
  engine        text not null,
  product_key   text not null,               -- asin (amazon) or product_id (google shopping)
  title         text,
  source        text,                        -- merchant (Amazon.in for amazon)
  price         numeric,
  old_price     numeric,                     -- the strikethrough / "was" price, if shown
  rating        numeric,
  reviews       int,
  serpapi_search_id text,                    -- free replay for 31 days
  raw           jsonb
);
create index if not exists price_snapshots_key_day_idx on public.price_snapshots (product_key, source, captured_on);
create index if not exists price_snapshots_day_idx on public.price_snapshots (captured_on);

create table if not exists public.snapshot_runs (
  id          bigserial primary key,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  searches    int,
  rows        int,
  errors      int,
  notes       jsonb
);

-- One tracked search per iteration, committed per search so one failure does not lose the night.
-- pg_cron runs as postgres (quota-exempt); the wrapper's account-wide cap still applies.
create or replace procedure serpapi.snapshot_prices(day date default current_date)
language plpgsql
as $$
declare
  t       record;
  run_id  bigint;
  n_rows  int := 0;
  n_err   int := 0;
  n_srch  int := 0;
  errs    jsonb := '[]'::jsonb;
  ins     int;
begin
  insert into public.snapshot_runs (searches) values (0) returning id into run_id;
  commit;

  for t in select * from public.tracked_searches where active order by id loop
    n_srch := n_srch + 1;
    begin
      if t.engine = 'amazon' then
        insert into public.price_snapshots (captured_on, search_id, engine, product_key, title, source, price, old_price, rating, reviews, serpapi_search_id, raw)
        select day, t.id, 'amazon', a.asin, a.title, 'Amazon.in', a.extracted_price, a.extracted_old_price, a.rating, a.reviews, a.search_id, a.raw
        from serpapi.amazon(t.query, pages => t.pages) a
        where a.asin is not null and a.extracted_price is not null
          and not coalesce(a.sponsored, false)
          and (t.title_filter = '' or a.title ~* t.title_filter);
      else
        insert into public.price_snapshots (captured_on, search_id, engine, product_key, title, source, price, old_price, rating, reviews, serpapi_search_id, raw)
        select day, t.id, 'google_shopping', coalesce(s.product_id, s.title), s.title, s.source, s.extracted_price, s.extracted_old_price, s.rating, s.reviews, s.search_id, s.raw
        from serpapi.google_shopping(t.query, pages => t.pages) s
        where s.extracted_price is not null
          and (t.title_filter = '' or s.title ~* t.title_filter);
      end if;
      get diagnostics ins = row_count;
      n_rows := n_rows + ins;
    exception when others then
      n_err := n_err + 1;
      errs := errs || jsonb_build_object('search', t.engine || ':' || t.query, 'error', sqlerrm);
    end;
    commit;
  end loop;

  update public.snapshot_runs
    set finished_at = now(), searches = n_srch, rows = n_rows, errors = n_err, notes = errs
    where id = run_id;
  commit;
end $$;

-- ---------------------------------------------------------------- analysis views

-- Shapes changed across versions; create-or-replace cannot alter a view's columns or a
-- function's return type, so drop first (data lives in the tables, not here).
drop function if exists public.strikethrough_forensics(date, int);
drop view if exists public.price_changes;
drop view if exists public.price_series;

-- Cheapest selling price per product × merchant × day, with the title seen that day.
create or replace view public.price_series as
  select s.engine, s.product_key, s.source, s.captured_on,
         min(s.title)           as title,
         min(s.price)           as price,
         max(s.old_price)       as old_price,
         min(s.serpapi_search_id) as serpapi_search_id
  from public.price_snapshots s
  group by s.engine, s.product_key, s.source, s.captured_on;

-- Day-over-day movement.
create or replace view public.price_changes as
  select *,
         price - lag(price) over w         as price_delta,
         old_price - lag(old_price) over w as old_price_delta
  from public.price_series
  window w as (partition by engine, product_key, source order by captured_on);

-- Strikethrough forensics for a given day: was the "was" price ever a real price in the prior window?
create or replace function public.strikethrough_forensics(day date default current_date, lookback int default 12)
returns table (
  engine text, product_key text, title text, source text,
  sale_price numeric, strikethrough numeric,
  max_seen_prior numeric, median_prior numeric, nights_observed int,
  claimed_saving_pct numeric, real_saving_pct numeric,
  inflated boolean, serpapi_search_id text
)
language sql stable as $$
  with today as (
    select * from public.price_series where captured_on = day
  ),
  prior as (
    select engine, product_key, source,
           max(price)                                            as max_seen_prior,
           (percentile_cont(0.5) within group (order by price))::numeric as median_prior,
           count(distinct captured_on)::int                      as nights_observed
    from public.price_series
    where captured_on < day and captured_on >= day - lookback
    group by engine, product_key, source
  )
  select t.engine, t.product_key, t.title, t.source,
         t.price          as sale_price,
         t.old_price      as strikethrough,
         pr.max_seen_prior,
         pr.median_prior,
         coalesce(pr.nights_observed, 0),
         case when t.old_price > 0 then round(100 * (t.old_price - t.price) / t.old_price, 1) end as claimed_saving_pct,
         case when pr.median_prior > 0 then round(100 * (pr.median_prior - t.price) / pr.median_prior, 1) end as real_saving_pct,
         (t.old_price is not null and pr.max_seen_prior is not null and t.old_price > pr.max_seen_prior) as inflated,
         t.serpapi_search_id
  from today t
  left join prior pr using (engine, product_key, source)
  order by inflated desc nulls last, claimed_saving_pct desc nulls last;
$$;

comment on function public.strikethrough_forensics is
  'For each product × merchant on `day`: sale price, the strikethrough shown, the max and median real price over the prior `lookback` nights, and whether the strikethrough exceeds anything actually observed (inflated).';

-- The nightly procedure is owner/service_role only (procedures default to PUBLIC execute).
revoke execute on procedure serpapi.snapshot_prices(date) from public;
