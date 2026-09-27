# Engines

Generated from `catalog/engines.json`. All functions are `security definer`, check the caller's quota, log the request, and never expose the foreign tables.

## `serpapi.google(...)`

Google Search organic results

**Arguments**

- `q text` (required)
- `gl text` default from server option `default_gl` Country code, e.g. in
- `hl text` default from server option `default_hl` Language code, e.g. en, hi, ta
- `location text` default from server option `default_location`
- `google_domain text` default from server option `default_google_domain`
- `num int`
- `tbs text` Time filter, e.g. qdr:w
- `safe text`
- `pages int` default 1 (capped by server `max_pages`); pagination: `start`

**Returns** `setof serpapi.google_result`: `search_id`, `page`, `position`, `title`, `link`, `displayed_link`, `snippet`, `date`, `source`, `favicon`, `thumbnail`, `raw`

Replay: `select * from serpapi.replay_google('<search_id>')`

## `serpapi.google_light(...)`

Google Light Search organic results (faster, fewer blocks). Note: `location` is temporarily unsupported by SerpApi on this engine (Sep 2026).

**Arguments**

- `q text` (required)
- `gl text` default from server option `default_gl` Country code, e.g. in
- `hl text` default from server option `default_hl` Language code, e.g. en, hi, ta
- `google_domain text` default from server option `default_google_domain`
- `num int`
- `pages int` default 1 (capped by server `max_pages`); pagination: `start`

**Returns** `setof serpapi.google_light_result`: `search_id`, `page`, `position`, `title`, `link`, `displayed_link`, `snippet`, `date`, `source`, `raw`

Replay: `select * from serpapi.replay_google_light('<search_id>')`

## `serpapi.google_shopping(...)`

Google Shopping results. SerpApi ignores `start` on this engine (~40 results per request), so pagination is none.

**Arguments**

- `q text` (required)
- `gl text` default from server option `default_gl` Country code, e.g. in
- `hl text` default from server option `default_hl` Language code, e.g. en, hi, ta
- `location text` default from server option `default_location`
- `google_domain text` default from server option `default_google_domain`
- `min_price numeric`
- `max_price numeric`
- `sort_by text` e.g. 1 (price low-high), 2 (price high-low), 3 (rating)
- `on_sale boolean`
- `num int`
- `pages int` default 1 (capped by server `max_pages`); pagination: `none`

**Returns** `setof serpapi.google_shopping_result`: `search_id`, `page`, `position`, `title`, `source`, `price`, `extracted_price`, `old_price`, `extracted_old_price`, `rating`, `reviews`, `delivery`, `tag`, `product_id`, `product_link`, `immersive_product_page_token`, `thumbnail`, `extensions`, `raw`

Replay: `select * from serpapi.replay_google_shopping('<search_id>')`

## `serpapi.amazon(...)`

Amazon Search results. Query parameter is `k`; `amazon_domain` selects the marketplace (amazon.in for India).

**Arguments**

- `q text` (required) → `k`
- `gl text` default from server option `default_gl` Country code, e.g. in
- `hl text` default from server option `default_hl` Language code, e.g. en, hi, ta
- `amazon_domain text` default from server option `default_amazon_domain`
- `language text` e.g. en_IN, hi_IN
- `delivery_zip text` PIN code
- `s text` Sort, e.g. price-asc-rank
- `pages int` default 1 (capped by server `max_pages`); pagination: `page`

**Returns** `setof serpapi.amazon_result`: `search_id`, `page`, `position`, `asin`, `title`, `link`, `price`, `extracted_price`, `old_price`, `extracted_old_price`, `rating`, `reviews`, `bought_last_month`, `sponsored`, `prime`, `thumbnail`, `delivery`, `variants`, `raw`

Replay: `select * from serpapi.replay_amazon('<search_id>')`

## `serpapi.google_jobs(...)`

Google Jobs results. 10 per page, token pagination. SerpApi reports intermittent empties on this engine (Sep 2026); the wrapper surfaces those as zero rows plus a notice.

**Arguments**

- `q text` (required)
- `gl text` default from server option `default_gl` Country code, e.g. in
- `hl text` default from server option `default_hl` Language code, e.g. en, hi, ta
- `location text` default from server option `default_location`
- `google_domain text` default from server option `default_google_domain`
- `lrad int` Search radius in km
- `uds text` Filter string harvested from filters[]
- `pages int` default 1 (capped by server `max_pages`); pagination: `next_page_token`

**Returns** `setof serpapi.google_jobs_result`: `search_id`, `page`, `title`, `company_name`, `job_location`, `via`, `posted_at`, `schedule_type`, `salary`, `work_from_home`, `description`, `share_link`, `job_id`, `apply_options`, `job_highlights`, `thumbnail`, `raw`

Replay: `select * from serpapi.replay_google_jobs('<search_id>')`

## `serpapi.google_maps(...)`

Google Maps local results (type=search). 20 per page via `start`. Prefer `ll` ('@lat,lng,14z') for precise geo; `location` also works.

**Arguments**

- `q text` (required)
- `gl text` default from server option `default_gl` Country code, e.g. in
- `hl text` default from server option `default_hl` Language code, e.g. en, hi, ta
- `ll text` @lat,lng,zoom e.g. @12.9716,77.5946,14z
- `location text` default from server option `default_location`
- `google_domain text` default from server option `default_google_domain`
- `min_rating numeric`
- `open_state text` now | 24h
- `pages int` default 1 (capped by server `max_pages`); pagination: `start`

**Returns** `setof serpapi.google_maps_result`: `search_id`, `page`, `position`, `title`, `place_id`, `data_id`, `data_cid`, `latitude`, `longitude`, `rating`, `reviews`, `price`, `type`, `types`, `address`, `open_now`, `phone`, `website`, `description`, `service_options`, `thumbnail`, `raw`

Replay: `select * from serpapi.replay_google_maps('<search_id>')`

## `serpapi.google_maps_reviews(...)`

Reviews for one place. Requires `data_id` (from google_maps) or `place_id`. First page is 8 reviews, then up to 20 per page via token.

**Arguments**

- `data_id text`
- `gl text` default from server option `default_gl` Country code, e.g. in
- `hl text` default from server option `default_hl` Language code, e.g. en, hi, ta
- `place_id text`
- `sort_by text` qualityScore | newestFirst | ratingHigh | ratingLow
- `topic_id text`
- `num int`
- `pages int` default 1 (capped by server `max_pages`); pagination: `next_page_token`

**Returns** `setof serpapi.google_maps_reviews_result`: `search_id`, `page`, `review_id`, `rating`, `date`, `iso_date`, `snippet`, `original_snippet`, `translated_snippet`, `likes`, `user_name`, `contributor_id`, `local_guide`, `user_reviews`, `user_photos`, `response`, `raw`

Replay: `select * from serpapi.replay_google_maps_reviews('<search_id>')`

## `serpapi.google_news(...)`

Google News results. No pagination. Regional editions exist for hi/ta/te/ml/bn/mr; `hl=kn` falls back to Hindi.

**Arguments**

- `q text`
- `gl text` default from server option `default_gl` Country code, e.g. in
- `hl text` default from server option `default_hl` Language code, e.g. en, hi, ta
- `topic_token text`
- `story_token text`
- `publication_token text`
- `so int` 1 = sort by date (inside a story/section)
- `pages int` default 1 (capped by server `max_pages`); pagination: `none`

**Returns** `setof serpapi.google_news_result`: `search_id`, `page`, `position`, `title`, `link`, `source_name`, `source_icon`, `authors`, `date`, `iso_date`, `snippet`, `thumbnail`, `stories`, `raw`

Replay: `select * from serpapi.replay_google_news('<search_id>')`
