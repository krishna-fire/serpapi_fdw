-- 00_wrappers.sql — one-time per database: enable Supabase Wrappers and the Wasm FDW handler.
-- Works on Supabase (extension preinstalled) and on plain Postgres with the `wrappers` .deb from
-- https://github.com/supabase/wrappers/releases installed. Safe to re-run.

-- Supabase keeps extensions in `extensions`; on plain Postgres create it so both look alike.
create schema if not exists extensions;
create extension if not exists wrappers with schema extensions;

do $$
begin
  if not exists (select 1 from pg_foreign_data_wrapper where fdwname = 'wasm_wrapper') then
    -- schema-qualified: `extensions` is on the search_path on Supabase, not on plain Postgres
    create foreign data wrapper wasm_wrapper
      handler extensions.wasm_fdw_handler
      validator extensions.wasm_fdw_validator;
  end if;
end $$;

-- Vault is preinstalled on Supabase; on plain Postgres this is a no-op and the server uses a
-- plain `api_key` option guarded by the serpapi.allow_plain_key setting (see 05_server.example.sql).
do $$
begin
  if exists (select 1 from pg_available_extensions where name = 'supabase_vault') then
    create extension if not exists supabase_vault;
  end if;
end $$;
