from __future__ import annotations

import numpy as np
import pandas as pd


def build_targets(df: pd.DataFrame, horizon_days: int = 20) -> pd.DataFrame:
    frame = df.sort_values(["ts_code", "trade_date"]).copy()
    grp = frame.groupby("ts_code", group_keys=False)

    future_close = grp["close"].shift(-horizon_days)
    frame["target_valuation_return"] = (future_close - frame["close"]) / frame["close"].replace(0, np.nan)
    frame["target_valuation_up"] = (frame["target_valuation_return"] > 0).astype(float)

    # earnings proxy: combine available profitability proxies as next-period signal
    earnings_signal = None
    for col in ["n_income", "q_dt_roe", "roe", "netprofit_margin"]:
        if col in frame.columns:
            earnings_signal = frame[col] if earnings_signal is None else earnings_signal.fillna(frame[col])

    if earnings_signal is None:
        frame["target_earnings_growth"] = np.nan
    else:
        # Robust fallback: use shifted earnings-signal pct_change by symbol.
        frame["_earnings_signal"] = earnings_signal
        frame["target_earnings_growth"] = grp["_earnings_signal"].transform(
            lambda s: s.replace(0, np.nan).pct_change().shift(-1)
        )
        frame.drop(columns=["_earnings_signal"], inplace=True)

    return frame

