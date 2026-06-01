# Earnings Forecast Training Dataset, Labels, and Versioning

## 1. Purpose

This document explains the current dev training pipeline for earnings forecast:

- where the dataset comes from
- how features are assembled
- how labels are generated
- how train/test splits are done
- how per-report-type models are trained
- how artifacts are versioned

Unless otherwise stated, this describes the current behavior in:

- configs/default.yaml
- earnings_forecast/services/pipeline.py
- earnings_forecast/management/commands/train_report_type_models.py

## 2. End-to-End Flow

Current training flow is:

1. Load local market mirror tables from earnings DB.
2. Load local financial feature panel or raw financial endpoint tables.
3. Build per-symbol, per-trade_date feature rows.
4. Add supervised target columns onto the same dataset rows.
5. Write dataset.parquet and optional report_type shard datasets.
6. Train one global model bundle for each requested report_type.
7. Optionally train industry specialist models inside each bundle.
8. Write experiment, version, registry, and serving-pointer artifacts.

## 3. Data Sources

The default dev config uses:

- db_url: smartinvestor_earnings_dev
- financial_db_url: smartinvestor_earnings_dev
- etl_db_url: smartinvestor_etl_dev

The dataset itself is built from the local mirror tables in earnings DB:

- earnings_mkt_trading_history
- earnings_mkt_fundamental_history
- earnings_financial_feature_panel
- earnings_dim_corporation
- earnings_dim_industry

Important config keys:

- data.start_date
- data.end_date
- data.freq
- data.scope_prefixes

In the current config, the default dataset uses:

- start_date: 2018-01-01
- freq: D
- scope_prefixes: 60, 00, 30, 68

## 4. Feature Row Definition

Each dataset row is anchored on a concrete stock trade_date sample.

The pipeline merges:

- trading features such as close, pct_change, vol
- fundamental features such as pe, pb, ps, total_mv, turnover_rate
- financial panel features from the latest available disclosed report as of that trade_date
- industry mapping features

Examples of derived market features include:

- ret_5d
- ret_lb
- vol_lb_std
- turnover_lb_mean
- pe_rank_120d
- industry-neutralized rank features such as pe_ind_rank

If a financial feature panel is available, the pipeline uses an as-of join by:

- left key: trade_date
- right key: ann_date
- direction: backward

This means a row only sees financial data disclosed on or before that sample date.

## 5. Label Construction

After feature rows are built, the pipeline adds target columns to the same frame before writing parquet.

### 5.1 Valuation Direction Labels

The valuation-return label is defined from the future close price after horizon_days trading steps.

Formula:

$$
target\_valuation\_return_t = \frac{P_{t+h} - P_t}{P_t}
$$

Where:

- $P_t$ is the current row close
- $P_{t+h}$ is the close at the next $h$-th trading sample for the same stock
- $h = label.horizon_days$

The binary direction label is:

- target_valuation_up = 1 if target_valuation_return > 0
- else 0

Current config:

- label.horizon_days: 20

Important detail:

- this is based on 20 trading rows ahead, not 20 calendar days ahead

Current implementation behavior:

- when future close is unavailable near the series tail, target_valuation_return becomes NaN
- target_valuation_up is also kept as NaN, so those rows do not participate in valuation-direction training

### 5.2 Generic Earnings Growth Label

The pipeline also builds a generic earnings-growth target:

- target_earnings_growth

It first chooses the first available earnings-like signal from this priority order:

- n_income
- q_dt_roe
- roe
- netprofit_margin

Then it computes next-step percentage change within each stock series.

This target is now mainly a fallback target, not the primary configured objective.

### 5.3 FY-Supervised Labels

The current primary supervised labels are FY-based.

Config:

- label.fy_value_col: n_income
- label.reg_target: target_fy_value_yoy
- label.cls_target: target_fy_up

Construction logic:

1. Find rows where report_type == FY.
2. For each ts_code and fiscal_year, keep the latest FY row.
3. Build:
   - target_fy_value
   - target_fy_value_yoy
   - target_fy_up
4. Merge those FY labels back to all rows of the same ts_code and fiscal_year.

This is what makes Q1, H1, and Q3 rows trainable against same-year FY outcomes.

If exclude_fy_rows_for_training is true, FY rows themselves are excluded from train/test modeling rows, so the primary supervised samples are non-FY report rows.

### 5.4 Risk Labels

Risk labels are enabled in the current config.

The pipeline builds:

- target_risk_drawdown
- target_risk_volatility
- target_risk_score
- target_risk_level
- target_risk_level_code
- target_risk_high

These are derived from future rolling downside and realized volatility over the configured risk horizon.

## 6. Tail Rows and Missing Future Labels

For labels that require future market data, the most recent rows naturally may not have enough lookahead horizon.

Example:

- if a sample row trade_date is 2026-03-31
- and the DB does not yet contain 20 later trading samples
- target_valuation_return cannot be fully observed

Therefore:

- target_valuation_return becomes NaN
- target_valuation_up also stays NaN

For FY-supervised labels, the issue is different:

- labels are available only when the corresponding same-year FY row exists
- if FY outcome is not yet known, target_fy_value, target_fy_value_yoy, and target_fy_up remain NaN

## 7. Train/Test Split Logic

After loading the dataset, the training pipeline:

1. removes non-feature columns from feature_cols
2. coerces feature columns to numeric
3. splits train/test by trade_date cutoff

Current default cutoff:

- train.train_end_date: 2024-12-31

For FY tasks, an additional fiscal-year split guard is applied:

- if target is target_fy_value, target_fy_value_yoy, or target_fy_up
- train/test are split by fiscal_year instead of only date
- current config keeps the latest 1 fiscal year as test

This avoids same-fiscal-year leakage.

## 8. Missing Value Imputation During Training

Before fitting models, feature values are imputed hierarchically using train-only statistics:

1. stock recent-N-year median
2. industry median
3. global median

Current config:

- train.stock_median_lookback_years: 3

These imputation statistics are also stored inside the trained model bundle for later prediction-time reuse.

## 9. Report-Type Training

The current command-line training entrypoint is:

- manage.py train_report_type_models

Default report types trained in one run:

- Q1
- H1
- Q3

When keep-separated-artifacts is true, the command writes separate files such as:

- models_Q1.joblib
- models_H1.joblib
- models_Q3.joblib
- metrics_Q1.json
- metrics_H1.json
- metrics_Q3.json

If dataset shards already exist, each report_type can be trained from its own split parquet shard.

## 10. Industry Specialist Models

Within each trained report_type bundle, the pipeline can also train industry specialist submodels.

Current config:

- use_industry_models: true
- industry_train_min_rows: 240
- industry_reg_min_rows: 80

Important detail:

- industry models use the same feature_cols as the global model
- the difference is the training sample subset and, if configured, algorithm choice

An industry model is created only if the industry has enough train rows and usable target diversity.

## 11. Artifact Outputs

After training, artifacts are written to several places.

### 11.1 Main output files

- outputs/models_Q1.joblib, models_H1.joblib, models_Q3.joblib
- outputs/metrics_Q1.json, metrics_H1.json, metrics_Q3.json

### 11.2 Dataset version directory

Because output.use_dataset_versioning is currently true, the dataset is written under:

- outputs/datasets/<dataset_version>/dataset.parquet
- outputs/datasets/<dataset_version>/datasets_by_report_type/*
- outputs/datasets/<dataset_version>/dataset_meta.json

Current dataset version:

- 2018plus_20260331_r2

### 11.3 Experiment history

- outputs/experiment_runs.jsonl
- outputs/experiments/<run_id>/...

### 11.4 Versioned model directory

- outputs/model_versions/<model_version>/...

Current model version:

- dev_20260331_r2

### 11.5 Registry and serving pointer

- outputs/model_registry.jsonl
- outputs/serving.yaml

The serving pointer is updated with candidate every training run.
Production is updated only if train.promote_to_production is true.

## 12. Recommended Training Command

For the current dev configuration, use:

```powershell
Set-Location C:/Users/HANJ29/Development/code/sms/tushare_earnings_service
C:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --report-types Q1,H1,Q3 --rebuild-dataset --keep-separated-artifacts
```

This will:

- rebuild the versioned dataset
- generate report-type split datasets
- train Q1, H1, and Q3 bundles
- write experiment history
- write model_versions
- write model_registry.jsonl
- write serving.yaml candidate

## 13. Current Key Config Snapshot

At the time of writing, the important active settings are:

- data.start_date: 2018-01-01
- data.freq: D
- label.horizon_days: 20
- label.reg_target: target_fy_value_yoy
- label.cls_target: target_fy_up
- train.train_end_date: 2024-12-31
- train.fy_test_years: 1
- train.model_version: dev_20260331_r2
- output.use_dataset_versioning: true
- output.dataset_version: 2018plus_20260331_r2

## 14. Known Caveats

1. Tail rows without enough future market data will have NaN valuation-direction labels and be excluded from valuation-direction training.
2. The primary online serving path depends on trained artifacts existing in outputs.
3. Versioning artifacts are generated only after a successful training run.