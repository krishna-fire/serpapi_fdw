Output demo/out/tapes/t05-payoff.mp4
Source demo/tapes/_common.tape
Sleep 600ms
Type "select product_key as asin, sale_price as price, strikethrough as was, max_seen_prior as max_prior,"
Enter
Type "       claimed_saving_pct as claimed_pct, real_saving_pct as real_pct, inflated"
Enter
Type "from public.strikethrough_forensics(current_date) where strikethrough is not null"
Enter
Type "order by inflated desc, claimed_pct desc limit 8;"
Sleep 700ms
Enter
Sleep 7s
