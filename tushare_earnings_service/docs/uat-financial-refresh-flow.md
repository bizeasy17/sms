# UAT Financial Refresh Flow

## 1. Purpose

This document describes the actual UAT data flow used to refresh earnings signals, including:

- where raw financial data comes from
- how feature panel and latest snapshot are rebuilt
- which feature source `refresh_signal_snapshot` uses at predict time
- what each monthly batch step is responsible for

## 2. End-to-End Flow

The current UAT monthly chain is:

1. ETL side market refresh
2. local earnings market mirror sync
3. online financial endpoint sync into raw split tables
4. financial feature panel rebuild
5. latest financial feature snapshot rebuild
6. batch prediction and signal snapshot persistence

In command terms:

```powershell
python manage.py sync_market_local
python manage.py sync_financials_direct
python manage.py build_financial_feature_panel
python manage.py build_financial_feature_snapshot
python manage.py refresh_signal_snapshot
```

The orchestration command used by UAT for finance is:

```powershell
python manage.py monthly_financial_maintenance
```

It runs these three steps in order:

1. `sync_financials_direct`
2. `build_financial_feature_panel`
3. `build_financial_feature_snapshot`

## 3. Data Sources by Layer

### 3.1 Market data used by predict path

Predict-time market features come from local earnings DB mirror tables:

- `earnings_mkt_trading_history`
- `earnings_mkt_fundamental_history`
- `earnings_dim_corporation`
- `earnings_dim_industry`

These are populated by:

```powershell
python manage.py sync_market_local
```

Important:

- `sync_market_local` does not fetch financial statements.
- It only mirrors trading, valuation-style fundamentals, corporation mapping, and industry mapping.

### 3.2 Raw financial data used to build features

Raw financial statement data is synced online from Tushare Pro by:

```powershell
python manage.py sync_financials_direct
```

Its upstream source is online Tushare API, not ETL local market tables.

The synced raw endpoint tables include:

- `earnings_fin_income`
- `earnings_fin_balancesheet_vip`
- `earnings_fin_cashflow_vip`
- `earnings_fin_fina_indicator_vip`
- and other endpoint-specific tables configured in `data.financial_endpoint_tables`

### 3.3 Financial feature panel

The financial feature panel is a multi-row panel by symbol and report period.

Default table in UAT config:

- `earnings_financial_feature_panel`

It is built by:

```powershell
python manage.py build_financial_feature_panel
```

This table is mainly for training/prepare-style workflows and report-period history reconstruction.

### 3.4 Financial feature snapshot

The latest financial feature snapshot is a latest-row snapshot per symbol.

Default snapshot table used by predict path when `financial_snapshot_table` is not explicitly configured:

- `earnings_financial_feature_snapshot`

It is built by:

```powershell
python manage.py build_financial_feature_snapshot
```

## 4. What `refresh_signal_snapshot` Actually Uses

`refresh_signal_snapshot` does not directly query a feature table by itself.

It loops through symbols and calls:

```python
pipeline.predict(ts_code, ...)
```

The predict path uses features in this order:

1. build live feature frame from local market mirror tables
2. load latest financial snapshot for the symbol from `earnings_financial_feature_snapshot`
3. overwrite/fill financial columns using that latest snapshot
4. if live features are unavailable, fallback to the versioned training dataset parquet

Returned field:

- `feature_data_source = live_db` when live DB features were used
- `feature_data_source = dataset_fallback` when dataset fallback was used

Important distinction:

- predict-time primary financial source is the latest financial snapshot table
- not the full panel table
- panel is still needed because snapshot is rebuilt from raw financial data and panel-oriented logic

## 5. UAT Config Defaults Relevant to This Flow

In UAT `configs/default.yaml`:

- `data.financial_db_url` points to `smartinvestor_earnings_uat`
- `data.financial_feature_table` is `earnings_financial_feature_panel`
- `feature.use_financial_feature_snapshot = true`
- market mirror tables point to local earnings DB tables

Predict path behavior:

- panel loading helpers use `data.financial_feature_table`
- latest predict-time snapshot loading uses `data.financial_snapshot_table`
- if `financial_snapshot_table` is absent in config, it falls back to `earnings_financial_feature_snapshot`

## 6. UAT Scheduled Batch Responsibilities

### 6.1 `quarterly_full_pipeline.bat`

This script runs:

1. ETL resample trading
2. ETL resample funda
3. ETL fetch corporation
4. `sync_market_local`
5. `monthly_financial_maintenance`
6. `refresh_signal_snapshot`

So it covers both market data refresh and financial feature refresh.

In the current UAT orchestration, this full pipeline is triggered quarterly rather than monthly.

### 6.2 `monthly_financial_maintenance`

This command only covers financial-side maintenance:

1. `sync_financials_direct`
2. `build_financial_feature_panel`
3. `build_financial_feature_snapshot`

It supports:

- `--latest-only` for monthly incremental online endpoint pulls
- `--skip-sync`
- `--skip-panel`
- `--skip-snapshot`

## 7. Recommended Manual Recovery Order

When UAT financial coverage is low, use this order:

1. Sync raw financial endpoint tables first

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py sync_financials_direct --scope 60,00,30,68 --apis income,balancesheet_vip,cashflow_vip,fina_indicator_vip --api-limit 2000 --max-pages 200 --batch-size 1000
```

2. Rebuild financial feature panel

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py build_financial_feature_panel --batch-size 1000
```

3. Rebuild latest financial feature snapshot

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py build_financial_feature_snapshot --batch-size 1000
```

4. Refresh signal snapshot after financial coverage is restored

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py refresh_signal_snapshot --scope 60,00,30,68 --store-mode both --serving-slot production --batch-key manual_refresh_202604
```

## 8. Operational Notes

- If raw financial tables contain only a few symbols, panel and snapshot will also be sparse.
- If latest financial snapshot is sparse, `refresh_signal_snapshot` will still run, but FY/Q3 quality and coverage will be weak.
- A successful refresh job does not imply good financial coverage.
- For signal quality validation, always verify both raw financial coverage and latest snapshot coverage before trusting refresh output.

## 9. Current UAT Root Scheduling Placement

At UAT root level, the earnings service is no longer scheduled as a standalone monthly root task.
Instead, it is wired into the consolidated root scheduler batches under `C:\Users\HANJ29\Development\web\UAT\`.

Current placement:

- `quarterly.bat`
	- calls `tushare_earnings_service\quarterly_full_pipeline.bat`
	- this remains the main earnings-service orchestration entry for quarterly refresh
- `quarterly_full_pipeline.bat`
	- still contains `sync_market_local`
	- still contains `monthly_financial_maintenance`
	- still contains `refresh_signal_snapshot`

Related earnings-service batch files that remain available for manual or partial use:

- `quarterly_full_pipeline.bat`
- `quarterly_financial_maintenance.bat`
- `quarterly_signal_refresh.bat`

This means the operator-facing root scheduler flow is:

1. run root `quarterly.bat`
2. root `quarterly.bat` enters earnings-service quarterly full pipeline
3. quarterly full pipeline performs market sync, financial maintenance, and signal refresh inside the earnings project

So the current UAT setup preserves the original "single earnings full-pipeline call from root quarterly batch" behavior, while using quarterly naming consistently at the file level.