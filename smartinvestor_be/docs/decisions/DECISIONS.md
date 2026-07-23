# Decisions

## 2026-07-17: Market Index Valuation Quantile Policy

Context:
- Market index valuation endpoint `/api/market-index/valuation-simple/` previously used historical median (P50) for both composite and conservative branches.
- This caused conservative valuation to remain too close to composite in some market regimes.

Decision:
- Use full-history quantiles with split policy:
  - composite branch uses Q60
  - conservative branch uses Q25
- Keep request contract unchanged.
- Return quantile metadata in `summary`:
  - `composite_metric_quantile`
  - `conservative_metric_quantile`

Rationale:
- Q60 provides a moderately optimistic composite anchor without Q75-level aggressiveness.
- Q25 gives a stricter conservative anchor and improves safety-margin discrimination.

Impact:
- `summary.composite_valuation_price` may increase versus M50 baseline.
- `summary.conservative_valuation_price` may decrease versus M50 baseline.
- Gap percentages are expected to widen.
