# Valuation Changelog

## 2026-03-23
- Added standalone `sw_history` valuation method alias support in API and prefill (`sw_hist`, `industry_history`).
- Added `history_years`, `history_quantile`, `history_min_samples` request parameters to full valuation endpoint and plumbed them to valuation runtime as `sw_history_kwargs`.
- Added history component rows (`pe`/`pb`/`ps`) with explicit `valuation_variant` signature (`hist_y<years>_q<q>_m<min_samples>`) and `compare_group=sw_history_anchor` in live valuation output.
- Added aggregate `sw_history` valuation row computed from available history components.
- Updated persistence to honor per-row `valuation_variant`/context metadata first, so `pe(default)` and `pe(hist_...)` can coexist in snapshots.
- Updated weighted valuation composition to ignore non-default variants and avoid double-counting history rows.
- Fixed variant normalization: treat missing/NaN `valuation_variant` as `default` in live valuation, API row extraction, and prefill extraction to prevent accidental `nan` variants and default-row filtering regressions.
