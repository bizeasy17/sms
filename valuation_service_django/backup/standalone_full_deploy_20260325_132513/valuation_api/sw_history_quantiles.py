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
    ):
        self.pro = pro
        self.window_years = tuple(sorted({int(y) for y in window_years if int(y) > 0})) or (3, 5, 10)
        self.quantile = float(max(0.05, min(0.95, quantile)))
        self.min_samples = max(20, int(min_samples))

    def build_history_payload(self, index_code: str, end_trade_date: str) -> Dict:
        """Return per-window quantiles and blended anchors for PE/PB/PS."""
        end_dt = self._parse_trade_date(end_trade_date)
        metric_payload = {"pe": {}, "pb": {}, "ps": {}}

        for years in self.window_years:
            start_dt = end_dt.replace(year=end_dt.year - years)
            df = self._fetch_sw_daily(index_code=index_code, start_date=start_dt, end_date=end_dt)
            metric_payload["pe"][f"{years}y"] = self._series_payload(df.get("pe"))
            metric_payload["pb"][f"{years}y"] = self._series_payload(df.get("pb"))
            metric_payload["ps"][f"{years}y"] = self._series_payload(df.get("ps"))

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

    def _fetch_sw_daily(self, index_code: str, start_date: date, end_date: date) -> pd.DataFrame:
        start_text = start_date.strftime("%Y%m%d")
        end_text = end_date.strftime("%Y%m%d")
        fields = "ts_code,trade_date,pe,pb,ps,float_mv,total_mv"
        try:
            df = self.pro.sw_daily(ts_code=index_code, start_date=start_text, end_date=end_text, fields=fields)
        except TypeError:
            df = self.pro.sw_daily(ts_code=index_code, start_date=start_text, end_date=end_text)

        if df is None or df.empty:
            return pd.DataFrame(columns=["pe", "pb", "ps"])
        return df.fillna("")

    @staticmethod
    def _parse_trade_date(value: str) -> date:
        text = str(value or "").replace("-", "").strip()
        if len(text) != 8 or not text.isdigit():
            raise ValueError(f"invalid trade_date: {value}")
        return datetime.strptime(text, "%Y%m%d").date()
