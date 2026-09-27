-- 05_server.example.sql — create the foreign server. Copy, fill in, run once.
-- The server MUST be named `serpapi` (20_generated.sql imports from it).

-- 1) store the key in Vault (never in SQL history: run this from the dashboard's SQL editor
--    or psql with \set, and clear your history afterwards)
-- select vault.create_secret('<your serpapi api key>', 'serpapi_api_key', 'SerpApi API key for serpapi_fdw');

-- 2a) hosted Supabase / any Postgres with Wrappers >= 0.5: install from a GitHub release
create server serpapi
  foreign data wrapper wasm_wrapper
  options (
    fdw_package_url 'https://github.com/krishna-fire/serpapi_fdw/releases/download/v0.1.0/serpapi_fdw.wasm',
    fdw_package_name 'serpapi:serpapi-fdw',
    fdw_package_version '0.1.0',
    fdw_package_checksum '<sha256 from the release>',
    api_key_name 'serpapi_api_key',
    default_gl 'in',
    default_hl 'en',
    default_location 'Bengaluru,Karnataka,India',
    default_google_domain 'google.co.in',
    default_amazon_domain 'amazon.in',
    hourly_cap '50',
    monthly_cap '250',
    max_pages '3'
  );

-- 2b) local `supabase start`: scripts/load-local.sh copies the built .wasm into the db container
--     and runs the equivalent of:
-- create server serpapi foreign data wrapper wasm_wrapper options (
--   fdw_package_url 'file:///tmp/serpapi_fdw.wasm',      -- no checksum needed for file://
--   fdw_package_name 'serpapi:serpapi-fdw',
--   fdw_package_version '0.1.0',
--   api_key_name 'serpapi_api_key',
--   default_gl 'in', default_location 'Bengaluru,Karnataka,India', default_amazon_domain 'amazon.in'
-- );
