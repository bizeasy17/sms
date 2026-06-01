# Earnings Project Ops Runbook

## 1. Scope

This document lists the current command-line workflow for the earnings project in:

- sync market mirror data
- sync financial raw data
- build financial feature panel and snapshot
- rebuild dataset and train models
- refresh persisted signal snapshots
- inspect experiment outputs

Workspace root used below:

```powershell
Set-Location "c:/Users/HANJ29/Development/code/sms/tushare_earnings_service"
```

Python executable used below:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe
```

## 2. Main Config Files

- `configs/default.yaml`: main training/inference config
- `configs/default_risk.yaml`: risk-oriented variant config
- `outputs/serving.yaml`: candidate/production serving pointer

Important config sections in `configs/default.yaml`:

- `data`: DB tables, date window, freq, cache path
- `feature`: feature engineering and panel sampling
- `label`: supervised target definitions
- `train`: train/test split, model version, report type settings
- `output`: dataset/model version directories and artifact files

## 3. Recommended End-to-End Flow

Current recommended sequence is:

1. Sync market mirror tables into earnings DB.
2. Sync or import financial raw tables.
3. Build financial feature panel.
4. Build or refresh financial feature snapshot.
5. Train report-type models, optionally rebuilding dataset.
6. Refresh signal snapshot table using a chosen model version or serving slot.
7. Compare experiment runs and inspect outputs.

## 4. Market Data Sync

Command:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py sync_market_local --config configs/default.yaml --mode full --freq D --retention-years 0
```

Purpose:

- sync ETL market tables into local earnings mirror tables
- target tables are typically `earnings_mkt_trading_history` and `earnings_mkt_fundamental_history`
- also refreshes corporation and industry dimension tables

Key options:

- `--mode full`: truncate target mirror tables and full reload
- `--mode range`: refresh only a specified trade_date range
- `--start-date YYYY-MM-DD`: lower bound for `range`
- `--end-date YYYY-MM-DD`: upper bound for `range`
- `--freq D|W|M`: frequency filter
- `--retention-years N`: prune target rows older than recent N years after sync
- `--retention-years 0`: disable post-sync pruning
- `--dry-run`: estimate scope without writing data

Common examples:

Full backfill without pruning:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py sync_market_local --config configs/default.yaml --mode full --freq D --retention-years 0
```

Backfill only the missing historical gap:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py sync_market_local --config configs/default.yaml --mode range --start-date 2011-04-02 --end-date 2023-04-02 --freq D --retention-years 0
```

Dry run:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py sync_market_local --config configs/default.yaml --mode full --freq D --retention-years 0 --dry-run
```

## 5. Financial Raw Data Sync

There are two main ingestion paths.

### 5.1 Direct Tushare Sync

Command:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py sync_financials_direct --scope 60,00,30,68 --apis income,balancesheet_vip,cashflow_vip,forecast_vip,express_vip,fina_indicator_vip,dividend,disclosure_date
```

Purpose:

- directly sync endpoint history from Tushare into earnings raw tables
- no intermediate file cache required

Key options:

- `--apis`: comma-separated endpoints
- `--scope`: `ALL` or ts_code prefixes such as `60,00,30,68`
- `--tscode`: single symbol smoke test
- `--start-date YYYYMMDD`
- `--end-date YYYYMMDD`
- `--limit`: limit number of symbols
- `--resume`: resume from a ts_code
- `--latest-only`: fetch only latest page for each endpoint/symbol
- `--strict-fields / --no-strict-fields`: schema mismatch handling

Smoke test example:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py sync_financials_direct --tscode 600519.SH --apis income,forecast_vip,express_vip --latest-only
```

### 5.2 Import From ETL Cache Files

Command:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py import_financial_cache --cache-dir c:/Users/HANJ29/Development/code/sms/smartinvestor_etl/analysis/financial_cache
```

Purpose:

- import already-downloaded financial cache files into earnings raw tables
- useful when ETL side has prepared files and you do not want live Tushare calls

Key options:

- `--cache-dir`: cache root directory
- `--endpoints`: subset of endpoints to import
- `--limit-files`: smoke test file count limit
- `--batch-size`: bulk upsert batch size

## 6. Financial Feature Builds

### 6.1 Build Financial Feature Panel

Command:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py build_financial_feature_panel --batch-size 5000
```

Purpose:

- build multi-row panel features by report period
- this is the table used for trade_date to ann_date as-of feature alignment

Key options:

- `--batch-size`: bulk upsert batch size
- `--limit`: limit symbols for smoke tests

Smoke test example:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py build_financial_feature_panel --limit 50 --batch-size 2000
```

### 6.2 Build Financial Feature Snapshot

Command:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py build_financial_feature_snapshot --batch-size 5000
```

Purpose:

- build/update flattened latest financial snapshot table
- useful for prediction-time latest-view features and diagnostics

### 6.3 Refresh Financial Feature Snapshot

Command:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py refresh_financial_feature_snapshot
```

Purpose:

- refresh normalized financial snapshot table from raw endpoint tables
- lighter operational command when only snapshot refresh is needed

## 7. Monthly Combined Maintenance

Command:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py monthly_financial_maintenance --scope 60,00,30,68 --latest-only
```

Purpose:

- one-stop monthly maintenance pipeline
- runs financial sync first, then rebuilds panel and snapshot

Key options:

- `--skip-sync`: rebuild panel/snapshot only
- `--skip-panel`: skip panel build
- `--skip-snapshot`: skip snapshot build
- `--start-date YYYYMMDD`
- `--end-date YYYYMMDD`
- `--latest-only`

Example: only rebuild panel and snapshot from existing raw tables:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py monthly_financial_maintenance --skip-sync
```

## 8. Dataset Build And Training

Primary command:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config configs/default.yaml --report-types Q1,H1,Q3,FY --rebuild-dataset --keep-separated-artifacts
```

Purpose:

- rebuild dataset if requested
- optionally write split datasets by report type
- train one model bundle for each requested report type
- write model and metrics artifacts under `outputs/model_versions`

Key options:

- `--config`: pipeline yaml config path
- `--report-types`: comma-separated report types such as `Q1,H1,Q3,FY`
- `--rebuild-dataset`: force dataset rebuild before training
- `--no-rebuild-dataset`: reuse existing dataset artifact
- `--keep-separated-artifacts`: write `models_Q1.joblib`, `metrics_Q1.json`, etc.

Common examples:

Train all main report types and rebuild dataset:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config configs/default.yaml --report-types Q1,H1,Q3,FY --rebuild-dataset --keep-separated-artifacts
```

Train only Q1 and H1 without rebuilding dataset:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config configs/default.yaml --report-types Q1,H1 --no-rebuild-dataset --keep-separated-artifacts
```

## 9. Signal Snapshot Refresh

Command:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py refresh_signal_snapshot --serving-slot candidate --store-mode both --scope 60,00,30,68
```

Purpose:

- run batch prediction and persist signal snapshots
- can target a specific model version or use `candidate` / `production` from `outputs/serving.yaml`

Key options:

- `--model-version`: explicit model version under `outputs/model_versions`
- `--serving-slot`: `production` or `candidate` when model version omitted
- `--store-mode`: `latest`, `history`, or `both`
- `--scope`: prefixes or `ALL`
- `--ts-code`: single symbol smoke test
- `--strict`: stop on first error

Smoke test example:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py refresh_signal_snapshot --serving-slot candidate --store-mode both --ts-code 600519.SH --strict
```

## 10. Experiment Comparison

Command:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py compare_experiment_runs --top 20 --sort-by cls_auc
```

Purpose:

- inspect historical experiment runs from `outputs/experiment_runs.jsonl`
- compare runs by chosen metric

Key options:

- `--history-file`: override history file path
- `--top`: top rows to display
- `--sort-by`: metric field to sort by
- `--ascending`: ascending sort
- `--output-csv`: write a CSV report

## 11. Typical Recipes

### 11.1 Full Historical Rebuild

```powershell
Set-Location "c:/Users/HANJ29/Development/code/sms/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py sync_market_local --config configs/default.yaml --mode full --freq D --retention-years 0
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py sync_financials_direct --scope 60,00,30,68 --latest-only
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py build_financial_feature_panel --batch-size 5000
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py build_financial_feature_snapshot --batch-size 5000
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config configs/default.yaml --report-types Q1,H1,Q3,FY --rebuild-dataset --keep-separated-artifacts
```

### 11.2 Rebuild Dataset And Retrain Only

```powershell
Set-Location "c:/Users/HANJ29/Development/code/sms/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config configs/default.yaml --report-types Q1,H1,Q3,FY --rebuild-dataset --keep-separated-artifacts
```

### 11.3 Candidate Signal Refresh After Training

```powershell
Set-Location "c:/Users/HANJ29/Development/code/sms/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py refresh_signal_snapshot --serving-slot candidate --store-mode both --scope 60,00,30,68
```

## 12. Quick Validation Checks

Check mirror table range:

```powershell
@'
from sqlalchemy import create_engine, text
import yaml
from pathlib import Path

cfg = yaml.safe_load(Path("configs/default.yaml").read_text(encoding="utf-8"))
engine = create_engine(cfg["data"]["db_url"])

for table in ["earnings_mkt_trading_history", "earnings_mkt_fundamental_history"]:
    with engine.connect() as conn:
        row = conn.execute(text(f"select min(trade_date), max(trade_date), count(*) from {table}")).fetchone()
    print(table, row)
'@ | c:/Users/HANJ29/Development/vdev1/Scripts/python.exe -
```

Check generated dataset versions:

```powershell
Get-ChildItem "outputs/datasets" -Directory | Select-Object Name, LastWriteTime
```

Check split dataset row counts:

```powershell
@'
import pandas as pd, pathlib
base = pathlib.Path("outputs/datasets/15y_20260402_r1/datasets_by_report_type")
for rt in ["Q1", "H1", "Q3", "FY", "UNKNOWN"]:
    p = base / f"dataset_{rt}.parquet"
    if p.exists():
        print(rt, len(pd.read_parquet(p, columns=["ts_code"])))
    else:
        print(rt, "missing")
'@ | c:/Users/HANJ29/Development/vdev1/Scripts/python.exe -
```

## 13. Notes

- `sync_market_local` operates on local mirror tables, not the final dataset artifacts.
- `retention-years` only applies after market sync and can delete old mirror rows if set to a positive number.
- `train_report_type_models --rebuild-dataset` uses the current `output.dataset_version` in the selected config.
- `refresh_signal_snapshot` can use `outputs/serving.yaml` candidate/production pointers if `--model-version` is omitted.
- For FY-supervised work, verify both dataset coverage and `metrics_*.json` target columns after training.