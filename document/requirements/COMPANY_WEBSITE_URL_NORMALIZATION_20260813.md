# Company Website URL Normalization

## Scope

UAT `smartinvestor_be` keeps `CorporationBasic.website` unchanged and returns a
derived `basic_info.website_url`. UAT `smartinvestor_fe` homepage links prefer
the derived value.

## Contract

- Database: `CorporationBasic.website` remains the raw website value.
- Response: `basic_info.website_url` is an optional normalized URL.
- Existing `http://` and `https://` values are preserved.
- Scheme-less values receive `https://` without per-row external probing.

## Performance

Watchlist API responses do not perform outbound website checks. Reachability
scanning remains a separate batch concern.