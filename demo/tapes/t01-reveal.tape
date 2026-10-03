Output demo/out/tapes/t01-reveal.mp4
Source demo/tapes/_common.tape
Sleep 800ms
Type "select asin, extracted_price as price, extracted_old_price as was, left(title, 58) as title"
Enter
Type "from serpapi.amazon('iPhone') order by price limit 9;"
Sleep 700ms
Enter
Sleep 6s
