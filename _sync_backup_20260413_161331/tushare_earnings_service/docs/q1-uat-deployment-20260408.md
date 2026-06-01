# Q1 UAT Deployment Record (2026-04-08)

## Summary
- Purpose: Deploy the latest DEV-trained Q1 model into the existing UAT mixed model version folder.
- Deployment target folder:
  - `C:/Users/HANJ29/Development/web/UAT/tushare_earnings_service/outputs/model_versions/dev_20260404_mix_q1h1_base_q3fy_v2`
- Deployment scope: Q1 artifacts only (`models_Q1.joblib`, `metrics_Q1.json`).

## Source Artifacts (DEV)
- Source run_id: `20260408_082736_hgb_hgb_a0937a47`
- Source model file:
  - `C:/Users/HANJ29/Development/code/sms/tushare_earnings_service/outputs/experiments/20260408_082736_hgb_hgb_a0937a47/models_Q1.joblib`
- Source metrics file:
  - `C:/Users/HANJ29/Development/code/sms/tushare_earnings_service/outputs/experiments/20260408_082736_hgb_hgb_a0937a47/metrics_Q1.json`

## Backup Before Replace (UAT)
- Backup timestamp suffix: `20260408_163443`
- Backed-up model:
  - `C:/Users/HANJ29/Development/web/UAT/tushare_earnings_service/outputs/model_versions/dev_20260404_mix_q1h1_base_q3fy_v2/models_Q1.joblib.bak_20260408_163443`
- Backed-up metrics:
  - `C:/Users/HANJ29/Development/web/UAT/tushare_earnings_service/outputs/model_versions/dev_20260404_mix_q1h1_base_q3fy_v2/metrics_Q1.json.bak_20260408_163443`

## Replaced Files (UAT)
- `C:/Users/HANJ29/Development/web/UAT/tushare_earnings_service/outputs/model_versions/dev_20260404_mix_q1h1_base_q3fy_v2/models_Q1.joblib`
- `C:/Users/HANJ29/Development/web/UAT/tushare_earnings_service/outputs/model_versions/dev_20260404_mix_q1h1_base_q3fy_v2/metrics_Q1.json`

## Post-Deployment Verification
Verified from deployed `metrics_Q1.json`:
- `run_id`: `20260408_082736_hgb_hgb_a0937a47`
- `reg_mae`: `0.9851702070727312`
- `cls_auc`: `0.7876996376555779`

## Rollback
If rollback is required, replace current Q1 files with backups:
1. Copy `models_Q1.joblib.bak_20260408_163443` to `models_Q1.joblib`.
2. Copy `metrics_Q1.json.bak_20260408_163443` to `metrics_Q1.json`.
3. Re-run verification by checking `run_id` and key metrics.

## Notes
- The deployment reused the existing mixed UAT version folder (`dev_20260404_mix_q1h1_base_q3fy_v2`) as requested.
- Q3/H1/FY artifacts were not modified in this operation.
