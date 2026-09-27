-- scripts/smoke.sql — end-to-end checks against a loaded server (mock or live).
--   psql "$DB_URL" -v ON_ERROR_STOP=0 -f scripts/smoke.sql
\set QUIET 1
\pset footer off
\timing off

\echo '== 1. wrappers version (need >= 0.5.0 for import foreign schema, >= 0.6.1 for LATERAL rescans)'
select name, version, installed from pg_available_extension_versions where name = 'wrappers' and installed;

\echo '== 2. server options (api_key never appears; key is in Vault)'
select serpapi_private.server_options() - 'fdw_package_url' - 'fdw_package_checksum';

\echo '== 3. private foreign tables imported'
select foreign_table_name from information_schema.foreign_tables where foreign_table_schema = 'serpapi_private' order by 1;

\echo '== 4. typed function: google_shopping'
select search_id, page, position, source, extracted_price, old_price
from serpapi.google_shopping('boAt Airdopes 141') limit 5;

\echo '== 5. echo-back: all rows survive the local recheck (count must equal the rows in 4.)'
select count(*) from serpapi.google_shopping('boAt Airdopes 141');

\echo '== 6. LATERAL: exactly one search per outer row'
select v.q, s.source, s.extracted_price
from (values ('boAt Airdopes 141'), ('boAt Airdopes 141 ')) v(q),
     lateral serpapi.google_shopping(v.q) s
order by 1, 2;

\echo '== 7. amazon (k param, amazon.in default)'
select asin, extracted_price, extracted_old_price, sponsored, bought_last_month from serpapi.amazon('boAt Airdopes 141') limit 3;

\echo '== 8. jobs with nested paths + token pagination request (pages=2 asks for a second page)'
select company_name, job_location, salary, via, page from serpapi.google_jobs('data engineer', pages => 2);

\echo '== 9. generic engine'
select search_id, page, jsonb_typeof(result) from serpapi.search('google_trends', '{"q":"air fryer","geo":"IN-KA"}');

\echo '== 10. replay by search_id (free)'
select source, extracted_price from serpapi.replay_google_shopping('fixture-shopping-boat-airdopes-141');

\echo '== 11. account (api_key column must not exist)'
select * from serpapi.account();

\echo '== 12. budget + log'
select * from serpapi.budget_status();
select at, caller, engine, params, rows, elapsed_ms from serpapi.request_log limit 5;

\echo '== 13. guards: missing q'
select * from serpapi.google_shopping(null);

\echo '== 14. guards: pages over max_pages'
select * from serpapi.google_jobs('x', pages => 99);

\echo '== 15. guards: bad operator straight on the private table (only owner can do this)'
select count(*) from serpapi_private.google_shopping where q like '%boAt%';

\echo '== 16. repeated calls keep working after PL/pgSQL would switch to a generic plan (8 calls)'
select count(*) from serpapi.google_shopping('boAt Airdopes 141');
select count(*) from serpapi.google_shopping('boAt Airdopes 141');
select count(*) from serpapi.google_shopping('boAt Airdopes 141');
select count(*) from serpapi.google_shopping('boAt Airdopes 141');
select count(*) from serpapi.google_shopping('boAt Airdopes 141');
select count(*) from serpapi.google_shopping('boAt Airdopes 141');

\echo '== 17. hourly cap fails closed (temporarily set to 1, then restore)'
alter server serpapi options (set hourly_cap '1');
select count(*) from serpapi.google_shopping('boAt Airdopes 141');
select count(*) from serpapi.google_shopping('boAt Airdopes 141 cap');
alter server serpapi options (set hourly_cap '50');

\echo '== done'
