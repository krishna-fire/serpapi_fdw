Output demo/out/tapes/t06-underhood.mp4
Source demo/tapes/_common.tape
Set WaitTimeout 60s
Type "\q" Enter
Type "clear" Enter
Sleep 400ms
Type `ls -la dist/serpapi_fdw.wasm | awk '{print $5" bytes", $9}'`
Sleep 300ms
Enter
Sleep 2s
Type "sed -n '/create server serpapi/,/);/p' sql/05_server.example.sql | head -8"
Sleep 300ms
Enter
Sleep 2500ms
Type "clear" Enter
Type "scripts/smoke-assert.sh"
Sleep 300ms
Enter
Wait+Screen /smoke: errors=/
Sleep 3s
