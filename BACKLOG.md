# Unified Backlog (sms)

Last Updated: 2026-05-12 (updated x11)
Owner: HANJ29 + Copilot

## Status Legend
- TODO: not started
- IN_PROGRESS: actively working
- BLOCKED: blocked by dependency/environment
- DONE: completed and validated

## Platform / Pipeline
- TODO: Refactor UAT daily.bat to label-based step execution (remove cmd /c string step calls) to avoid quote-parsing instant-exit failures, aligned with weekly/monthly/quarterly hardening pattern
- TODO: Re-prepare dataset and retrain model
- TODO: Check industry stratified metric outputs
- TODO: Implement express-report-based inference branch
- DONE: Implement quantitative target output (target price / target market cap)
- DONE: Implement market-regime-aware strategy routing
- DONE: Implement FY annual-report supervised labels

## Risk Modeling
- TODO: Define risk labels and thresholds
- TODO: Implement risk training and prediction outputs
- TODO: Add risk explanation and industry percentile outputs
- TODO: Add explicit overvalued/undervalued flag (valuation_gap) and apply post-rule adjustment to risk/action/target bands

## Integration / Productization
- TODO: Design BE event-triggered prediction persistence flow
- TODO: Add industry-weighted valuation to smartinvestor_be (load valuation_method_weights_CN.json, inject method_weights into BE valuation config, and expose weighted valuation alongside existing composite path)
- TODO: Reduce valuation signal cliff effects by adding a soft transition near core-method cutoff, so composite/conservative prices and buy signals do not flip abruptly at the threshold
- IN_PROGRESS: Reduce predictive valuation pick latency (focus on predictive_earnings_enrich stage, cache-hit uplift, and upstream batch timeout/concurrency tuning)
- DONE: Implement as-of report_type fusion (dynamic weights + freshness decay + confidence gates)

## Completed (Reference)
- DONE: Implement quantitative target output (target price / target market cap)
- DONE: Implement market-regime-aware strategy routing
- DONE: Implement FY annual-report supervised labels
- DONE: Full rebuild of financial snapshot table
- DONE: Implement Q1/H1/Q3 split-route training
- DONE: Implement multi-algorithm experiment recording and comparison
- DONE: Evaluate whether to use industry specialist models
- DONE: Confirm training algorithms and parameters
- DONE: Build multi-row feature snapshots by report period

## Operating Notes
- UAT refresh now supports production serving slot in serving.yaml.
- If first symbol is very slow, run a 1-symbol warmup before full refresh.
- Monthly full pipeline currently depends on ETL resample command health.
