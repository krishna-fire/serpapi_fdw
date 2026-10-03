Output demo/out/tapes/t09-plainpg.mp4
Source demo/tapes/_common.tape
# plain Postgres 17 container (scripts/plain-pg-up.sh), no Supabase: DB_URL points at it, e.g.
#   DB_URL=postgresql://postgres:postgres@host.docker.internal:55432/postgres python3 demo/build.py --only t09-plainpg
Hide
Type "\set PROMPT1 '%[%033[38;5;110m%]postgres@plain-pg17=#%[%033[0m%] '" Enter
Type "\! clear" Enter
Sleep 300ms
Show
Sleep 300ms
Type@20ms "select split_part(version(), ' on ', 1) as server;"
Sleep 200ms
Enter
Sleep 700ms
Type@20ms "select title, source, extracted_price from serpapi.google_shopping('iPhone 16') limit 5;"
Sleep 300ms
Enter
Sleep 2000ms
