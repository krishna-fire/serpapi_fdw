Output demo/out/tapes/t02-table.mp4
Source demo/tapes/_common.tape
Sleep 600ms
Type "select asin, extracted_price as price, extracted_old_price as was"
Enter
Type "from serpapi.amazon('iPhone', pages => 2) where extracted_old_price is not null;"
Sleep 600ms
Enter
Sleep 2500ms
Type "\! clear" Enter
Type "select p.query, s.asin, s.extracted_price as price"
Enter
Type "from (values ('iPhone')) p(query), lateral serpapi.amazon(p.query) s limit 5;"
Sleep 600ms
Enter
Sleep 2500ms
Type "\! clear" Enter
Type "select search_id, result -> 'interest_over_time' -> 'averages' as averages"
Enter
Type `from serpapi.search('google_trends', '{"q": "air fryer", "geo": "IN-KA"}');`
Sleep 600ms
Enter
Sleep 3s
