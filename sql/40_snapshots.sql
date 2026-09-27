-- 40_snapshots.sql — Strikethrough: a nightly price ledger built from serpapi.google_shopping()
-- and serpapi.amazon(), plus the forensics view that flags manufactured strikethrough prices.

-- ---------------------------------------------------------------- products (edit freely)

create table if not exists public.products (
  id         serial primary key,
  sku        text not null unique,
  query      text not null,            -- what we search for
  category   text,
  active     boolean not null default true,
  created_at timestamptz not null default now()
);

-- Placeholder seed; tune later. Keep ~10 to fit the credit budget (2 searches per product per night).
insert into public.products (sku, query, category) values
  ('iphone-16-128',        'iPhone 16 128GB',                       'phone'),
  ('samsung-43-crystal4k', 'Samsung 43 inch Crystal 4K UHD Smart TV', 'tv'),
  ('boat-airdopes-141',    'boAt Airdopes 141',                     'audio'),
  ('sony-wh1000xm5',       'Sony WH-1000XM5',                       'audio'),
  ('philips-airfryer-41',  'Philips 4.1L Air Fryer HD9200',         'kitchen'),
  ('prestige-iris-750',    'Prestige Iris 750W Mixer Grinder',      'kitchen'),
  ('samsung-253l-fridge',  'Samsung 253L Frost Free Refrigerator',  'appliance'),
  ('lg-7kg-frontload',     'LG 7 kg Front Load Washing Machine',    'appliance'),
  ('oneplus-nord-ce4',     'OnePlus Nord CE4',                      'phone'),
  ('lenovo-ideapad-slim3', 'Lenovo IdeaPad Slim 3 i5',              'laptop')
on conflict (sku) do nothing;

-- ---------------------------------------------------------------- snapshots

create table if not exists public.price_snapshots (
  id            bigserial primary key,
  product_id    int not null references public.products (id),
  captured_on   date not null,
  captured_at   timestamptz not null default now(),
  engine        text not null,              -- google_shopping | amazon
  source        text,                       -- merchant as SerpApi reports it
  title         text,
  price         numeric,                    -- selling price
  old_price     numeric,                    -- the strikethrough / "was" price, if shown
  rating        numeric,
  reviews       int,
  search_id     text,                       -- SerpApi search id: free replay for 31 days
  raw           jsonb
);
create index if not exists price_snapshots_prod_day_idx on public.price_snapshots (product_id, captured_on);
create index if not exists price_snapshots_day_idx on public.price_snapshots (captured_on);

create table if not exists public.snapshot_runs (
  id          bigserial primary key,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  products    int,
  rows        int,
  errors      int,
  notes       jsonb
);

-- One product per iteration, committed per product so one bad engine does not roll back the night.
-- Runs as the caller (pg_cron runs as postgres, which is quota-exempt); the wrapper's account cap still applies.
create or replace procedure serpapi.snapshot_prices(day date default current_date)
language plpgsql
as $$
declare
  p       record;
  run_id  bigint;
  n_rows  int := 0;
  n_err   int := 0;
  n_prod  int := 0;
  errs    jsonb := '[]'::jsonb;
  ins     int;
begin
  insert into public.snapshot_runs (products) values (0) returning id into run_id;
  commit;

  for p in select * from public.products where active order by id loop
    n_prod := n_prod + 1;

    begin
      insert into public.price_snapshots (product_id, captured_on, engine, source, title, price, old_price, rating, reviews, search_id, raw)
      select p.id, day, 'google_shopping', s.source, s.title, s.extracted_price, s.extracted_old_price, s.rating, s.reviews, s.search_id, s.raw
      from serpapi.google_shopping(p.query) s
      where s.extracted_price is not null;
      get diagnostics ins = row_count;
      n_rows := n_rows + ins;
    exception when others then
      n_err := n_err + 1;
      errs := errs || jsonb_build_object('product', p.sku, 'engine', 'google_shopping', 'error', sqlerrm);
    end;
    commit;

    begin
      insert into public.price_snapshots (product_id, captured_on, engine, source, title, price, old_price, rating, reviews, search_id, raw)
      select p.id, day, 'amazon', 'Amazon.in', a.title, a.extracted_price, a.extracted_old_price, a.rating, a.reviews, a.search_id, a.raw
      from serpapi.amazon(p.query) a
      where a.extracted_price is not null and not coalesce(a.sponsored, false)
      limit 5;   -- top organic matches only
      get diagnostics ins = row_count;
      n_rows := n_rows + ins;
    exception when others then
      n_err := n_err + 1;
      errs := errs || jsonb_build_object('product', p.sku, 'engine', 'amazon', 'error', sqlerrm);
    end;
    commit;
  end loop;

  update public.snapshot_runs
    set finished_at = now(), products = n_prod, rows = n_rows, errors = n_err, notes = errs
    where id = run_id;
  commit;
end $$;

-- ---------------------------------------------------------------- analysis views

-- Cheapest selling price per product × engine × source × day.
create or replace view public.price_series as
  select s.product_id, p.sku, s.captured_on, s.engine, s.source,
         min(s.price)      as price,
         max(s.old_price)  as old_price,
         min(s.search_id)  as search_id
  from public.price_snapshots s
  join public.products p on p.id = s.product_id
  group by s.product_id, p.sku, s.captured_on, s.engine, s.source;

-- Day-over-day movement.
create or replace view public.price_changes as
  select *,
         price - lag(price) over w      as price_delta,
         old_price - lag(old_price) over w as old_price_delta
  from public.price_series
  window w as (partition by product_id, engine, source order by captured_on);

-- Strikethrough forensics for a given day: was the "was" price ever a real price in the prior window?
create or replace function public.strikethrough_forensics(day date default current_date, lookback int default 12)
returns table (
  sku text, engine text, source text,
  sale_price numeric, strikethrough numeric,
  max_seen_prior numeric, median_prior numeric, nights_observed int,
  claimed_saving_pct numeric, real_saving_pct numeric,
  inflated boolean, search_id text
)
language sql stable as $$
  with today as (
    select * from public.price_series where captured_on = day
  ),
  prior as (
    select product_id, engine, source,
           max(price)                                   as max_seen_prior,
           (percentile_cont(0.5) within group (order by price))::numeric as median_prior,
           count(distinct captured_on)::int             as nights_observed
    from public.price_series
    where captured_on < day and captured_on >= day - lookback
    group by product_id, engine, source
  )
  select t.sku, t.engine, t.source,
         t.price          as sale_price,
         t.old_price      as strikethrough,
         pr.max_seen_prior,
         pr.median_prior,
         coalesce(pr.nights_observed, 0),
         case when t.old_price > 0 then round(100 * (t.old_price - t.price) / t.old_price, 1) end as claimed_saving_pct,
         case when pr.median_prior > 0 then round(100 * (pr.median_prior - t.price) / pr.median_prior, 1) end as real_saving_pct,
         (t.old_price is not null and pr.max_seen_prior is not null and t.old_price > pr.max_seen_prior) as inflated,
         t.search_id
  from today t
  left join prior pr using (product_id, engine, source)
  order by inflated desc nulls last, claimed_saving_pct desc nulls last;
$$;

comment on function public.strikethrough_forensics is
  'For each product × seller on `day`: sale price, the strikethrough shown, the max and median real price over the prior `lookback` nights, and whether the strikethrough exceeds anything actually observed (inflated).';
