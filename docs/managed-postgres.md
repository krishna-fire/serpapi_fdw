# From RDS or any managed Postgres: a sidecar

RDS for PostgreSQL and Aurora can be given outbound network access (a security-group egress rule, NAT gateway or VPC endpoint, as their `aws_lambda` setup describes), but their supported-extension lists contain nothing that issues HTTP from SQL: no `http`, `pg_net`, `wrappers`, or untrusted procedural languages, and `pg_tle` allows only trusted ones ([RDS list](https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html), [Aurora list](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraPostgreSQLReleaseNotes/AuroraPostgreSQL.Extensions.html)). So the wrapper cannot be installed there.

Two routes remain. The AWS-native one is `aws_lambda.invoke` (synchronous, returns the Lambda's JSON) with a Lambda that calls SerpApi; that is a separate integration and out of scope here. The one that reuses this project unchanged: RDS ships `postgres_fdw` and `dblink`, so run `serpapi_fdw` in a sidecar (a free Supabase project or a small container) and let the managed database query it. Joins, snapshots and quotas stay next to your data; only the search hop leaves.

```sql
-- on RDS
create extension postgres_fdw;
create server serpapi_sidecar foreign data wrapper postgres_fdw
  options (host 'sidecar.example.com', port '5432', dbname 'postgres');
create user mapping for current_user server serpapi_sidecar options (user 'app', password '…');

-- table style: quals are pushed to the sidecar, whose wrapper runs exactly one search
import foreign schema serpapi_private limit to (google_shopping) from server serpapi_sidecar into sidecar;
select source, extracted_price from sidecar.google_shopping
where q = 'boAt Airdopes 141' and gl = '' and hl = '' and location = '' and google_domain = ''
  and min_price = -1 and max_price = -1 and sort_by = '' and on_sale = false and num = -1 and pages = 1;

-- function style: named arguments, quota and log on the sidecar
select * from dblink('serpapi_sidecar', $$ select source, extracted_price from serpapi.google_shopping('boAt Airdopes 141') $$)
  as t(source text, extracted_price numeric);
```

Verified against a contrib-only Postgres federating to the local Supabase stack: rows come back, `EXPLAIN VERBOSE` shows `q = …` in the remote SQL, and the sidecar's guards surface as errors on the RDS side.
