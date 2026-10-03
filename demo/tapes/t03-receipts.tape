Output demo/out/tapes/t03-receipts.mp4
Source demo/tapes/_common.tape
Sleep 600ms
Type "select search_id, asin, extracted_price from serpapi.amazon('iPhone') limit 3;"
Sleep 500ms
Enter
Sleep 2500ms
Type "\! clear" Enter
Type "select search_id, asin, extracted_price from serpapi.replay_amazon('6ab918f3d9961244aece3f29') limit 3;"
Sleep 500ms
Enter
Sleep 2500ms
Type `select scope, "window", used, cap from serpapi.budget_status();`
Sleep 400ms
Enter
Sleep 2500ms
Type "\! clear" Enter
Type "select jobname, schedule, command from cron.job;"
Sleep 400ms
Enter
Sleep 2500ms
Type "select started_at::date as night, searches, rows, errors from public.snapshot_runs order by 1;"
Sleep 400ms
Enter
Sleep 2500ms
Type "\! clear" Enter
Type "select captured_on, price, old_price from public.price_series"
Enter
Type "where product_key = 'B0FQFBDQJ1' and source = 'Amazon.in' order by 1;"
Sleep 500ms
Enter
Sleep 3s
