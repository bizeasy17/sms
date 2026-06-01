import json
from pathlib import Path

import pandas as pd
import yaml

base = Path("c:/Users/HANJ29/Development/code/sms/tushare_earnings_service")
cfg = yaml.safe_load((base / "configs/default.yaml").read_text(encoding="utf-8"))
tr_end = cfg.get("train", {}).get("train_end_date")
split = base / "outputs" / "datasets_by_report_type"
manifest = json.loads((split / "manifest.json").read_text(encoding="utf-8"))
cands = ["target_fy_up", "target_valuation_up"]

for item in manifest.get("items", []):
	rt = str(item.get("report_type"))
	if rt not in {"Q1", "H1", "Q3"}:
		continue

	df = pd.read_parquet(Path(item["path"])).sort_values("trade_date")
	cutoff = pd.Timestamp(tr_end) if tr_end else df["trade_date"].quantile(0.8)
	train = df[df["trade_date"] <= cutoff]
	test = df[df["trade_date"] > cutoff]

	if len(train) == 0 and len(df) > 1:
		cutoff = df["trade_date"].quantile(0.8)
		train = df[df["trade_date"] <= cutoff]
		test = df[df["trade_date"] > cutoff]

	print()
	print(
		rt,
		{
			"rows": len(df),
			"train": len(train),
			"test": len(test),
			"cutoff": str(cutoff.date()) if hasattr(cutoff, "date") else str(cutoff),
		},
	)

	for c in cands:
		if c in df.columns:
			t = test[c].dropna()
			pos = float((t > 0.5).mean()) if len(t) > 0 else None
			print(
				" ",
				c,
				{
					"test_nonnull": int(len(t)),
					"test_nunique": int(t.nunique()) if len(t) > 0 else 0,
					"test_pos_ratio": pos,
				},
			)

