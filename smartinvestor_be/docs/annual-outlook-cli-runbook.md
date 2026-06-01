# Annual Outlook CLI Runbook

This runbook describes the MVP command for annual forecast + valuation outlook using three scenarios (`base`, `bull`, `bear`).

## 1. Command

```powershell
python manage.py annualoutlook
```

## 2. Common Options

- `--trade-date YYYY-MM-DD`: valuation date, default latest D trade date
- `--scope 688`: stock pool scope, supports `ALL` or prefixes like `60,0,3,688`
- `--code-offset` / `--code-limit`: sample subset for quick validation
- `--base-profit-growth-pct`: base FY netprofit growth (default `12`)
- `--bull-profit-growth-pct`: bull FY netprofit growth (default `base+8`)
- `--bear-profit-growth-pct`: bear FY netprofit growth (default `base-8`)
- `--base-revenue-growth-pct`: base FY revenue growth (default follows base profit growth)
- `--bull-revenue-growth-pct`: bull FY revenue growth (default follows bull profit growth)
- `--bear-revenue-growth-pct`: bear FY revenue growth (default follows bear profit growth)
- `--bull-multiple-premium-pct`: bull multiple uplift (default `10`)
- `--bear-multiple-discount-pct`: bear multiple haircut (default `10`)
- `--top N`: print top N rows by base upside
- `--output-csv`: save full table to CSV
- `--outlook-version`: forecast/valuation outlook version tag
- `--persist`: persist scenario rows to DB table `prediction_annualoutlooksnapshot`

## 3. Example (UAT)

```powershell
python manage.py annualoutlook ^
  --trade-date 2026-03-17 ^
  --scope 688 ^
  --outlook-version annual_q1_v20260319 ^
  --persist ^
  --base-profit-growth-pct 12 ^
  --bull-profit-growth-pct 20 ^
  --bear-profit-growth-pct 4 ^
  --bull-multiple-premium-pct 10 ^
  --bear-multiple-discount-pct 10 ^
  --top 50 ^
  --output-csv output/annual_outlook_688_2026-03-17.csv
```

## 4. Output Highlights

- `base_composite_price`, `bull_composite_price`, `bear_composite_price`
- `base_upside_pct`, `bull_upside_pct`, `bear_upside_pct`
- `*_implied_price_pe`, `*_implied_price_ps`, `*_implied_price_pb`
- `*_forecast_netprofit`, `*_forecast_revenue`

## 5. Notes

- This is an MVP forecast model based on local fundamentals and scenario assumptions.
- It does not replace a full statement model; use as a structured outlook layer for decision support.
- Versioning key in DB: `ts_code + trade_date + freq + outlook_version + assumptions_signature + scenario`.
- Re-run with the same version/signature updates existing rows; changing assumptions generates a new signature lineage.
