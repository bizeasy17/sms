import time
from datetime import date, datetime
from typing import Dict, Iterable, Optional

import pandas as pd


class SwHistoryQuantileService:
    """Independent helper to fetch SW daily history and compute quantile anchors."""

    def __init__(
        self,
        pro,
        window_years: Iterable[int] = (3, 5, 10),
        quantile: float = 0.5,
        min_samples: int = 120,
        min_request_interval: float = 0.31,
        retry_count: int = 3,
        retry_backoff_seconds: float = 0.8,
    ):
        self.pro = pro
        self.window_years = tuple(sorted({int(y) for y in window_years if int(y) > 0})) or (3, 5, 10)
        self.quantile = float(max(0.05, min(0.95, quantile)))
        self.min_samples = max(20, int(min_samples))
        self.min_request_interval = max(0.0, float(min_request_interval or 0.0))
        self.retry_count = max(1, int(retry_count or 1))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds or 0.0))
        self._last_request_ts = 0.0

    def build_history_payload(self, index_code: str, end_trade_date: str) -> Dict:
        """Return per-window quantiles and blended anchors for PE/PB/PS."""
        end_dt = self._parse_trade_date(end_trade_date)
        metric_payload = {"pe": {}, "pb": {}, "ps": {}}

        max_years = max(self.window_years)
        start_dt = self._subtract_years(end_dt, max_years)
        df = self._fetch_sw_daily(index_code=index_code, start_date=start_dt, end_date=end_dt)

        for years in self.window_years:
            window_df = self._slice_window(df, end_dt=end_dt, years=years)
            metric_payload["pe"][f"{years}y"] = self._series_payload(window_df.get("pe"))
            metric_payload["pb"][f"{years}y"] = self._series_payload(window_df.get("pb"))
            metric_payload["ps"][f"{years}y"] = self._series_payload(window_df.get("ps"))

        return {
            "windows": [f"{y}y" for y in self.window_years],
            "quantile": self.quantile,
            "min_samples": self.min_samples,
            "metrics": metric_payload,
            "anchors": {
                "pe": self._blended_anchor(metric_payload["pe"]),
                "pb": self._blended_anchor(metric_payload["pb"]),
                "ps": self._blended_anchor(metric_payload["ps"]),
            },
        }

    def _series_payload(self, series) -> Dict:
        if series is None:
            return {"sample_count": 0, "p50": None}
        cleaned = pd.to_numeric(series, errors="coerce").dropna()
        cleaned = cleaned[cleaned > 0]
        count = int(len(cleaned))
        if count < self.min_samples:
            return {"sample_count": count, "p50": None}
        return {
            "sample_count": count,
            "p50": round(float(cleaned.quantile(self.quantile)), 4),
        }

    def _blended_anchor(self, window_payload: Dict[str, Dict]) -> Optional[float]:
        # Default long-cycle weights, robust for noisy short windows.
        base_weights = {"3y": 0.2, "5y": 0.5, "10y": 0.3}
        valid_values = []
        valid_weights = []
        for window, payload in window_payload.items():
            value = payload.get("p50") if isinstance(payload, dict) else None
            if value is None:
                continue
            valid_values.append(float(value))
            valid_weights.append(float(base_weights.get(window, 0.0)))

        if not valid_values:
            return None

        total_weight = sum(valid_weights)
        if total_weight <= 0:
            return round(sum(valid_values) / len(valid_values), 4)
        return round(sum(v * w for v, w in zip(valid_values, valid_weights)) / total_weight, 4)

    def _sleep_for_rate_limit(self):
        if self.min_request_interval <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_request_ts
        if elapsed < self.min_request_interval:
            time.sleep(self.min_request_interval - elapsed)

    @staticmethod
    def _is_rate_limit_error(exc) -> bool:
        message = str(exc or "").lower()
        return any(
            marker in message
            for marker in ["200/min", "too many", "rate limit", "rate_limit", "429", "频率", "限频"]
        )

    @staticmethod
    def _subtract_years(value: date, years: int) -> date:
        try:
            return value.replace(year=value.year - years)
        except ValueError:
            return value.replace(month=2, day=28, year=value.year - years)

    def _slice_window(self, df: pd.DataFrame, end_dt: date, years: int) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["pe", "pb", "ps"])
        start_dt = self._subtract_years(end_dt, years)
        working = df.copy()
        if "trade_date" not in working.columns:
            return working
        trade_dates = pd.to_datetime(working["trade_date"], format="%Y%m%d", errors="coerce")
        mask = trade_dates.notna() & (trade_dates.dt.date >= start_dt) & (trade_dates.dt.date <= end_dt)
        filtered = working.loc[mask].copy()
        return filtered if not filtered.empty else pd.DataFrame(columns=working.columns)

    def _fetch_sw_daily(self, index_code: str, start_date: date, end_date: date) -> pd.DataFrame:
        start_text = start_date.strftime("%Y%m%d")
        end_text = end_date.strftime("%Y%m%d")
        fields = "ts_code,trade_date,pe,pb,ps,float_mv,total_mv"
        last_exc = None
        for attempt in range(1, self.retry_count + 1):
            try:
                self._sleep_for_rate_limit()
                try:
                    df = self.pro.sw_daily(ts_code=index_code, start_date=start_text, end_date=end_text, fields=fields)
                except TypeError:
                    df = self.pro.sw_daily(ts_code=index_code, start_date=start_text, end_date=end_text)
                self._last_request_ts = time.monotonic()
                break
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._last_request_ts = time.monotonic()
                last_exc = exc
                if (not self._is_rate_limit_error(exc)) or attempt >= self.retry_count:
                    raise
                backoff = self.retry_backoff_seconds * attempt
                if backoff > 0:
                    time.sleep(backoff)
        else:
            if last_exc is not None:
                raise last_exc
            df = None

        if df is None or df.empty:
            return pd.DataFrame(columns=["pe", "pb", "ps"])
        return df.fillna("")

    @staticmethod
    def _parse_trade_date(value: str) -> date:
        text = str(value or "").replace("-", "").strip()
        if len(text) != 8 or not text.isdigit():
            raise ValueError(f"invalid trade_date: {value}")
        return datetime.strptime(text, "%Y%m%d").date()
