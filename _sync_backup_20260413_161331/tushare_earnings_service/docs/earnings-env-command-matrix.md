# Earnings Environments Command Matrix

## 1. Purpose

This document compares the current DEV and UAT earnings environments and isolates the command entrypoints for each environment.

Use this document when you want to avoid mixing:

- workspace root
- config file
- DB target
- output directory
- serving pointer

## 2. Environment Roots

DEV root:

```powershell
Set-Location "c:/Users/HANJ29/Development/code/sms/tushare_earnings_service"
```

UAT root:

```powershell
Set-Location "c:/Users/HANJ29/Development/web/UAT/tushare_earnings_service"
```

Common Python executable currently used:

```powershell
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe
```

## 3. Current Config Snapshot

### 3.1 DEV current config

Config file:

- `c:/Users/HANJ29/Development/code/sms/tushare_earnings_service/configs/default.yaml`

Current key settings:

- `data.db_url`: `smartinvestor_earnings_dev`
- `data.financial_db_url`: `smartinvestor_earnings_dev`
- `data.etl_db_url`: `smartinvestor_etl_dev`
- `output.dir`: `c:/Users/HANJ29/Development/code/sms/tushare_earnings_service/outputs`
- `output.dataset_version`: `15y_20260402_r1`
- `feature.prepare_sampling.recent_years_per_symbol`: `15`
- `feature.prepare_sampling.max_rows_per_report_type`: `0`
- `output.split_max_rows_per_report_type`: `0`

### 3.2 UAT current config

Config file:

- `c:/Users/HANJ29/Development/web/UAT/tushare_earnings_service/configs/default.yaml`

Current key settings:

- `data.db_url`: `smartinvestor_earnings_uat`
- `data.financial_db_url`: `smartinvestor_earnings_uat`
- `data.etl_db_url`: `smartinvestor_etl`
- `output.dir`: `c:/Users/HANJ29/Development/web/UAT/tushare_earnings_service/outputs`
- `output.dataset_version`: `15y_20260402_uat_r1`
- `feature.prepare_sampling.recent_years_per_symbol`: `5`
- `feature.prepare_sampling.max_rows_per_report_type`: `100000`
- `output.split_max_rows_per_report_type`: `100000`

## 4. Important Isolation Warning

UAT project root and key config targets are now isolated from DEV.

Current isolation state:

- UAT earnings DB: `smartinvestor_earnings_uat`
- UAT output directory: `c:/Users/HANJ29/Development/web/UAT/tushare_earnings_service/outputs`

That means:

1. Running UAT commands with `configs/default.yaml` now writes to UAT earnings DB and UAT output path.
2. Root-level command isolation and config-level target isolation are both in place.
3. You should still run preflight checks before batch write operations.

## 5. Preflight Check Commands

### 5.1 DEV preflight

```powershell
Set-Location "c:/Users/HANJ29/Development/code/sms/tushare_earnings_service"
@'
import yaml
from pathlib import Path
cfg = yaml.safe_load(Path("configs/default.yaml").read_text(encoding="utf-8"))
print("db_url:", cfg["data"]["db_url"])
print("financial_db_url:", cfg["data"]["financial_db_url"])
print("etl_db_url:", cfg["data"]["etl_db_url"])
print("output.dir:", cfg["output"]["dir"])
print("dataset_version:", cfg["output"]["dataset_version"])
'@ | c:/Users/HANJ29/Development/vdev1/Scripts/python.exe -
```

### 5.2 UAT preflight

```powershell
Set-Location "c:/Users/HANJ29/Development/web/UAT/tushare_earnings_service"
@'
import yaml
from pathlib import Path
cfg = yaml.safe_load(Path("configs/default.yaml").read_text(encoding="utf-8"))
print("db_url:", cfg["data"]["db_url"])
print("financial_db_url:", cfg["data"]["financial_db_url"])
print("etl_db_url:", cfg["data"]["etl_db_url"])
print("output.dir:", cfg["output"]["dir"])
print("dataset_version:", cfg["output"]["dataset_version"])
'@ | c:/Users/HANJ29/Development/vdev1/Scripts/python.exe -
```

## 6. Isolated Command Pairs

### 6.1 Sync market mirror

DEV:

```powershell
Set-Location "c:/Users/HANJ29/Development/code/sms/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py sync_market_local --config configs/default.yaml --mode full --freq D --retention-years 0
```

UAT:

```powershell
Set-Location "c:/Users/HANJ29/Development/web/UAT/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py sync_market_local --config configs/default.yaml --mode full --freq D --retention-years 0
```

Note:

- The commands are environment-isolated only by workspace root and config file path.
- Current UAT config also points to UAT DB/output targets, so DB/output isolation is in place.

### 6.2 Sync financial raw data

DEV:

```powershell
Set-Location "c:/Users/HANJ29/Development/code/sms/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py sync_financials_direct --scope 60,00,30,68 --apis income,balancesheet_vip,cashflow_vip,forecast_vip,express_vip,fina_indicator_vip,dividend,disclosure_date
```

UAT:

```powershell
Set-Location "c:/Users/HANJ29/Development/web/UAT/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py sync_financials_direct --scope 60,00,30,68 --apis income,balancesheet_vip,cashflow_vip,forecast_vip,express_vip,fina_indicator_vip,dividend,disclosure_date
```

### 6.3 Build financial feature panel

DEV:

```powershell
Set-Location "c:/Users/HANJ29/Development/code/sms/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py build_financial_feature_panel --batch-size 5000
```

UAT:

```powershell
Set-Location "c:/Users/HANJ29/Development/web/UAT/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py build_financial_feature_panel --batch-size 5000
```

### 6.4 Build financial feature snapshot

DEV:

```powershell
Set-Location "c:/Users/HANJ29/Development/code/sms/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py build_financial_feature_snapshot --batch-size 5000
```

UAT:

```powershell
Set-Location "c:/Users/HANJ29/Development/web/UAT/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py build_financial_feature_snapshot --batch-size 5000
```

### 6.5 Train report-type models

DEV:

```powershell
Set-Location "c:/Users/HANJ29/Development/code/sms/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config configs/default.yaml --report-types Q1,H1,Q3,FY --rebuild-dataset --keep-separated-artifacts
```

UAT:

```powershell
Set-Location "c:/Users/HANJ29/Development/web/UAT/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py train_report_type_models --config configs/default.yaml --report-types Q1,H1,Q3,FY --rebuild-dataset --keep-separated-artifacts
```

### 6.6 Refresh signal snapshot

DEV:

```powershell
Set-Location "c:/Users/HANJ29/Development/code/sms/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py refresh_signal_snapshot --serving-slot candidate --store-mode both --scope 60,00,30,68
```

UAT:

```powershell
Set-Location "c:/Users/HANJ29/Development/web/UAT/tushare_earnings_service"
c:/Users/HANJ29/Development/vdev1/Scripts/python.exe manage.py refresh_signal_snapshot --serving-slot candidate --store-mode both --scope 60,00,30,68
```

## 7. Environment-Specific Batch Files

UAT root currently includes ready-to-run batch wrappers:

- `monthly_financial_maintenance.bat`
- `monthly_full_pipeline.bat`
- `monthly_signal_refresh.bat`
- `full_signal_snapshot_refresh.bat`

These exist under:

- `c:/Users/HANJ29/Development/web/UAT/tushare_earnings_service`

Treat them as UAT entrypoints, but still verify config isolation first.

## 8. Safe Operating Rules

1. Always run the preflight check before any write command in UAT.
2. Never assume UAT root means UAT DB/output.
3. For dataset rebuilds, verify `output.dataset_version` before training.
4. For signal refresh, verify `outputs/serving.yaml` in the same root you are operating in.
5. If UAT must be truly isolated, first fix UAT `configs/default.yaml` so `db_url`, `financial_db_url`, and `output.dir` point to UAT resources.

## 9. Recommended Next Cleanup

Current UAT isolation is ready for normal operations. Optional next cleanup:

1. Decide whether UAT should keep `feature.prepare_sampling` at 5 years + row caps, or align with DEV's 15-year/cap-free settings.
2. If ETL also has strict UAT DB isolation requirements, confirm whether `data.etl_db_url` should switch from `smartinvestor_etl` to a dedicated UAT ETL DB.
3. Keep UAT dataset and serving lifecycle independent from DEV model promotion.

Until those optional items are decided, command isolation is already safe for DB/output boundaries.