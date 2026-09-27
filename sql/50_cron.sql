-- 50_cron.sql — schedule the nightly ledger. 21:00 UTC = 02:30 IST.
-- On hosted Supabase enable pg_cron from Integrations first; locally it is available.

create extension if not exists pg_cron;

select cron.unschedule(jobid) from cron.job where jobname = 'serpapi-nightly-prices';
select cron.schedule('serpapi-nightly-prices', '0 21 * * *', $$ call serpapi.snapshot_prices() $$);

-- inspect: select * from cron.job_run_details order by start_time desc limit 10;
