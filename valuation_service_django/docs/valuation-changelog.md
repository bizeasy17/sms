# Valuation Changelog

## 2026-03-26
- Aligned standalone `estmktv` behavior to UAT baseline for single-stock CLI comparisons.
- Plumbed `sw_history_kwargs` from resolved valuation config into `test_valuation_local`, fixing missing SW-history runtime context in standalone command execution.
- Updated standalone `live_valuation` SW-history aggregation to prefer explicit `assumption_metrics.history_anchors` before fallback component reuse, matching UAT historical-anchor behavior more closely.
- Updated standalone scarcity overlay base-row selection to follow UAT preference order (`sw_history` -> `ps` -> `pb` -> `pe`) without filtering out non-default history variants.
- Switched standalone single-stock `estmktv` output from line-by-line method prints to the same table-style formatter used by UAT CLI output.
- Spot-check after alignment showed `688818.SH` converged from materially different `sw_history`/`scarcity_overlay` outputs to near-equal values versus UAT (remaining difference only at small floating-point precision level).
- Synced standalone `static/valuation_config/valuation_defaults_CN_sw.json` with UAT baseline to eliminate cross-project SW default parameter drift (notably `peg_target` on several L3 industry codes).
- Added local express fallback merge for missing growth fields: when local `StockExpressVip` row is present but growth fields are unusable, standalone now backfills missing fields from Tushare `express_vip` row before applying express adjustments.
- Aligned standalone PEG floor logic with UAT by setting `PEG_MIN_GROWTH_PCT=5.0` in `live_valuation`, fixing residual low-growth bank-stock PEG divergence (e.g., `601398.SH`).
- OpenClaw chat endpoint now supports stock-name fuzzy resolution for short aliases and noisy natural-language inputs (e.g., `招行`, `给我招行的估值`) with deterministic fallback ranking.
- Added ambiguity handling in OpenClaw chat responses: when no unique symbol is found, API returns structured `need_clarification` and `symbol_resolution.candidates` for frontend confirmation.
- Added dominant-candidate auto-resolve rule for short aliases, allowing direct valuation response when top match confidence is sufficiently higher than runner-up.
- Fixed OpenClaw JSON rendering stability by normalizing non-finite float values (`NaN`/`Inf`) to `null` before serialization.
- OpenClaw response payload now includes Chinese stock names via `resolved_stock_name` and `valuation.stock_name`; advice text `标的` line now renders as `中文名 (ts_code)`.
- Added script `scripts/run_alias_regression.ps1` for one-click alias regression checks, with optional UTF-8 answer file output (`-ShowAnswer`, `-OutputFile`).

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
