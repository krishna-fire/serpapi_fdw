Output demo/out/tapes/t04-bill.mp4
Source demo/tapes/_common.tape
Sleep 600ms
Type `select scope, "window", used, cap, remaining from serpapi.budget_status();`
Sleep 400ms
Enter
Sleep 2500ms
Type "\! clear" Enter
Hide
Type "alter server serpapi options (set hourly_cap '1');" Enter
Sleep 300ms
Type "\! clear" Enter
Show
Type "select count(*) from serpapi.amazon('iPhone 17 Pro');"
Sleep 400ms
Enter
Sleep 3s
Hide
Type "alter server serpapi options (set hourly_cap '50');" Enter
Type "\! clear" Enter
Show
Type `\! demo/rpc.sh anon google_shopping '{"q": "iPhone 16"}'`
Sleep 400ms
Enter
Sleep 2500ms
Type `\! demo/rpc.sh user budget_status`
Sleep 400ms
Enter
Sleep 3s
