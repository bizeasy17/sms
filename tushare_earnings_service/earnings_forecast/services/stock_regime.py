from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


VALID_STOCK_REGIMES = {"GROWTH", "BALANCE", "DEFENSIVE", "RISK_OFF"}


@dataclass(frozen=True)
class StockRegimeMetrics:
    regime: str
    ma20: float
    ma60: float
    volatility_20d: float
    drawdown_60d: float


def classify_stock_regime(closes: Iterable[float]) -> StockRegimeMetrics | None:
    series = pd.to_numeric(pd.Series(list(closes)), errors="coerce").dropna()
    series = series[series > 0]
    if len(series) < 60:
        return None
    ma20 = float(series.tail(20).mean())
    ma60 = float(series.tail(60).mean())
    close = float(series.iloc[-1])
    volatility_20d = float(series.pct_change().tail(20).std() or 0.0)
    peak60 = float(series.tail(60).max())
    drawdown_60d = close / peak60 - 1.0 if peak60 > 0 else 0.0
    ma_ratio = close / ma60 if ma60 > 0 else 1.0

    if (ma20 < ma60 and (ma_ratio <= 0.94 or drawdown_60d <= -0.18)):
        regime = "RISK_OFF"
    elif ma20 < ma60 or ma_ratio < 0.98 or drawdown_60d <= -0.10 or volatility_20d >= 0.035:
        regime = "DEFENSIVE"
    elif ma20 > ma60 and ma_ratio >= 1.02 and drawdown_60d > -0.08 and volatility_20d < 0.03:
        regime = "GROWTH"
    else:
        regime = "BALANCE"
    return StockRegimeMetrics(regime, ma20, ma60, volatility_20d, drawdown_60d)


def next_regime_state(current: str, pending: str, pending_days: int, detected: str, confirm_days: int) -> tuple[str, str, int, bool]:
    """Return confirmed regime, pending regime, pending count, and trigger flag."""
    if detected not in VALID_STOCK_REGIMES:
        raise ValueError("invalid detected regime")
    if not current:
        return detected, "", 0, False
    if detected == current:
        return current, "", 0, False
    next_pending_days = pending_days + 1 if pending == detected else 1
    if next_pending_days >= max(1, confirm_days):
        return detected, "", 0, True
    return current, detected, next_pending_days, False