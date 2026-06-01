from __future__ import annotations

import numpy as np
import pandas as pd


def _safe_pct_change(series: pd.Series, periods: int):
    return series.replace(0, np.nan).pct_change(periods=periods)


def build_features(
    trading: pd.DataFrame,
    fundamental: pd.DataFrame,
    financial_cache: dict[str, pd.DataFrame] | None = None,
    lookback_days: int = 20,
    min_history_rows: int = 120,
) -> pd.DataFrame:
    trading = trading.copy()
    fundamental = fundamental.copy()

    needed_cols = ["ts_code", "trade_date", "close", "pct_change", "vol"]
    for col in needed_cols:
        if col not in trading.columns:
            trading[col] = np.nan

    for col in ["ts_code", "trade_date", "pe", "pb", "ps", "total_mv", "circ_mv", "turnover_rate"]:
        if col not in fundamental.columns:
            fundamental[col] = np.nan

    merged = pd.merge(
        trading[["ts_code", "trade_date", "close", "pct_change", "vol"]],
        fundamental[["ts_code", "trade_date", "pe", "pb", "ps", "total_mv", "circ_mv", "turnover_rate"]],
        on=["ts_code", "trade_date"],
        how="left",
    ).sort_values(["ts_code", "trade_date"])

    grp = merged.groupby("ts_code", group_keys=False)
    lookback_days = max(5, int(lookback_days))
    merged["ret_5d"] = grp["close"].transform(lambda s: _safe_pct_change(s, 5))
    merged["ret_lb"] = grp["close"].transform(lambda s: _safe_pct_change(s, lookback_days))
    merged["vol_lb_std"] = grp["pct_change"].transform(lambda s: s.rolling(lookback_days).std())
    merged["turnover_lb_mean"] = grp["turnover_rate"].transform(lambda s: s.rolling(lookback_days).mean())
    merged["pe_rank_120d"] = grp["pe"].transform(
        lambda s: s.rolling(120).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
    )

    # Optional financial-cache features: pick latest per ts_code from fina_indicator/income.
    if financial_cache:
        fina = financial_cache.get("fina_indicator")
        income = financial_cache.get("income")
        fin_feat = pd.DataFrame({"ts_code": merged["ts_code"].drop_duplicates()})

        if fina is not None and not fina.empty:
            use_cols = [c for c in ["ts_code", "roe", "grossprofit_margin", "netprofit_margin", "q_dt_roe", "end_date"] if c in fina.columns]
            fina2 = fina[use_cols].copy()
            if "end_date" in fina2.columns:
                fina2["end_date"] = pd.to_datetime(fina2["end_date"], errors="coerce")
                fina2 = fina2.sort_values(["ts_code", "end_date"]).groupby("ts_code", as_index=False).tail(1)
            else:
                fina2 = fina2.groupby("ts_code", as_index=False).tail(1)
            fin_feat = fin_feat.merge(fina2.drop(columns=[c for c in ["end_date"] if c in fina2.columns]), on="ts_code", how="left")

        if income is not None and not income.empty:
            use_cols = [c for c in ["ts_code", "revenue", "n_income", "end_date"] if c in income.columns]
            income2 = income[use_cols].copy()
            if "end_date" in income2.columns:
                income2["end_date"] = pd.to_datetime(income2["end_date"], errors="coerce")
                income2 = income2.sort_values(["ts_code", "end_date"]).groupby("ts_code", as_index=False).tail(1)
            else:
                income2 = income2.groupby("ts_code", as_index=False).tail(1)
            fin_feat = fin_feat.merge(income2.drop(columns=[c for c in ["end_date"] if c in income2.columns]), on="ts_code", how="left")

        merged = merged.merge(fin_feat, on="ts_code", how="left")

    counts = merged.groupby("ts_code").size()
    valid_codes = set(counts[counts >= int(min_history_rows)].index)
    merged = merged[merged["ts_code"].isin(valid_codes)].copy()

    merged = merged.replace([np.inf, -np.inf], np.nan)
    merged = merged.dropna(subset=["close"]).reset_index(drop=True)
    return merged
