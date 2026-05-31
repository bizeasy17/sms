# Valuation Changelog

## 2026-03-25
- Added current market-cap impact in buy-candidate composite layer only.
- Composite now applies a size factor inferred from current market-cap tiers (small/mid/large/mega).
- Conservative valuation and single-method valuations remain unchanged.
- Added `size_factor` in `buy_candidate_reason` for auditability.
- Refactored estmktv CLI (phase-1, behavior-preserving): extracted runtime option normalization, requested scenario-model resolver, and scarcity-profile apply wrapper to reduce branching duplication and improve maintainability.
- Refactored estmktv CLI (phase-2, behavior-preserving): extracted business-match orchestration into `valuation_api/estmktv_business_match_service.py`, leaving command layer as orchestration entrypoint.
- Added phase-3 regression tests for estmktv refactor in `valuation_api/tests_estmktv_command.py` (runtime option normalization, scenario-model priority, business-match delegation).

## 2026-03-23
- Added standalone `sw_history` valuation method alias support in API and prefill (`sw_hist`, `industry_history`).
- Added `history_years`, `history_quantile`, `history_min_samples` request parameters to full valuation endpoint and plumbed them to valuation runtime as `sw_history_kwargs`.
- Added history component rows (`pe`/`pb`/`ps`) with explicit `valuation_variant` signature (`hist_y<years>_q<q>_m<min_samples>`) and `compare_group=sw_history_anchor` in live valuation output.
- Added aggregate `sw_history` valuation row computed from available history components.
- Updated persistence to honor per-row `valuation_variant`/context metadata first, so `pe(default)` and `pe(hist_...)` can coexist in snapshots.
- Updated weighted valuation composition to ignore non-default variants and avoid double-counting history rows.
- Fixed variant normalization: treat missing/NaN `valuation_variant` as `default` in live valuation, API row extraction, and prefill extraction to prevent accidental `nan` variants and default-row filtering regressions.
