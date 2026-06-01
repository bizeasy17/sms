from pathlib import Path

import pandas as pd

p = Path(r"c:/Users/HANJ29/Development/code/sms/tushare_earnings_service/outputs/datasets/15y_20260402_r1/datasets_by_report_type/dataset_FY.parquet")
df = pd.read_parquet(p)
print("rows", len(df))

for c in ["target_fy_up", "target_fy_value_yoy", "target_valuation_up", "fiscal_year", "is_fy_row"]:
    if c in df.columns:
        s = df[c]
        nunique = int(s.dropna().nunique()) if s.notna().any() else 0
        print(c, "nonnull", int(s.notna().sum()), "nunique", nunique)

y = pd.to_numeric(df["fiscal_year"], errors="coerce")
years = sorted(int(v) for v in y.dropna().unique())
print("year_minmax", years[0], years[-1], "year_count", len(years))

test_years = {years[-1]}
tr = df[~y.isin(test_years)]
te = df[y.isin(test_years)]
print("train_rows", len(tr), "test_rows", len(te))
for c in ["target_fy_up", "target_valuation_up"]:
    if c in df.columns:
        tr_nu = int(tr[c].dropna().nunique()) if tr[c].notna().any() else 0
        te_nu = int(te[c].dropna().nunique()) if te[c].notna().any() else 0
        print(
            c,
            "train_nonnull",
            int(tr[c].notna().sum()),
            "train_nunique",
            tr_nu,
            "test_nonnull",
            int(te[c].notna().sum()),
            "test_nunique",
            te_nu,
        )
