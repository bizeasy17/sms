from __future__ import annotations

import hashlib
import json
import gc
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.metrics import accuracy_score, mean_absolute_error, roc_auc_score
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import create_engine, text


class EarningsForecastPipeline:
    DEFAULT_FINANCIAL_ENDPOINT_TABLES = {
        "income": "earnings_fin_income",
        "balancesheet_vip": "earnings_fin_balancesheet_vip",
        "cashflow_vip": "earnings_fin_cashflow_vip",
        "forecast_vip": "earnings_fin_forecast_vip",
        "express_vip": "earnings_fin_express_vip",
        "dividend": "earnings_fin_dividend",
        "fina_indicator_vip": "earnings_fin_fina_indicator_vip",
        "fina_audit": "earnings_fin_fina_audit",
        "fina_mainbz_vip": "earnings_fin_fina_mainbz_vip",
        "disclosure_date": "earnings_fin_disclosure_date",
    }

    def __init__(self, config_path: str | Path):
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {path}")
        self.config_path = path
        self.config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self._bundle_cache: dict[str, dict[str, Any]] = {}
        self._impute_stats_cache: dict[str, tuple[pd.Series, pd.DataFrame]] = {}
        self._market_frames_cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
        self._financial_cache_by_code: dict[str, dict[str, pd.DataFrame]] = {}
        self._financial_latest_snapshot_cache: dict[str, pd.DataFrame] = {}
        self._industry_mapping_by_code: dict[str, pd.DataFrame] = {}
        self._live_feature_cache: dict[str, pd.DataFrame] = {}
        self._market_regime_cache: dict[str, dict[str, Any]] = {}
        self._market_overall_adjust_cache: dict[str, dict[str, Any]] = {}
        self._engine_cache: dict[str, Any] = {}

    def _get_engine(self, db_url: str):
        url = str(db_url or "").strip()
        if not url:
            raise ValueError("db_url is required")
        cached = self._engine_cache.get(url)
        if cached is not None:
            return cached
        engine = create_engine(url)
        self._engine_cache[url] = engine
        return engine

    @property
    def output_dir(self) -> Path:
        output = self.config.get("output", {})
        out_dir = Path(output.get("dir", "outputs"))
        if not out_dir.is_absolute():
            out_dir = self.config_path.parent.parent / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir

    def _config_hash(self) -> str:
        raw = json.dumps(self.config, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()

    def _resolve_dataset_version(self) -> str:
        output_cfg = self.config.get("output", {})
        version = str(output_cfg.get("dataset_version") or "").strip()
        if version:
            return version
        if bool(output_cfg.get("auto_dataset_version", False)):
            return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return ""

    def _dataset_output_dir(self) -> Path:
        output_cfg = self.config.get("output", {})
        if not bool(output_cfg.get("use_dataset_versioning", False)):
            return self.output_dir
        version = self._resolve_dataset_version()
        if not version:
            return self.output_dir
        root = self.output_dir / str(output_cfg.get("dataset_versions_dir", "datasets"))
        out = root / version
        out.mkdir(parents=True, exist_ok=True)
        return out

    def _write_registry_record(self, record: dict[str, Any]) -> None:
        output_cfg = self.config.get("output", {})
        registry_file = self.output_dir / str(output_cfg.get("model_registry_file", "model_registry.jsonl"))
        registry_file.parent.mkdir(parents=True, exist_ok=True)
        with registry_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _update_serving_pointer(self, candidate: dict[str, Any], promote_to_production: bool = False) -> None:
        output_cfg = self.config.get("output", {})
        pointer_file = self.output_dir / str(output_cfg.get("serving_pointer_file", "serving.yaml"))
        payload = {
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
            "candidate": candidate,
        }
        if pointer_file.exists():
            prev = yaml.safe_load(pointer_file.read_text(encoding="utf-8")) or {}
            if isinstance(prev, dict):
                payload.update(prev)
                payload["candidate"] = candidate
        if promote_to_production:
            payload["production"] = candidate
        pointer_file.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")

    @staticmethod
    def _create_classifier(algo: str, random_state: int):
        name = str(algo or "hgb").strip().lower()
        if name in {"hgb", "histgb", "hist_gradient_boosting"}:
            return HistGradientBoostingClassifier(random_state=random_state)
        if name in {"rf", "random_forest", "randomforest"}:
            return RandomForestClassifier(n_estimators=400, random_state=random_state, n_jobs=-1)
        raise ValueError(f"Unsupported classifier algorithm: {algo}")

    @staticmethod
    def _create_regressor(algo: str, random_state: int):
        name = str(algo or "hgb").strip().lower()
        if name in {"hgb", "histgb", "hist_gradient_boosting"}:
            return HistGradientBoostingRegressor(random_state=random_state)
        if name in {"rf", "random_forest", "randomforest"}:
            return RandomForestRegressor(n_estimators=400, random_state=random_state, n_jobs=-1)
        raise ValueError(f"Unsupported regressor algorithm: {algo}")

    @staticmethod
    def _clip01(value: float) -> float:
        return float(max(0.0, min(1.0, value)))

    @staticmethod
    def _to_float_or_none(value: Any) -> float | None:
        if value is None:
            return None
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        if np.isnan(out) or np.isinf(out):
            return None
        return out

    @staticmethod
    def _digits8(value: Any) -> str:
        raw = "".join(ch for ch in str(value or "") if ch.isdigit())
        if len(raw) >= 8:
            return raw[:8]
        return ""

    @classmethod
    def _report_type_from_end_date(cls, end_date: Any) -> str:
        d = cls._digits8(end_date)
        md = d[4:8] if len(d) == 8 else ""
        if md == "0331":
            return "Q1"
        if md == "0630":
            return "H1"
        if md == "0930":
            return "Q3"
        if md == "1231":
            return "FY"
        return "OTHER"

    @classmethod
    def _endpoint_has_period_row(
        cls,
        frame: pd.DataFrame | None,
        report_type: str,
        end_date: str,
    ) -> bool:
        if frame is None or frame.empty:
            return False

        target_rt = str(report_type or "").strip().upper()
        target_end = cls._digits8(end_date)

        for row in frame.to_dict(orient="records"):
            row_end = ""
            for key in ("end_date", "report_date", "period"):
                row_end = cls._digits8(row.get(key))
                if row_end:
                    break
            if not row_end:
                continue
            if target_end and row_end != target_end:
                continue

            row_rt = cls._report_type_from_end_date(row_end)
            if target_rt and row_rt != target_rt:
                continue
            return True
        return False

    def _resolve_report_source_from_raw(self, ts_code: str, report_type: str, end_date: str) -> str:
        code = str(ts_code or "").strip().upper()
        if not code:
            return "unknown"

        try:
            from earnings_forecast.models import get_financial_endpoint_model

            def _endpoint_has_match(endpoint: str) -> bool:
                model = get_financial_endpoint_model(endpoint)
                if model is None:
                    return False
                model_fields = {f.name for f in model._meta.fields}
                query_fields = [f for f in ("end_date", "report_date", "period") if f in model_fields]
                if not query_fields:
                    return False
                frame = pd.DataFrame(model.objects.filter(ts_code=code).values(*query_fields))
                return self._endpoint_has_period_row(frame, report_type=report_type, end_date=end_date)

            audited_endpoints = ["income", "fina_indicator_vip", "balancesheet_vip", "cashflow_vip"]
            for endpoint in audited_endpoints:
                if _endpoint_has_match(endpoint):
                    return "audited"
            if _endpoint_has_match("express_vip"):
                return "express"
            if _endpoint_has_match("forecast_vip"):
                return "forecast"
        except Exception:
            return "unknown"

        return "unknown"

    def _build_quantitative_target(
        self,
        score: float,
        current_price: float | None,
        current_market_cap: float | None,
        valuation_up_prob: float | None = None,
        earnings_growth: float | None = None,
        industry_rank: float | None = None,
        risk_level: str = "MEDIUM",
        realized_volatility: float | None = None,
        market_regime: str = "BALANCE",
        asof_trade_date: Any | None = None,
    ) -> dict[str, float | None]:
        cfg = self.config.get("valuation_mapping") or {}
        regime_cfg = cfg.get("market_regime") or {}
        regime_profiles = regime_cfg.get("profiles") or {}
        regime_key = str(market_regime or "BALANCE").strip().upper()
        regime_profile = regime_profiles.get(regime_key.lower()) or regime_profiles.get(regime_key) or {}

        max_abs_return = float(cfg.get("quant_target_max_abs_return", 0.30))
        max_abs_return *= float(regime_profile.get("return_scale", 1.0))
        if max_abs_return <= 0:
            max_abs_return = 0.30

        tail_cfg = cfg.get("bull_tail") or {}
        tail_applied = False
        tail_reason = ""
        if bool(tail_cfg.get("enabled", False)):
            allowed_regimes = tail_cfg.get("allowed_regimes") or ["BULL", "BALANCE"]
            allowed_set = {str(item).strip().upper() for item in allowed_regimes if str(item).strip()}
            min_score = float(tail_cfg.get("min_score", 95.0))
            min_prob = float(tail_cfg.get("min_prob", 0.90))
            min_earnings_growth = float(tail_cfg.get("min_earnings_growth", 0.80))
            max_risk_levels = tail_cfg.get("max_risk_levels") or ["LOW", "MEDIUM"]
            risk_allow_set = {str(item).strip().upper() for item in max_risk_levels if str(item).strip()}
            tail_cap = float(tail_cfg.get("max_abs_return", max_abs_return))
            tail_cap = max(tail_cap, max_abs_return)

            prob_tail = 0.5 if valuation_up_prob is None else self._clip01(float(valuation_up_prob))
            earn_tail = None if earnings_growth is None else float(earnings_growth)
            risk_key = str(risk_level or "MEDIUM").upper()

            if regime_key in allowed_set and float(score) >= min_score:
                if prob_tail >= min_prob and (earn_tail is not None and earn_tail >= min_earnings_growth):
                    if risk_key in risk_allow_set:
                        max_abs_return = tail_cap
                        tail_applied = True
                        tail_reason = "high_confidence_growth"

        prob_coef = float(cfg.get("quant_target_prob_coef", 0.10))
        earn_coef = float(cfg.get("quant_target_earnings_coef", 0.12))
        industry_coef = float(cfg.get("quant_target_industry_coef", 0.06))
        earnings_clip = float(cfg.get("quant_target_earnings_clip", 0.40))
        if earnings_clip <= 0:
            earnings_clip = 0.40

        # Map 0-100 signal score to a bounded return target around 50 neutral.
        base_return = ((float(score) - 50.0) / 50.0) * max_abs_return

        prob = 0.5 if valuation_up_prob is None else self._clip01(float(valuation_up_prob))
        prob_return = ((prob - 0.5) * 2.0) * prob_coef

        earn_return = 0.0
        if earnings_growth is not None:
            eg = max(-earnings_clip, min(earnings_clip, float(earnings_growth)))
            earn_return = (eg / earnings_clip) * earn_coef

        ind_return = 0.0
        if industry_rank is not None:
            ir = self._clip01(float(industry_rank))
            # Lower percentile means relatively cheaper inside industry -> slightly higher upside allowance.
            ind_return = ((0.5 - ir) * 2.0) * industry_coef

        risk_scales = cfg.get("quant_target_risk_scales") or {"LOW": 1.10, "MEDIUM": 1.00, "HIGH": 0.80}
        profile_risk_scales = regime_profile.get("risk_scales") or {}
        if isinstance(profile_risk_scales, dict) and profile_risk_scales:
            merged = dict(risk_scales)
            merged.update(profile_risk_scales)
            risk_scales = merged
        risk_scale = float(risk_scales.get(str(risk_level or "MEDIUM").upper(), 1.0))

        implied_return = (base_return + prob_return + earn_return + ind_return) * risk_scale
        implied_return = max(-max_abs_return, min(max_abs_return, implied_return))

        base_band = float(cfg.get("quant_target_base_band", 0.04))
        base_band *= float(regime_profile.get("band_scale", 1.0))
        vol_mult = float(cfg.get("quant_target_volatility_mult", 1.50))
        vol = max(0.0, min(0.25, float(realized_volatility or 0.0)))
        risk_pad = {"LOW": 0.00, "MEDIUM": 0.015, "HIGH": 0.03}.get(str(risk_level or "MEDIUM").upper(), 0.015)
        return_band = base_band + vol * vol_mult + risk_pad
        return_band = max(0.02, min(max_abs_return * 0.80, return_band))

        implied_low = max(-max_abs_return, min(max_abs_return, implied_return - return_band))
        implied_high = max(-max_abs_return, min(max_abs_return, implied_return + return_band))

        market_overall_adjustment = self._compute_market_overall_adjustment(asof_trade_date=asof_trade_date)
        market_multiplier = self._to_float_or_none(market_overall_adjustment.get("multiplier"))
        if market_multiplier is None or market_multiplier <= 0:
            market_multiplier = 1.0

        implied_return = max(
            -max_abs_return,
            min(max_abs_return, (1.0 + implied_return) * market_multiplier - 1.0),
        )
        implied_low = max(
            -max_abs_return,
            min(max_abs_return, (1.0 + implied_low) * market_multiplier - 1.0),
        )
        implied_high = max(
            -max_abs_return,
            min(max_abs_return, (1.0 + implied_high) * market_multiplier - 1.0),
        )

        target_price = None
        target_price_low = None
        target_price_high = None
        if current_price is not None and current_price > 0:
            target_price = current_price * (1.0 + implied_return)
            target_price_low = current_price * (1.0 + implied_low)
            target_price_high = current_price * (1.0 + implied_high)

        target_market_cap = None
        target_market_cap_low = None
        target_market_cap_high = None
        if current_market_cap is not None and current_market_cap > 0:
            target_market_cap = current_market_cap * (1.0 + implied_return)
            target_market_cap_low = current_market_cap * (1.0 + implied_low)
            target_market_cap_high = current_market_cap * (1.0 + implied_high)

        return {
            "target_return_pct": round(100.0 * implied_return, 4),
            "target_return_low_pct": round(100.0 * implied_low, 4),
            "target_return_high_pct": round(100.0 * implied_high, 4),
            "target_price": None if target_price is None else round(float(target_price), 4),
            "target_price_low": None if target_price_low is None else round(float(target_price_low), 4),
            "target_price_high": None if target_price_high is None else round(float(target_price_high), 4),
            "target_market_cap": None if target_market_cap is None else round(float(target_market_cap), 4),
            "target_market_cap_low": None if target_market_cap_low is None else round(float(target_market_cap_low), 4),
            "target_market_cap_high": None if target_market_cap_high is None else round(float(target_market_cap_high), 4),
            "components": {
                "base_return_pct": round(100.0 * base_return, 4),
                "prob_return_pct": round(100.0 * prob_return, 4),
                "earnings_return_pct": round(100.0 * earn_return, 4),
                "industry_return_pct": round(100.0 * ind_return, 4),
                "risk_scale": round(risk_scale, 4),
                "volatility": round(vol, 6),
                "market_regime": regime_key,
                "regime_return_scale": round(float(regime_profile.get("return_scale", 1.0)), 4),
                "regime_band_scale": round(float(regime_profile.get("band_scale", 1.0)), 4),
                "bull_tail_applied": tail_applied,
                "bull_tail_reason": tail_reason,
                "max_abs_return_cap_pct": round(100.0 * max_abs_return, 4),
                "market_overall_adjustment": {
                    "enabled": bool(market_overall_adjustment.get("enabled", False)),
                    "state": str(market_overall_adjustment.get("state") or "neutral"),
                    "score": market_overall_adjustment.get("score"),
                    "multiplier": round(float(market_multiplier), 6),
                    "source": market_overall_adjustment.get("source"),
                    "index_count": market_overall_adjustment.get("index_count"),
                    "asof_trade_date": market_overall_adjustment.get("asof_trade_date"),
                },
            },
        }

    def _detect_market_regime(self, asof_trade_date: Any | None = None) -> dict[str, Any]:
        cfg = (self.config.get("valuation_mapping") or {}).get("market_regime") or {}
        if not bool(cfg.get("enabled", True)):
            return {"regime": "BALANCE", "source": "disabled"}

        asof_key = ""
        asof_ts = pd.to_datetime(asof_trade_date, errors="coerce") if asof_trade_date is not None else None
        if pd.notna(asof_ts):
            asof_key = str(asof_ts.date())
        cache_key = asof_key or "latest"
        cached = self._market_regime_cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        benchmark_code = str(cfg.get("benchmark_ts_code") or "000001.SH").strip().upper()
        try:
            trading, _ = self._load_market_frames_for_ts_code(benchmark_code)
        except Exception:
            trading = pd.DataFrame()

        regime_source = "local_mirror"
        if trading is None or trading.empty or "trade_date" not in trading.columns or "close" not in trading.columns:
            if bool(cfg.get("use_tushare_fallback", True)):
                trading, fallback_source = self._load_index_trading_from_tushare(
                    ts_code=benchmark_code,
                    asof_trade_date=asof_trade_date,
                    lookback_days=int(cfg.get("fallback_lookback_days", 360)),
                    asset=str(cfg.get("benchmark_asset") or "I"),
                )
                regime_source = fallback_source
            if trading is None or trading.empty or "trade_date" not in trading.columns or "close" not in trading.columns:
                result = {"regime": "BALANCE", "source": regime_source, "benchmark_ts_code": benchmark_code}
                self._market_regime_cache[cache_key] = dict(result)
                return result

        frame = trading[["trade_date", "close"]].copy()
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna(subset=["trade_date", "close"]).sort_values("trade_date")

        asof = pd.to_datetime(asof_trade_date, errors="coerce") if asof_trade_date is not None else None
        if pd.notna(asof):
            frame = frame[frame["trade_date"] <= asof]
        if len(frame) < 80:
            result = {
                "regime": "BALANCE",
                "source": "insufficient_history",
                "benchmark_ts_code": benchmark_code,
                "rows": int(len(frame)),
            }
            self._market_regime_cache[cache_key] = dict(result)
            return result

        close = frame["close"]
        ma20 = float(close.rolling(20).mean().iloc[-1])
        ma60 = float(close.rolling(60).mean().iloc[-1])
        close_last = float(close.iloc[-1])
        ret = close.pct_change()
        vol20 = float(ret.tail(20).std()) if len(ret) >= 20 else 0.0
        peak60 = float(close.tail(60).max()) if len(close) >= 60 else close_last
        drawdown60 = (close_last / peak60 - 1.0) if peak60 > 0 else 0.0
        ma_ratio = (close_last / ma60) if ma60 and ma60 > 0 else 1.0

        bull_ratio_min = float(cfg.get("bull_ma_ratio_min", 1.03))
        bear_ratio_max = float(cfg.get("bear_ma_ratio_max", 0.97))
        bear_drawdown_max = float(cfg.get("bear_drawdown_max", -0.12))
        high_vol_threshold = float(cfg.get("high_vol_threshold", 0.028))

        if ma20 > ma60 and ma_ratio >= bull_ratio_min and drawdown60 > bear_drawdown_max:
            regime = "BULL"
        elif ma20 < ma60 and (ma_ratio <= bear_ratio_max or drawdown60 <= bear_drawdown_max):
            regime = "BEAR"
        else:
            regime = "BALANCE"

        # High volatility downgrades bullish regime to balance to avoid over-aggressive targets.
        if regime == "BULL" and vol20 >= high_vol_threshold:
            regime = "BALANCE"

        result = {
            "regime": regime,
            "source": f"rule_v1:{regime_source}",
            "benchmark_ts_code": benchmark_code,
            "asof_trade_date": str(frame["trade_date"].iloc[-1].date()),
            "ma20": round(ma20, 6),
            "ma60": round(ma60, 6),
            "ma_ratio": round(ma_ratio, 6),
            "drawdown60": round(drawdown60, 6),
            "volatility20": round(vol20, 6),
        }
        self._market_regime_cache[cache_key] = dict(result)
        return result

    @staticmethod
    def _percentile_rank(values: list[float], value: float) -> float | None:
        if not values:
            return None
        total = len(values)
        if total <= 0:
            return None
        le_count = sum(1 for item in values if item <= value)
        return float(le_count) / float(total)

    def _load_index_dailybasic_from_tushare(
        self,
        ts_code: str,
        *,
        start_date: str,
        end_date: str,
    ) -> tuple[pd.DataFrame, str]:
        try:
            import tushare as ts  # type: ignore
        except Exception:
            return pd.DataFrame(), "no_tushare"

        token = (
            str(os.getenv("TUSHARE_TOKEN") or "").strip()
            or str((self.config.get("data") or {}).get("tushare_token") or "").strip()
        )
        if not token:
            return pd.DataFrame(), "no_token"

        try:
            ts.set_token(token)
            pro = ts.pro_api()
            frame = pro.index_dailybasic(
                ts_code=str(ts_code or "").strip().upper(),
                start_date=start_date,
                end_date=end_date,
                fields="ts_code,trade_date,pe_ttm,pb,turnover_rate_f",
            )
        except Exception:
            return pd.DataFrame(), "tushare_error"

        if frame is None or frame.empty:
            return pd.DataFrame(), "tushare_empty"

        required_cols = {"trade_date", "pe_ttm", "pb", "turnover_rate_f"}
        if not required_cols.issubset(set(frame.columns)):
            return pd.DataFrame(), "tushare_bad_schema"

        out = frame[["trade_date", "pe_ttm", "pb", "turnover_rate_f"]].copy()
        out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce")
        out["pe_ttm"] = pd.to_numeric(out["pe_ttm"], errors="coerce")
        out["pb"] = pd.to_numeric(out["pb"], errors="coerce")
        out["turnover_rate_f"] = pd.to_numeric(out["turnover_rate_f"], errors="coerce")
        out = out.dropna(subset=["trade_date"]).sort_values("trade_date")
        return out, "tushare_index_dailybasic"

    def _score_index_dailybasic_frame(
        self,
        frame: pd.DataFrame,
        *,
        asof_trade_date: Any | None,
        metric_weights: dict[str, float],
    ) -> float | None:
        if frame is None or frame.empty:
            return None

        local = frame.copy()
        asof_ts = pd.to_datetime(asof_trade_date, errors="coerce") if asof_trade_date is not None else None
        if pd.notna(asof_ts):
            local = local[local["trade_date"] <= asof_ts]
        if local.empty:
            return None

        local = local.sort_values("trade_date")
        latest_row = local.iloc[-1]

        weighted_score = 0.0
        weight_sum = 0.0
        for metric, metric_weight in metric_weights.items():
            latest_value = self._to_float_or_none(latest_row.get(metric))
            if latest_value is None or latest_value <= 0:
                continue
            series = pd.to_numeric(local.get(metric), errors="coerce")
            series = series.replace([np.inf, -np.inf], np.nan).dropna()
            series = series[series > 0]
            values = [float(x) for x in series.tolist()]
            percentile = self._percentile_rank(values, float(latest_value))
            if percentile is None:
                continue
            weighted_score += float(metric_weight) * float(percentile)
            weight_sum += float(metric_weight)

        if weight_sum <= 0:
            return None
        return weighted_score / weight_sum

    def _compute_market_overall_adjustment(self, asof_trade_date: Any | None = None) -> dict[str, Any]:
        cfg = (self.config.get("valuation_mapping") or {}).get("market_overall_adjustment") or {}
        if not bool(cfg.get("enabled", True)):
            return {
                "enabled": False,
                "state": "neutral",
                "score": 0.5,
                "multiplier": 1.0,
                "source": "disabled",
            }

        asof_ts = pd.to_datetime(asof_trade_date, errors="coerce") if asof_trade_date is not None else None
        if pd.isna(asof_ts):
            asof_ts = pd.Timestamp.now().normalize()
        cache_key = str(asof_ts.date())
        cached = self._market_overall_adjust_cache.get(cache_key)
        if cached is not None:
            return dict(cached)

        lookback_years = max(1, int(cfg.get("lookback_years", 5) or 5))
        overvalued_threshold = float(cfg.get("overvalued_threshold", 0.8))
        undervalued_threshold = float(cfg.get("undervalued_threshold", 0.2))
        multiplier_overvalued = float(cfg.get("multiplier_overvalued", 0.95))
        multiplier_neutral = float(cfg.get("multiplier_neutral", 1.0))
        multiplier_undervalued = float(cfg.get("multiplier_undervalued", 1.05))
        index_weights_raw = cfg.get("index_weights") or {
            "000001.SH": 0.30,
            "399001.SZ": 0.30,
            "000300.SH": 0.20,
            "000905.SH": 0.15,
            "399006.SZ": 0.05,
        }
        metric_weights_raw = cfg.get("metric_weights") or {
            "pe_ttm": 0.45,
            "pb": 0.40,
            "turnover_rate_f": 0.15,
        }

        index_weights = {
            str(k).strip().upper(): float(v)
            for k, v in index_weights_raw.items()
            if str(k).strip()
        }
        metric_weights = {
            str(k).strip(): float(v)
            for k, v in metric_weights_raw.items()
            if str(k).strip()
        }

        end_date = asof_ts.strftime("%Y%m%d")
        start_date = (asof_ts - pd.Timedelta(days=lookback_years * 370)).strftime("%Y%m%d")

        weighted_score = 0.0
        weight_sum = 0.0
        used_index_count = 0
        source_used = "tushare_index_dailybasic"

        for ts_code, idx_weight in index_weights.items():
            if idx_weight <= 0:
                continue
            frame, source = self._load_index_dailybasic_from_tushare(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )
            if source != "tushare_index_dailybasic":
                source_used = source
            idx_score = self._score_index_dailybasic_frame(
                frame,
                asof_trade_date=asof_ts,
                metric_weights=metric_weights,
            )
            if idx_score is None:
                continue
            weighted_score += float(idx_weight) * float(idx_score)
            weight_sum += float(idx_weight)
            used_index_count += 1

        if weight_sum <= 0:
            result = {
                "enabled": True,
                "state": "neutral",
                "score": 0.5,
                "multiplier": multiplier_neutral,
                "source": source_used or "no_data",
                "reason": "no_index_data",
                "index_count": 0,
                "asof_trade_date": str(asof_ts.date()),
            }
            self._market_overall_adjust_cache[cache_key] = dict(result)
            return result

        score = weighted_score / weight_sum
        if score >= overvalued_threshold:
            state = "overvalued"
            multiplier = multiplier_overvalued
        elif score <= undervalued_threshold:
            state = "undervalued"
            multiplier = multiplier_undervalued
        else:
            state = "neutral"
            multiplier = multiplier_neutral

        result = {
            "enabled": True,
            "state": state,
            "score": round(float(score), 6),
            "multiplier": float(multiplier),
            "source": source_used,
            "index_count": used_index_count,
            "asof_trade_date": str(asof_ts.date()),
        }
        self._market_overall_adjust_cache[cache_key] = dict(result)
        return result

    def detect_market_regime(self, asof_trade_date: Any | None = None) -> dict[str, Any]:
        """Public wrapper for market regime detection used by orchestration commands."""
        return self._detect_market_regime(asof_trade_date=asof_trade_date)

    def _load_index_trading_from_tushare(
        self,
        ts_code: str,
        asof_trade_date: Any | None,
        lookback_days: int,
        asset: str = "I",
    ) -> tuple[pd.DataFrame, str]:
        try:
            import tushare as ts  # type: ignore
        except Exception:
            return pd.DataFrame(), "no_tushare"

        token = (
            str(os.getenv("TUSHARE_TOKEN") or "").strip()
            or str((self.config.get("data") or {}).get("tushare_token") or "").strip()
        )
        if not token:
            return pd.DataFrame(), "no_token"

        try:
            ts.set_token(token)
            end_ts = pd.to_datetime(asof_trade_date, errors="coerce")
            if pd.isna(end_ts):
                end_ts = pd.Timestamp.now().normalize()
            lookback = max(120, int(lookback_days))
            start_ts = end_ts - pd.Timedelta(days=lookback)

            frame = ts.pro_bar(
                ts_code=str(ts_code).strip().upper(),
                asset=str(asset or "I").strip().upper(),
                start_date=start_ts.strftime("%Y%m%d"),
                end_date=end_ts.strftime("%Y%m%d"),
                freq="D",
            )
            if frame is None or frame.empty:
                return pd.DataFrame(), "tushare_empty"
            if "trade_date" not in frame.columns or "close" not in frame.columns:
                return pd.DataFrame(), "tushare_bad_schema"

            out = frame[["trade_date", "close"]].copy()
            out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce")
            out["close"] = pd.to_numeric(out["close"], errors="coerce")
            out = out.dropna(subset=["trade_date", "close"]).sort_values("trade_date")
            return out, "tushare_pro_bar"
        except Exception:
            return pd.DataFrame(), "tushare_error"

    def _valuation_mapping(self, valuation_up_prob: float, earnings_growth: float | None) -> dict[str, Any]:
        cfg = self._valuation_mapping_config()
        prob = self._clip01(float(valuation_up_prob))

        # Map earnings growth into [0, 1] by a capped linear scale.
        e_min = float(cfg.get("earnings_growth_min", -0.3))
        e_max = float(cfg.get("earnings_growth_max", 0.3))
        if e_max <= e_min:
            e_max = e_min + 1e-6

        if earnings_growth is None or (isinstance(earnings_growth, float) and np.isnan(earnings_growth)):
            earn_norm = 0.5
            earn_available = False
        else:
            e = float(earnings_growth)
            e = max(e_min, min(e_max, e))
            earn_norm = (e - e_min) / (e_max - e_min)
            earn_available = True

        w_prob = float(cfg.get("weight_prob", 0.7))
        w_earn = float(cfg.get("weight_earnings", 0.3))
        w_sum = w_prob + w_earn
        if w_sum <= 0:
            w_prob, w_earn, w_sum = 0.7, 0.3, 1.0
        w_prob /= w_sum
        w_earn /= w_sum

        composite = w_prob * prob + w_earn * earn_norm
        score = round(100.0 * composite, 2)
        picked = self._pick_valuation_band(score)

        return {
            "score": score,
            "stance": str(picked.get("stance") or "HOLD"),
            "confidence": str(picked.get("confidence") or "MEDIUM"),
            "prob_up": round(prob, 6),
            "pred_earnings_growth": None if not earn_available else round(float(earnings_growth), 6),
            "prob_component": round(100.0 * w_prob * prob, 2),
            "earnings_component": round(100.0 * w_earn * earn_norm, 2),
            "rules_version": str(cfg.get("rules_version", "v1")),
        }

    def _pick_valuation_band(self, score: float) -> dict[str, Any]:
        cfg = self._valuation_mapping_config()
        bands = cfg.get("score_bands") or [
            {"min": 70, "stance": "STRONG_BUY", "confidence": "HIGH"},
            {"min": 60, "stance": "BUY", "confidence": "MEDIUM"},
            {"min": 45, "stance": "HOLD", "confidence": "MEDIUM"},
            {"min": 30, "stance": "REDUCE", "confidence": "LOW"},
            {"min": 0, "stance": "SELL", "confidence": "LOW"},
        ]
        bands = sorted(bands, key=lambda x: float(x.get("min", 0)), reverse=True)
        picked = bands[-1]
        for item in bands:
            if float(score) >= float(item.get("min", 0)):
                picked = item
                break
        return picked

    @staticmethod
    def _risk_level_to_code(level: str | None) -> int:
        key = str(level or "MEDIUM").strip().upper()
        return {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(key, 1)

    @staticmethod
    def _risk_code_to_level(code: int) -> str:
        idx = max(0, min(2, int(code)))
        return {0: "LOW", 1: "MEDIUM", 2: "HIGH"}[idx]

    @staticmethod
    def _row_float_value(frame: pd.DataFrame, column: str) -> float | None:
        if column not in frame.columns:
            return None
        try:
            value = frame[column].iloc[0]
        except Exception:
            return None
        return EarningsForecastPipeline._to_float_or_none(value)

    def _risk_level_from_score(self, score: float) -> str:
        s = float(score)
        if s >= 65:
            return "LOW"
        if s >= 50:
            return "MEDIUM"
        return "HIGH"

    def _apply_quality_risk_guard(self, row: pd.DataFrame, base_score: float, base_risk_level: str) -> dict[str, Any]:
        cfg = (self.config.get("valuation_mapping") or {}).get("quality_risk_guard") or {}
        if not bool(cfg.get("enabled", False)):
            return {
                "applied": False,
                "score": round(float(base_score), 2),
                "risk_level": str(base_risk_level or "MEDIUM").upper(),
                "penalty_total": 0.0,
                "reasons": [],
            }

        min_revenue_base = float(cfg.get("min_revenue_base", 1_000_000.0))
        max_score_penalty = max(0.0, float(cfg.get("max_score_penalty", 30.0)))
        max_risk_upgrade = max(0, int(cfg.get("max_risk_upgrade", 2)))

        thresholds = cfg.get("thresholds") or {}
        rules = cfg.get("rules") or {}

        revenue = self._row_float_value(row, "revenue")
        netprofit = self._row_float_value(row, "n_income_attr_p")
        if netprofit is None:
            netprofit = self._row_float_value(row, "n_income")
        ocf_to_or = self._row_float_value(row, "ocf_to_or")
        n_cashflow_act = self._row_float_value(row, "n_cashflow_act")
        accounts_receiv = self._row_float_value(row, "accounts_receiv")
        inventories = self._row_float_value(row, "inventories")

        reasons: list[dict[str, Any]] = []
        penalty_total = 0.0
        risk_upgrade_total = 0

        def _hit(rule_key: str, metric_value: float | None, extra: dict[str, Any] | None = None):
            nonlocal penalty_total, risk_upgrade_total
            rule_cfg = rules.get(rule_key) or {}
            penalty = max(0.0, float(rule_cfg.get("score_penalty", 0.0)))
            risk_up = max(0, int(rule_cfg.get("risk_upgrade", 0)))
            penalty_total += penalty
            risk_upgrade_total += risk_up
            payload = {
                "rule": rule_key,
                "score_penalty": penalty,
                "risk_upgrade": risk_up,
                "metric_value": metric_value,
            }
            if isinstance(extra, dict):
                payload.update(extra)
            reasons.append(payload)

        min_ocf_to_or = float(thresholds.get("min_ocf_to_or", 0.0))
        if ocf_to_or is not None and ocf_to_or < min_ocf_to_or:
            _hit("ocf_to_or_low", ocf_to_or, {"threshold": min_ocf_to_or})

        min_positive_profit = float(thresholds.get("min_positive_profit", 0.0))
        max_negative_operating_cashflow = float(thresholds.get("max_negative_operating_cashflow", 0.0))
        if (
            netprofit is not None
            and netprofit > min_positive_profit
            and n_cashflow_act is not None
            and n_cashflow_act <= max_negative_operating_cashflow
        ):
            _hit(
                "profit_cashflow_mismatch",
                n_cashflow_act,
                {
                    "netprofit": netprofit,
                    "netprofit_threshold": min_positive_profit,
                    "cashflow_threshold": max_negative_operating_cashflow,
                },
            )

        max_receiv_to_revenue = float(thresholds.get("max_receiv_to_revenue", 0.45))
        if (
            revenue is not None
            and revenue >= min_revenue_base
            and accounts_receiv is not None
        ):
            recv_ratio = accounts_receiv / max(abs(revenue), 1e-6)
            if recv_ratio > max_receiv_to_revenue:
                _hit(
                    "receivables_ratio_high",
                    recv_ratio,
                    {"threshold": max_receiv_to_revenue, "revenue": revenue},
                )

        max_inventory_to_revenue = float(thresholds.get("max_inventory_to_revenue", 0.60))
        if (
            revenue is not None
            and revenue >= min_revenue_base
            and inventories is not None
        ):
            inv_ratio = inventories / max(abs(revenue), 1e-6)
            if inv_ratio > max_inventory_to_revenue:
                _hit(
                    "inventory_ratio_high",
                    inv_ratio,
                    {"threshold": max_inventory_to_revenue, "revenue": revenue},
                )

        if not reasons:
            return {
                "applied": False,
                "score": round(float(base_score), 2),
                "risk_level": str(base_risk_level or "MEDIUM").upper(),
                "penalty_total": 0.0,
                "reasons": [],
            }

        penalty_total = min(max_score_penalty, penalty_total)
        risk_upgrade_total = min(max_risk_upgrade, risk_upgrade_total)

        adjusted_score = max(0.0, float(base_score) - penalty_total)
        risk_from_score = self._risk_level_from_score(adjusted_score)
        upgraded_risk_code = min(
            2,
            self._risk_level_to_code(base_risk_level) + risk_upgrade_total,
        )
        upgraded_risk_level = self._risk_code_to_level(upgraded_risk_code)
        final_risk_level = self._risk_code_to_level(
            max(self._risk_level_to_code(risk_from_score), self._risk_level_to_code(upgraded_risk_level))
        )

        return {
            "applied": True,
            "score": round(adjusted_score, 2),
            "risk_level": final_risk_level,
            "penalty_total": round(penalty_total, 4),
            "reasons": reasons,
        }

    def _valuation_mapping_config(self) -> dict[str, Any]:
        default_cfg = {
            "rules_version": "v1",
            "weight_prob": 0.7,
            "weight_earnings": 0.3,
            "earnings_growth_min": -0.3,
            "earnings_growth_max": 0.3,
            "score_bands": [
                {"min": 70, "stance": "STRONG_BUY", "confidence": "HIGH"},
                {"min": 60, "stance": "BUY", "confidence": "MEDIUM"},
                {"min": 45, "stance": "HOLD", "confidence": "MEDIUM"},
                {"min": 30, "stance": "REDUCE", "confidence": "LOW"},
                {"min": 0, "stance": "SELL", "confidence": "LOW"},
            ],
        }
        custom_cfg = self.config.get("valuation_mapping") or {}
        out = dict(default_cfg)
        out.update({k: v for k, v in custom_cfg.items() if k != "score_bands"})
        if isinstance(custom_cfg.get("score_bands"), list) and custom_cfg.get("score_bands"):
            out["score_bands"] = custom_cfg["score_bands"]
        return out

    def _build_run_id(self, classifier_algo: str, regressor_algo: str, train_rows: int, test_rows: int) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        raw = f"{classifier_algo}|{regressor_algo}|{train_rows}|{test_rows}|{self.config_path}"
        short = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:8]
        return f"{ts}_{classifier_algo}_{regressor_algo}_{short}"

    @staticmethod
    def _prepare_log(message: str) -> None:
        print(f"[prepare] {message}", flush=True)

    @staticmethod
    def _forward_rolling_min(series: pd.Series, window: int, min_periods: int) -> pd.Series:
        values = pd.to_numeric(series, errors="coerce")
        return values.iloc[::-1].rolling(window=window, min_periods=min_periods).min().iloc[::-1]

    @staticmethod
    def _forward_close_volatility(series: pd.Series, window: int, min_periods: int) -> pd.Series:
        values = pd.to_numeric(series, errors="coerce").replace(0, np.nan)
        returns = values.pct_change()
        return returns.iloc[::-1].rolling(window=window, min_periods=min_periods).std().iloc[::-1]

    @staticmethod
    def _sample_panel_snapshot(snapshot: pd.DataFrame, sample_cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        cfg = sample_cfg or {}
        if not bool(cfg.get("enabled", False)):
            return snapshot
        if snapshot is None or snapshot.empty:
            return snapshot
        if not {"ts_code", "ann_date", "report_type"}.issubset(set(snapshot.columns)):
            return snapshot

        out = snapshot.copy()
        out["ann_date"] = pd.to_datetime(out["ann_date"], errors="coerce")
        out = out.dropna(subset=["ann_date"])
        out["report_type"] = out["report_type"].fillna("UNKNOWN").astype(str).str.upper()

        configured_types = cfg.get("report_types") or ["Q1", "H1", "Q3", "FY"]
        allowed = {str(x).strip().upper() for x in configured_types if str(x).strip()}
        if allowed:
            out = out[out["report_type"].isin(allowed)]

        # Keep only recent-N-year reports per symbol to cap asof-join memory.
        recent_years = int(cfg.get("recent_years_per_symbol", 5))
        if recent_years > 0 and not out.empty:
            max_ann = out.groupby("ts_code")["ann_date"].transform("max")
            cutoff = max_ann - pd.to_timedelta(recent_years * 365, unit="D")
            out = out[out["ann_date"] >= cutoff]

        max_rows = int(cfg.get("max_rows_per_report_type", 100000))
        if max_rows > 0 and not out.empty:
            out = out.sort_values(["report_type", "ann_date"], ascending=[True, False])
            out = out.groupby("report_type", group_keys=False).head(max_rows)

        return out

    def _load_market_frames(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        data = self.config.get("data", {})
        engine = self._get_engine(data["db_url"])
        trading = pd.read_sql_table(data.get("trading_table", "stockdata_stocktradinghistory"), engine)
        fundamental = pd.read_sql_table(data.get("fundamental_table", "stockdata_stockfundamentalhistory"), engine)

        for frame in (trading, fundamental):
            frame["trade_date"] = pd.to_datetime(frame["trade_date"])

        freq = str(data.get("freq", "D")).upper()
        if "freq" in trading.columns:
            trading = trading[trading["freq"].astype(str).str.upper() == freq]
        if "freq" in fundamental.columns:
            fundamental = fundamental[fundamental["freq"].astype(str).str.upper() == freq]

        start_date = data.get("start_date")
        end_date = data.get("end_date")
        if start_date:
            start = pd.Timestamp(start_date)
            trading = trading[trading["trade_date"] >= start]
            fundamental = fundamental[fundamental["trade_date"] >= start]
        if end_date:
            end = pd.Timestamp(end_date)
            trading = trading[trading["trade_date"] <= end]
            fundamental = fundamental[fundamental["trade_date"] <= end]

        prefixes = data.get("scope_prefixes") or []
        if prefixes:
            prefixes = tuple(str(x) for x in prefixes)
            trading = trading[trading["ts_code"].astype(str).str.startswith(prefixes)]
            fundamental = fundamental[fundamental["ts_code"].astype(str).str.startswith(prefixes)]

        return trading, fundamental

    def _load_market_frames_for_ts_code(self, ts_code: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        data = self.config.get("data", {})
        code = str(ts_code or "").strip()
        if not code:
            return pd.DataFrame(), pd.DataFrame()

        cached = self._market_frames_cache.get(code)
        if cached is not None:
            trading_cached, fundamental_cached = cached
            return trading_cached.copy(), fundamental_cached.copy()

        engine = self._get_engine(data["db_url"])
        trading_table = str(data.get("trading_table", "stockdata_stocktradinghistory")).strip()
        fundamental_table = str(data.get("fundamental_table", "stockdata_stockfundamentalhistory")).strip()

        trading_query = f"SELECT * FROM {trading_table} WHERE ts_code = :ts_code"
        fundamental_query = f"SELECT * FROM {fundamental_table} WHERE ts_code = :ts_code"

        trading = pd.read_sql_query(text(trading_query), engine, params={"ts_code": code})
        fundamental = pd.read_sql_query(text(fundamental_query), engine, params={"ts_code": code})

        for frame in (trading, fundamental):
            if "trade_date" in frame.columns:
                frame["trade_date"] = pd.to_datetime(frame["trade_date"])

        freq = str(data.get("freq", "D")).upper()
        if "freq" in trading.columns:
            trading = trading[trading["freq"].astype(str).str.upper() == freq]
        if "freq" in fundamental.columns:
            fundamental = fundamental[fundamental["freq"].astype(str).str.upper() == freq]

        start_date = data.get("start_date")
        end_date = data.get("end_date")
        if start_date and "trade_date" in trading.columns:
            start = pd.Timestamp(start_date)
            trading = trading[trading["trade_date"] >= start]
            if "trade_date" in fundamental.columns:
                fundamental = fundamental[fundamental["trade_date"] >= start]
        if end_date and "trade_date" in trading.columns:
            end = pd.Timestamp(end_date)
            trading = trading[trading["trade_date"] <= end]
            if "trade_date" in fundamental.columns:
                fundamental = fundamental[fundamental["trade_date"] <= end]

        self._market_frames_cache[code] = (trading.copy(), fundamental.copy())
        return trading, fundamental

    def _load_financial_from_db(self) -> dict[str, pd.DataFrame]:
        data = self.config.get("data", {})
        feature = self.config.get("feature", {})
        if not bool(feature.get("use_financial_db", True)):
            return {}

        financial_db_url = str(data.get("financial_db_url") or data["db_url"])
        engine = self._get_engine(financial_db_url)
        out: dict[str, list[dict]] = {}
        table_name = str(data.get("financial_table") or "").strip()

        # Backward compatibility for old mixed-table schema.
        if table_name:
            query = f"SELECT endpoint, ts_code, payload FROM {table_name}"
            try:
                frame = pd.read_sql_query(query, engine)
            except SQLAlchemyError:
                frame = pd.DataFrame()

            for row in frame.to_dict(orient="records"):
                endpoint = str(row.get("endpoint") or "").strip()
                ts_code = str(row.get("ts_code") or "").strip()
                payload = row.get("payload")
                if not endpoint or not ts_code:
                    continue

                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except (ValueError, TypeError):
                        payload = {}
                if not isinstance(payload, dict):
                    payload = {}

                payload = dict(payload)
                payload["ts_code"] = ts_code
                out.setdefault(endpoint, []).append(payload)

            if out:
                return {ep: pd.DataFrame(rows) for ep, rows in out.items() if rows}

        endpoint_tables = data.get("financial_endpoint_tables") or self.DEFAULT_FINANCIAL_ENDPOINT_TABLES
        for endpoint, table in endpoint_tables.items():
            ep = str(endpoint or "").strip()
            tb = str(table or "").strip()
            if not ep or not tb:
                continue
            query = f"SELECT ts_code, payload FROM {tb}"
            try:
                frame = pd.read_sql_query(query, engine)
            except SQLAlchemyError:
                continue
            if frame is None or frame.empty:
                continue
            for row in frame.to_dict(orient="records"):
                ts_code = str(row.get("ts_code") or "").strip()
                payload = row.get("payload")
                if not ts_code:
                    continue
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except (ValueError, TypeError):
                        payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                payload = dict(payload)
                payload["ts_code"] = ts_code
                out.setdefault(ep, []).append(payload)

        return {ep: pd.DataFrame(rows) for ep, rows in out.items() if rows}

    def _load_financial_feature_snapshot(self) -> dict[str, pd.DataFrame]:
        data = self.config.get("data", {})
        feature = self.config.get("feature", {})
        if not bool(feature.get("use_financial_feature_snapshot", True)):
            return {}

        table_name = str(data.get("financial_feature_table", "earnings_financial_feature_snapshot")).strip()
        if not table_name:
            return {}

        financial_db_url = str(data.get("financial_db_url") or data["db_url"])
        engine = self._get_engine(financial_db_url)
        query = f"SELECT * FROM {table_name}"
        try:
            frame = pd.read_sql_query(query, engine)
        except SQLAlchemyError:
            return {}

        if frame is None or frame.empty:
            return {}

        return {"snapshot": frame}

    def _load_financial_feature_snapshot_for_ts_code(self, ts_code: str) -> dict[str, pd.DataFrame]:
        data = self.config.get("data", {})
        feature = self.config.get("feature", {})
        if not bool(feature.get("use_financial_feature_snapshot", True)):
            return {}

        code = str(ts_code or "").strip()
        if not code:
            return {}

        table_name = str(data.get("financial_feature_table", "earnings_financial_feature_snapshot")).strip()
        if not table_name:
            return {}

        financial_db_url = str(data.get("financial_db_url") or data["db_url"])
        engine = self._get_engine(financial_db_url)
        query = f"SELECT * FROM {table_name} WHERE ts_code = :ts_code"
        try:
            frame = pd.read_sql_query(text(query), engine, params={"ts_code": code})
        except SQLAlchemyError:
            return {}
        if frame is None or frame.empty:
            return {}
        return {"snapshot": frame}

    def _load_financial_feature_panel_for_ts_code(self, ts_code: str) -> dict[str, pd.DataFrame]:
        """Load per-report-type financial panel rows for a single symbol.

        This is preferred by live predict path because it preserves report_type granularity.
        """
        data = self.config.get("data", {})
        feature = self.config.get("feature", {})
        if not bool(feature.get("use_financial_feature_snapshot", True)):
            return {}

        code = str(ts_code or "").strip()
        if not code:
            return {}

        table_name = str(data.get("financial_feature_panel_table", "earnings_financial_feature_panel")).strip()
        if not table_name:
            return {}

        financial_db_url = str(data.get("financial_db_url") or data["db_url"])
        engine = self._get_engine(financial_db_url)
        query = f"SELECT * FROM {table_name} WHERE ts_code = :ts_code"
        try:
            frame = pd.read_sql_query(text(query), engine, params={"ts_code": code})
        except SQLAlchemyError:
            return {}

        if frame is None or frame.empty:
            return {}

        if "ann_date" in frame.columns:
            frame["ann_date"] = pd.to_datetime(frame["ann_date"], errors="coerce")
        if "end_date" in frame.columns:
            frame["end_date"] = pd.to_datetime(frame["end_date"], errors="coerce")
        if "report_type" in frame.columns:
            frame["report_type"] = frame["report_type"].fillna("UNKNOWN").astype(str).str.upper()

        return {"snapshot": frame}

    def _load_financial_from_db_for_ts_code(self, ts_code: str) -> dict[str, pd.DataFrame]:
        data = self.config.get("data", {})
        feature = self.config.get("feature", {})
        if not bool(feature.get("use_financial_db", True)):
            return {}

        code = str(ts_code or "").strip()
        if not code:
            return {}

        financial_db_url = str(data.get("financial_db_url") or data["db_url"])
        engine = self._get_engine(financial_db_url)
        out: dict[str, list[dict]] = {}
        table_name = str(data.get("financial_table") or "").strip()

        if table_name:
            query = f"SELECT endpoint, ts_code, payload FROM {table_name} WHERE ts_code = :ts_code"
            try:
                frame = pd.read_sql_query(text(query), engine, params={"ts_code": code})
            except SQLAlchemyError:
                frame = pd.DataFrame()

            for row in frame.to_dict(orient="records"):
                endpoint = str(row.get("endpoint") or "").strip()
                payload = row.get("payload")
                if not endpoint:
                    continue
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except (ValueError, TypeError):
                        payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                payload = dict(payload)
                payload["ts_code"] = code
                out.setdefault(endpoint, []).append(payload)

            if out:
                return {ep: pd.DataFrame(rows) for ep, rows in out.items() if rows}

        endpoint_tables = data.get("financial_endpoint_tables") or self.DEFAULT_FINANCIAL_ENDPOINT_TABLES
        for endpoint, table in endpoint_tables.items():
            ep = str(endpoint or "").strip()
            tb = str(table or "").strip()
            if not ep or not tb:
                continue
            query = f"SELECT ts_code, payload FROM {tb} WHERE ts_code = :ts_code"
            try:
                frame = pd.read_sql_query(text(query), engine, params={"ts_code": code})
            except SQLAlchemyError:
                continue
            if frame is None or frame.empty:
                continue
            for row in frame.to_dict(orient="records"):
                payload = row.get("payload")
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except (ValueError, TypeError):
                        payload = {}
                if not isinstance(payload, dict):
                    payload = {}
                payload = dict(payload)
                payload["ts_code"] = code
                out.setdefault(ep, []).append(payload)

        return {ep: pd.DataFrame(rows) for ep, rows in out.items() if rows}

    def _load_industry_mapping(self) -> pd.DataFrame:
        data = self.config.get("data", {})
        map_table = str(data.get("industry_map_table", "stockdata_corporation")).strip()
        dim_table = str(data.get("industry_dim_table", "stockdata_industry")).strip()
        if not map_table:
            return pd.DataFrame(columns=["ts_code", "industry_name"])

        engine = self._get_engine(data["db_url"])
        query = (
            f"SELECT c.ts_code, COALESCE(i.name, 'UNKNOWN') AS industry_name "
            f"FROM {map_table} c LEFT JOIN {dim_table} i ON c.industry_id = i.id"
        )
        try:
            mapping = pd.read_sql_query(query, engine)
        except SQLAlchemyError:
            return pd.DataFrame(columns=["ts_code", "industry_name"])

        if mapping is None or mapping.empty:
            return pd.DataFrame(columns=["ts_code", "industry_name"])

        mapping["ts_code"] = mapping["ts_code"].astype(str)
        mapping["industry_name"] = mapping["industry_name"].fillna("UNKNOWN").astype(str)
        return mapping[["ts_code", "industry_name"]].drop_duplicates("ts_code")

    def _load_industry_mapping_for_ts_code(self, ts_code: str) -> pd.DataFrame:
        data = self.config.get("data", {})
        map_table = str(data.get("industry_map_table", "stockdata_corporation")).strip()
        dim_table = str(data.get("industry_dim_table", "stockdata_industry")).strip()
        code = str(ts_code or "").strip()
        if not map_table or not code:
            return pd.DataFrame(columns=["ts_code", "industry_name"])

        cached = self._industry_mapping_by_code.get(code)
        if cached is not None:
            return cached.copy()

        engine = self._get_engine(data["db_url"])
        query = (
            f"SELECT c.ts_code, COALESCE(i.name, 'UNKNOWN') AS industry_name "
            f"FROM {map_table} c LEFT JOIN {dim_table} i ON c.industry_id = i.id "
            f"WHERE c.ts_code = :ts_code"
        )
        try:
            mapping = pd.read_sql_query(text(query), engine, params={"ts_code": code})
        except SQLAlchemyError:
            return pd.DataFrame(columns=["ts_code", "industry_name"])

        if mapping is None or mapping.empty:
            return pd.DataFrame(columns=["ts_code", "industry_name"])

        mapping["ts_code"] = mapping["ts_code"].astype(str)
        mapping["industry_name"] = mapping["industry_name"].fillna("UNKNOWN").astype(str)
        mapping = mapping[["ts_code", "industry_name"]].drop_duplicates("ts_code")
        self._industry_mapping_by_code[code] = mapping.copy()
        return mapping

    def _load_financial_cache(self) -> dict[str, pd.DataFrame]:
        snap_data = self._load_financial_feature_snapshot()
        if snap_data:
            return snap_data

        db_data = self._load_financial_from_db()
        if db_data:
            return db_data

        data = self.config.get("data", {})
        feature = self.config.get("feature", {})
        if not bool(feature.get("use_financial_cache", True)):
            return {}

        cache_dir = Path(str(data.get("financial_cache_dir") or ""))
        if not cache_dir.exists():
            return {}

        out: dict[str, pd.DataFrame] = {}
        for endpoint_dir in cache_dir.iterdir():
            if not endpoint_dir.is_dir():
                continue
            frames = []
            for fp in endpoint_dir.glob("*.parquet"):
                try:
                    frame = pd.read_parquet(fp)
                    frame["ts_code"] = fp.stem
                    frames.append(frame)
                except (OSError, ValueError, TypeError):
                    continue
            if not frames:
                for fp in endpoint_dir.glob("*.csv"):
                    try:
                        frame = pd.read_csv(fp)
                        frame["ts_code"] = fp.stem
                        frames.append(frame)
                    except (OSError, ValueError, TypeError):
                        continue
            if frames:
                out[endpoint_dir.name] = pd.concat(frames, ignore_index=True)
        return out

    def _load_financial_cache_for_ts_code(self, ts_code: str) -> dict[str, pd.DataFrame]:
        code = str(ts_code or "").strip()
        if not code:
            return {}

        cached = self._financial_cache_by_code.get(code)
        if cached is not None:
            return {key: value.copy() for key, value in cached.items()}

        panel_data = self._load_financial_feature_panel_for_ts_code(code)
        if panel_data:
            self._financial_cache_by_code[code] = {key: value.copy() for key, value in panel_data.items()}
            return {key: value.copy() for key, value in panel_data.items()}

        snap_data = self._load_financial_feature_snapshot_for_ts_code(code)
        if snap_data:
            self._financial_cache_by_code[code] = {key: value.copy() for key, value in snap_data.items()}
            return {key: value.copy() for key, value in snap_data.items()}

        db_data = self._load_financial_from_db_for_ts_code(code)
        if db_data:
            self._financial_cache_by_code[code] = {key: value.copy() for key, value in db_data.items()}
            return {key: value.copy() for key, value in db_data.items()}

        data = self.config.get("data", {})
        feature = self.config.get("feature", {})
        if not bool(feature.get("use_financial_cache", True)):
            return {}

        cache_dir = Path(str(data.get("financial_cache_dir") or ""))
        if not cache_dir.exists():
            return {}

        out: dict[str, pd.DataFrame] = {}
        for endpoint_dir in cache_dir.iterdir():
            if not endpoint_dir.is_dir():
                continue
            frames = []
            pq = endpoint_dir / f"{code}.parquet"
            if pq.exists():
                try:
                    frame = pd.read_parquet(pq)
                    frame["ts_code"] = code
                    frames.append(frame)
                except (OSError, ValueError, TypeError):
                    pass
            csv_fp = endpoint_dir / f"{code}.csv"
            if csv_fp.exists():
                try:
                    frame = pd.read_csv(csv_fp)
                    frame["ts_code"] = code
                    frames.append(frame)
                except (OSError, ValueError, TypeError):
                    pass
            if frames:
                out[endpoint_dir.name] = pd.concat(frames, ignore_index=True)
        self._financial_cache_by_code[code] = {key: value.copy() for key, value in out.items()}
        return {key: value.copy() for key, value in out.items()}

    def _load_financial_latest_snapshot_for_ts_code(
        self,
        ts_code: str,
        asof_date: datetime | pd.Timestamp | str | None = None,
    ) -> pd.DataFrame:
        data = self.config.get("data", {})
        feature = self.config.get("feature", {})
        if not bool(feature.get("use_financial_feature_snapshot", True)):
            return pd.DataFrame()

        code = str(ts_code or "").strip()
        if not code:
            return pd.DataFrame()

        asof_ts = pd.to_datetime(asof_date, errors="coerce") if asof_date is not None else pd.NaT
        asof_text = ""
        if pd.notna(asof_ts):
            asof_text = pd.Timestamp(asof_ts).strftime("%Y%m%d")

        cache_key = code if not asof_text else f"{code}|{asof_text}"
        cached = self._financial_latest_snapshot_cache.get(cache_key)
        if cached is not None:
            return cached.copy()

        table_name = str(data.get("financial_snapshot_table", "earnings_financial_feature_snapshot")).strip()
        if not table_name:
            return pd.DataFrame()

        financial_db_url = str(data.get("financial_db_url") or data["db_url"])
        engine = self._get_engine(financial_db_url)
        if asof_text:
            query = (
                f"SELECT * FROM {table_name} WHERE ts_code = :ts_code "
                f"AND COALESCE(NULLIF(REPLACE(CAST(ann_date AS TEXT), '-', ''), ''), "
                f"NULLIF(REPLACE(CAST(end_date AS TEXT), '-', ''), '')) <= :asof_date "
                f"ORDER BY COALESCE(NULLIF(REPLACE(CAST(ann_date AS TEXT), '-', ''), ''), "
                f"NULLIF(REPLACE(CAST(end_date AS TEXT), '-', ''), '')) DESC LIMIT 1"
            )
        else:
            query = (
                f"SELECT * FROM {table_name} WHERE ts_code = :ts_code "
                f"ORDER BY COALESCE(ann_date, '') DESC, COALESCE(end_date, '') DESC LIMIT 1"
            )
        try:
            params = {"ts_code": code}
            if asof_text:
                params["asof_date"] = asof_text
            frame = pd.read_sql_query(text(query), engine, params=params)
        except SQLAlchemyError:
            return pd.DataFrame()

        if frame is None or frame.empty:
            return pd.DataFrame()
        self._financial_latest_snapshot_cache[cache_key] = frame.copy()
        return frame

    @staticmethod
    def _build_features(
        trading: pd.DataFrame,
        fundamental: pd.DataFrame,
        financial_cache: dict[str, pd.DataFrame],
        industry_map: pd.DataFrame,
        lookback_days: int,
        min_history_rows: int,
    ) -> pd.DataFrame:
        trading = trading.copy()
        fundamental = fundamental.copy()

        for col in ["ts_code", "trade_date", "close", "pct_change", "vol"]:
            if col not in trading.columns:
                trading[col] = np.nan
        for col in ["ts_code", "trade_date", "pe", "pb", "ps", "total_mv", "circ_mv", "turnover_rate"]:
            if col not in fundamental.columns:
                fundamental[col] = np.nan

        frame = pd.merge(
            trading[["ts_code", "trade_date", "close", "pct_change", "vol"]],
            fundamental[["ts_code", "trade_date", "pe", "pb", "ps", "total_mv", "circ_mv", "turnover_rate"]],
            on=["ts_code", "trade_date"],
            how="left",
        ).sort_values(["ts_code", "trade_date"])

        lookback_days = max(5, int(lookback_days))
        grp = frame.groupby("ts_code", group_keys=False)
        frame["ret_5d"] = grp["close"].transform(lambda s: s.replace(0, np.nan).pct_change(5))
        frame["ret_lb"] = grp["close"].transform(lambda s: s.replace(0, np.nan).pct_change(lookback_days))
        frame["vol_lb_std"] = grp["pct_change"].transform(lambda s: s.rolling(lookback_days).std())
        frame["turnover_lb_mean"] = grp["turnover_rate"].transform(lambda s: s.rolling(lookback_days).mean())
        frame["pe_rank_120d"] = grp["pe"].transform(
            lambda s: s.rolling(120).apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
        )

        if financial_cache:
            fin = pd.DataFrame({"ts_code": frame["ts_code"].drop_duplicates()})
            snapshot = financial_cache.get("snapshot")
            if snapshot is not None and not snapshot.empty:
                is_panel_like = {"ann_date", "report_type"}.issubset(set(snapshot.columns))
                if is_panel_like:
                    panel_cols = [
                        c
                        for c in snapshot.columns
                        if c not in {"id", "created_at", "updated_at", "source_updated_at"}
                    ]
                    s2 = snapshot[panel_cols].copy()
                    s2["ts_code"] = s2["ts_code"].astype(str)
                    if "report_type" in s2.columns:
                        s2["report_type"] = s2["report_type"].fillna("UNKNOWN").astype(str).str.upper()
                    s2["ann_date"] = pd.to_datetime(s2["ann_date"], errors="coerce")
                    if "end_date" in s2.columns:
                        s2["end_date"] = pd.to_datetime(s2["end_date"], errors="coerce")
                    if "fiscal_year" in s2.columns:
                        s2["fiscal_year"] = pd.to_numeric(s2["fiscal_year"], errors="coerce")

                    s2 = s2.dropna(subset=["ann_date"])
                    sort_cols = ["ts_code", "ann_date"]
                    if "report_type" in s2.columns:
                        sort_cols.append("report_type")
                    if "end_date" in s2.columns:
                        sort_cols.append("end_date")
                    if "fiscal_year" in s2.columns:
                        sort_cols.append("fiscal_year")
                    s2 = s2.sort_values(sort_cols, kind="mergesort")

                    if {"report_type", "end_date"}.issubset(set(s2.columns)):
                        s2 = s2.drop_duplicates(["ts_code", "report_type", "ann_date"], keep="last")
                    elif "end_date" in s2.columns:
                        s2 = s2.drop_duplicates(["ts_code", "ann_date"], keep="last")

                    left = frame.copy()
                    left["ts_code"] = left["ts_code"].astype(str)
                    left["trade_date"] = pd.to_datetime(left["trade_date"], errors="coerce")
                    left = left.dropna(subset=["trade_date"])
                    left = left.sort_values(["ts_code", "trade_date"], kind="mergesort")

                    right = s2.copy()
                    right = right.sort_values(["ts_code", "ann_date"], kind="mergesort")
                    frame = pd.merge_asof(
                        left,
                        right,
                        left_on="trade_date",
                        right_on="ann_date",
                        by="ts_code",
                        direction="backward",
                        allow_exact_matches=True,
                    )

                    if "report_type" in frame.columns:
                        frame["report_type"] = frame["report_type"].fillna("UNKNOWN").astype(str)
                        frame["report_type_code"] = frame["report_type"].astype("category").cat.codes.astype(float)
                    if "fiscal_year" in frame.columns:
                        frame["fiscal_year"] = pd.to_numeric(frame["fiscal_year"], errors="coerce")
                    if "ann_date" in frame.columns:
                        frame["ann_date_lag_days"] = (frame["trade_date"] - frame["ann_date"]).dt.days
                else:
                    keep_cols = [
                        c
                        for c in snapshot.columns
                        if c
                        not in {
                            "id",
                            "created_at",
                            "updated_at",
                            "source_updated_at",
                            "ann_date",
                        }
                    ]
                    if "ts_code" in keep_cols:
                        s2 = snapshot[keep_cols].copy()
                        if "end_date" in s2.columns:
                            s2["end_date"] = pd.to_datetime(s2["end_date"], errors="coerce")
                            s2 = s2.sort_values(["ts_code", "end_date"]).groupby("ts_code", as_index=False).tail(1)
                        fin = fin.merge(s2.drop(columns=[c for c in ["end_date"] if c in s2.columns]), on="ts_code", how="left")

            fina = financial_cache.get("fina_indicator_vip") or financial_cache.get("fina_indicator")
            if fina is not None and not fina.empty:
                cols = [c for c in ["ts_code", "roe", "q_dt_roe", "grossprofit_margin", "netprofit_margin", "end_date"] if c in fina.columns]
                f2 = fina[cols].copy()
                if "end_date" in f2.columns:
                    f2["end_date"] = pd.to_datetime(f2["end_date"], errors="coerce")
                    f2 = f2.sort_values(["ts_code", "end_date"]).groupby("ts_code", as_index=False).tail(1)
                fin = fin.merge(f2.drop(columns=[c for c in ["end_date"] if c in f2.columns]), on="ts_code", how="left")

            income = financial_cache.get("income")
            if income is not None and not income.empty:
                cols = [c for c in ["ts_code", "revenue", "n_income", "end_date"] if c in income.columns]
                i2 = income[cols].copy()
                if "end_date" in i2.columns:
                    i2["end_date"] = pd.to_datetime(i2["end_date"], errors="coerce")
                    i2 = i2.sort_values(["ts_code", "end_date"]).groupby("ts_code", as_index=False).tail(1)
                fin = fin.merge(i2.drop(columns=[c for c in ["end_date"] if c in i2.columns]), on="ts_code", how="left")

            if not ({"ann_date", "report_type"}.issubset(set(snapshot.columns)) if snapshot is not None and not snapshot.empty else False):
                frame = frame.merge(fin, on="ts_code", how="left")

        if industry_map is not None and not industry_map.empty:
            frame = frame.merge(industry_map, on="ts_code", how="left")

        if "industry_name" not in frame.columns:
            frame["industry_name"] = "UNKNOWN"
        frame["industry_name"] = frame["industry_name"].fillna("UNKNOWN").astype(str)
        frame["industry_code"] = frame["industry_name"].astype("category").cat.codes.astype(float)

        # Industry neutralized features reduce cross-sector valuation comparability bias.
        for col in ["pe", "pb", "ps", "ret_5d", "ret_lb", "turnover_rate"]:
            if col in frame.columns:
                frame[f"{col}_ind_rank"] = frame.groupby(["trade_date", "industry_name"])[col].transform(lambda s: s.rank(pct=True))

        counts = frame.groupby("ts_code").size()
        valid = set(counts[counts >= int(min_history_rows)].index)
        frame = frame[frame["ts_code"].isin(valid)]
        frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=["close"]).reset_index(drop=True)
        return frame

    @staticmethod
    def _build_targets(frame: pd.DataFrame, horizon_days: int, label_cfg: dict[str, Any] | None = None) -> pd.DataFrame:
        label_cfg = label_cfg or {}
        frame = frame.sort_values(["ts_code", "trade_date"]).copy()
        grp = frame.groupby("ts_code", group_keys=False)

        future_close = grp["close"].shift(-horizon_days)
        frame["target_valuation_return"] = (future_close - frame["close"]) / frame["close"].replace(0, np.nan)
        frame["target_valuation_up"] = np.where(
            future_close.notna(),
            (frame["target_valuation_return"] > 0).astype(float),
            np.nan,
        )

        earnings_signal = None
        for col in ["n_income", "q_dt_roe", "roe", "netprofit_margin"]:
            if col in frame.columns:
                earnings_signal = frame[col] if earnings_signal is None else earnings_signal.fillna(frame[col])

        if earnings_signal is None:
            frame["target_earnings_growth"] = np.nan
        else:
            frame["_earnings_signal"] = earnings_signal
            frame["target_earnings_growth"] = grp["_earnings_signal"].transform(
                lambda s: s.replace(0, np.nan).pct_change(fill_method=None).shift(-1)
            )
            frame.drop(columns=["_earnings_signal"], inplace=True)

        # FY-supervised labels: map each sample year to same-year FY result.
        # This is required for Q1/H1/Q3 -> FY training.
        fy_value_col = str(label_cfg.get("fy_value_col", "n_income"))
        if {"fiscal_year", "report_type", fy_value_col}.issubset(set(frame.columns)):
            tmp = frame[["ts_code", "fiscal_year", "report_type", fy_value_col]].copy()
            tmp["ts_code"] = tmp["ts_code"].astype(str)
            tmp["fiscal_year"] = pd.to_numeric(tmp["fiscal_year"], errors="coerce")
            fy_rows = tmp[tmp["report_type"].astype(str).str.upper() == "FY"].copy()
            fy_rows = fy_rows.dropna(subset=["fiscal_year"])
            fy_rows = fy_rows.sort_values(["ts_code", "fiscal_year"]).drop_duplicates(["ts_code", "fiscal_year"], keep="last")
            fy_rows["target_fy_value"] = pd.to_numeric(fy_rows[fy_value_col], errors="coerce")
            fy_rows["target_fy_value_yoy"] = fy_rows.groupby("ts_code")["target_fy_value"].transform(
                lambda s: s.replace(0, np.nan).pct_change()
            )
            fy_rows["target_fy_up"] = (fy_rows["target_fy_value_yoy"] > 0).astype(float)

            # Memory-safe FY label mapping: avoid a full frame.merge on wide datasets.
            label_map = fy_rows[["ts_code", "fiscal_year", "target_fy_value", "target_fy_value_yoy", "target_fy_up"]].copy()
            label_map["fiscal_year"] = pd.to_numeric(label_map["fiscal_year"], errors="coerce")
            label_idx = label_map.set_index(["ts_code", "fiscal_year"])

            key_index = pd.MultiIndex.from_arrays(
                [
                    frame["ts_code"].astype(str),
                    pd.to_numeric(frame["fiscal_year"], errors="coerce"),
                ],
                names=["ts_code", "fiscal_year"],
            )
            aligned = label_idx.reindex(key_index)
            frame["target_fy_value"] = aligned["target_fy_value"].to_numpy()
            frame["target_fy_value_yoy"] = aligned["target_fy_value_yoy"].to_numpy()
            frame["target_fy_up"] = aligned["target_fy_up"].to_numpy()

            # For FY-supervised task, non-FY report rows are primary training samples.
            if bool(label_cfg.get("exclude_fy_rows_for_training", True)) and "report_type" in frame.columns:
                frame["is_fy_row"] = frame["report_type"].astype(str).str.upper().eq("FY")
            else:
                frame["is_fy_row"] = False
        else:
            frame["target_fy_value"] = np.nan
            frame["target_fy_value_yoy"] = np.nan
            frame["target_fy_up"] = np.nan
            frame["is_fy_row"] = False

        risk_cfg = label_cfg.get("risk") or {}
        if bool(risk_cfg.get("enabled", True)):
            risk_horizon_days = max(5, int(risk_cfg.get("horizon_days", horizon_days)))
            risk_min_periods = max(1, int(risk_cfg.get("min_periods", max(5, risk_horizon_days // 2))))

            future_min_close = grp["close"].transform(
                lambda s: EarningsForecastPipeline._forward_rolling_min(s, risk_horizon_days, risk_min_periods)
            )
            future_close_vol = grp["close"].transform(
                lambda s: EarningsForecastPipeline._forward_close_volatility(s, risk_horizon_days, risk_min_periods)
            )

            close_base = frame["close"].replace(0, np.nan)
            frame["target_risk_drawdown"] = (future_min_close - close_base) / close_base
            frame["target_risk_volatility"] = future_close_vol

            severe_drawdown = abs(float(risk_cfg.get("severe_drawdown", 0.20)))
            severe_volatility = float(risk_cfg.get("severe_volatility", 0.05))
            weight_drawdown = float(risk_cfg.get("weight_drawdown", 0.7))
            weight_volatility = float(risk_cfg.get("weight_volatility", 0.3))
            weight_sum = weight_drawdown + weight_volatility
            if weight_sum <= 0:
                weight_drawdown, weight_volatility, weight_sum = 0.7, 0.3, 1.0
            weight_drawdown /= weight_sum
            weight_volatility /= weight_sum

            drawdown_component = ((-frame["target_risk_drawdown"]).clip(lower=0) / max(severe_drawdown, 1e-6)).clip(0, 1)
            volatility_component = (frame["target_risk_volatility"].clip(lower=0) / max(severe_volatility, 1e-6)).clip(0, 1)
            frame["target_risk_score"] = 100.0 * (
                weight_drawdown * drawdown_component + weight_volatility * volatility_component
            )

            risk_bands = risk_cfg.get("score_bands") or [
                {"max": 35, "level": "LOW", "code": 0},
                {"max": 65, "level": "MEDIUM", "code": 1},
                {"max": 100, "level": "HIGH", "code": 2},
            ]
            risk_bands = sorted(risk_bands, key=lambda x: float(x.get("max", 100)))

            def _map_risk_level(score: float | None):
                if score is None or pd.isna(score):
                    return (None, np.nan)
                score_value = float(score)
                for item in risk_bands:
                    if score_value <= float(item.get("max", 100)):
                        return (str(item.get("level") or "MEDIUM"), float(item.get("code", 1)))
                last = risk_bands[-1]
                return (str(last.get("level") or "HIGH"), float(last.get("code", 2)))

            mapped = frame["target_risk_score"].apply(_map_risk_level)
            frame["target_risk_level"] = mapped.str[0]
            frame["target_risk_level_code"] = pd.to_numeric(mapped.str[1], errors="coerce")
            high_code = max(float(x.get("code", 0)) for x in risk_bands)
            frame["target_risk_high"] = (frame["target_risk_level_code"] >= high_code).astype(float)
        else:
            frame["target_risk_drawdown"] = np.nan
            frame["target_risk_volatility"] = np.nan
            frame["target_risk_score"] = np.nan
            frame["target_risk_level"] = None
            frame["target_risk_level_code"] = np.nan
            frame["target_risk_high"] = np.nan

        return frame

    def prepare_dataset(self) -> Path:
        t0 = time.perf_counter()
        self._prepare_log("start")
        feature_cfg = self.config.get("feature", {})
        label_cfg = self.config.get("label", {})
        output_cfg = self.config.get("output", {})
        dataset_out_dir = self._dataset_output_dir()

        self._prepare_log("loading market frames")
        t_market = time.perf_counter()
        trading, fundamental = self._load_market_frames()
        self._prepare_log(
            f"market loaded: trading_rows={len(trading)}, fundamental_rows={len(fundamental)}, elapsed={time.perf_counter()-t_market:.2f}s"
        )

        self._prepare_log("loading financial cache")
        t_fin = time.perf_counter()
        financial_cache = self._load_financial_cache()
        snapshot_rows = 0
        snapshot = financial_cache.get("snapshot") if isinstance(financial_cache, dict) else None
        if isinstance(snapshot, pd.DataFrame):
            snapshot_rows = int(len(snapshot))
        self._prepare_log(
            f"financial loaded: keys={list(financial_cache.keys()) if isinstance(financial_cache, dict) else []}, snapshot_rows={snapshot_rows}, elapsed={time.perf_counter()-t_fin:.2f}s"
        )

        if isinstance(financial_cache, dict):
            financial_cache["__prepare_sampling__"] = feature_cfg.get("prepare_sampling") or {}
            sampling_cfg = financial_cache["__prepare_sampling__"]
            self._prepare_log(f"prepare sampling config: {sampling_cfg}")

        self._prepare_log("loading industry mapping")
        t_ind = time.perf_counter()
        industry_map = self._load_industry_mapping()
        self._prepare_log(f"industry map loaded: rows={len(industry_map)}, elapsed={time.perf_counter()-t_ind:.2f}s")

        self._prepare_log("building features")
        t_feat = time.perf_counter()
        frame = self._build_features(
            trading=trading,
            fundamental=fundamental,
            financial_cache=financial_cache,
            industry_map=industry_map,
            lookback_days=int(feature_cfg.get("lookback_days", 20)),
            min_history_rows=int(feature_cfg.get("min_history_rows", 120)),
        )
        self._prepare_log(f"features built: rows={len(frame)}, cols={len(frame.columns)}, elapsed={time.perf_counter()-t_feat:.2f}s")

        self._prepare_log("building targets")
        t_label = time.perf_counter()
        frame = self._build_targets(
            frame,
            horizon_days=int(label_cfg.get("horizon_days", 20)),
            label_cfg=label_cfg,
        )
        self._prepare_log(f"targets built: rows={len(frame)}, cols={len(frame.columns)}, elapsed={time.perf_counter()-t_label:.2f}s")

        dataset_file = output_cfg.get("dataset_file", "dataset.parquet")
        output_path = dataset_out_dir / dataset_file
        self._prepare_log(f"writing dataset: {output_path}")
        t_write = time.perf_counter()
        frame.to_parquet(output_path, index=False)
        self._prepare_log(f"dataset written: size_bytes={output_path.stat().st_size if output_path.exists() else 0}, elapsed={time.perf_counter()-t_write:.2f}s")

        split_by_report_type = bool(output_cfg.get("split_dataset_by_report_type", False))
        if split_by_report_type and "report_type" in frame.columns:
            self._prepare_log("writing report_type split datasets")
            t_split = time.perf_counter()
            split_dir_name = str(output_cfg.get("split_dataset_dir", "datasets_by_report_type"))
            split_dir = dataset_out_dir / split_dir_name
            split_dir.mkdir(parents=True, exist_ok=True)

            requested_types = output_cfg.get("split_report_types")
            if isinstance(requested_types, list) and requested_types:
                report_types = [str(x).strip().upper() for x in requested_types if str(x).strip()]
            else:
                report_types = (
                    frame["report_type"]
                    .fillna("UNKNOWN")
                    .astype(str)
                    .str.upper()
                    .drop_duplicates()
                    .tolist()
                )

            # Keep stable ordering for predictable output file names.
            report_types = sorted([x for x in report_types if x])
            stem = Path(dataset_file).stem
            suffix = Path(dataset_file).suffix or ".parquet"
            split_max_rows = int(output_cfg.get("split_max_rows_per_report_type", 0) or 0)

            manifest: list[dict[str, Any]] = []
            for report_type in report_types:
                part = frame[frame["report_type"].fillna("UNKNOWN").astype(str).str.upper() == report_type].copy()
                if part.empty:
                    continue
                if split_max_rows > 0 and len(part) > split_max_rows:
                    part = part.sort_values("trade_date", ascending=False).head(split_max_rows)

                part_file = f"{stem}_{report_type}{suffix}"
                part_path = split_dir / part_file
                part.to_parquet(part_path, index=False)

                manifest.append(
                    {
                        "report_type": report_type,
                        "path": str(part_path.resolve()),
                        "rows": int(len(part)),
                        "trade_date_min": str(part["trade_date"].min()) if "trade_date" in part.columns else None,
                        "trade_date_max": str(part["trade_date"].max()) if "trade_date" in part.columns else None,
                    }
                )

                del part
                gc.collect()

            manifest_path = split_dir / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "created_at_utc": datetime.now(timezone.utc).isoformat(),
                        "dataset_file": str(output_path.resolve()),
                        "items": manifest,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self._prepare_log(f"split datasets written: count={len(manifest)}, dir={split_dir}, elapsed={time.perf_counter()-t_split:.2f}s")

        dataset_meta = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "dataset_version": self._resolve_dataset_version() or None,
            "dataset_path": str(output_path.resolve()),
            "rows": int(len(frame)),
            "columns": int(len(frame.columns)),
            "config_path": str(self.config_path),
            "config_hash": self._config_hash(),
        }
        (dataset_out_dir / "dataset_meta.json").write_text(
            json.dumps(dataset_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._prepare_log(f"done: total_elapsed={time.perf_counter()-t0:.2f}s")
        return output_path

    def train(self, rebuild_dataset: bool = False) -> dict[str, Any]:
        train_cfg = self.config.get("train", {})
        output_cfg = self.config.get("output", {})
        dataset_out_dir = self._dataset_output_dir()

        dataset_path = dataset_out_dir / output_cfg.get("dataset_file", "dataset.parquet")
        if rebuild_dataset or (not dataset_path.exists()):
            dataset_path = self.prepare_dataset()

        df: pd.DataFrame
        split_dir = dataset_out_dir / str(output_cfg.get("split_dataset_dir", "datasets_by_report_type"))
        manifest_path = split_dir / "manifest.json"
        train_report_type = str(train_cfg.get("report_type") or "").strip().upper()

        if train_report_type and manifest_path.exists():
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            items = payload.get("items") or []
            matched = None
            for item in items:
                if str(item.get("report_type") or "").strip().upper() == train_report_type:
                    matched = item
                    break
            if matched is None:
                available = sorted({str(x.get("report_type") or "").strip().upper() for x in items if x})
                raise ValueError(
                    f"Configured train.report_type={train_report_type} not found in split manifest. available={available}"
                )
            df = pd.read_parquet(Path(str(matched["path"])))
        else:
            df = pd.read_parquet(dataset_path)
        feature_exclude = {
            "ts_code",
            "trade_date",
            "industry_name",
            "report_type",
            "ann_date",
            "end_date",
            "target_valuation_return",
            "target_valuation_up",
            "target_earnings_growth",
            "target_fy_value",
            "target_fy_value_yoy",
            "target_fy_up",
            "target_risk_drawdown",
            "target_risk_volatility",
            "target_risk_score",
            "target_risk_level",
            "target_risk_level_code",
            "target_risk_high",
            "is_fy_row",
        }
        feature_cols = [c for c in df.columns if c not in feature_exclude]

        model_df = df.copy()
        model_df[feature_cols] = model_df[feature_cols].replace([np.inf, -np.inf], np.nan)
        for col in feature_cols:
            model_df[col] = pd.to_numeric(model_df[col], errors="coerce")

        train_end_date = train_cfg.get("train_end_date")
        if train_end_date:
            cutoff = pd.Timestamp(train_end_date)
        else:
            cutoff = model_df["trade_date"].quantile(0.8)

        train = model_df[model_df["trade_date"] <= cutoff]
        test = model_df[model_df["trade_date"] > cutoff]

        # For capped split shards (latest-N rows), fixed date cutoffs can produce empty train.
        # Auto-fallback to quantile split to keep training runnable without rebuilding dataset.
        if len(train) == 0 and len(model_df) > 1:
            fallback_cutoff = model_df["trade_date"].quantile(0.8)
            train = model_df[model_df["trade_date"] <= fallback_cutoff]
            test = model_df[model_df["trade_date"] > fallback_cutoff]
            cutoff = fallback_cutoff

        if len(train) == 0:
            raise ValueError(
                f"No train rows after split. report_type={train_cfg.get('report_type')}, cutoff={cutoff}, total_rows={len(model_df)}"
            )

        # Default to FY-supervised targets when available.
        requested_reg_target = str(self.config.get("label", {}).get("reg_target", "target_fy_value_yoy"))
        requested_cls_target = str(self.config.get("label", {}).get("cls_target", "target_fy_up"))
        reg_target_col = requested_reg_target if requested_reg_target in model_df.columns else "target_earnings_growth"
        cls_target_col = requested_cls_target if requested_cls_target in model_df.columns else "target_valuation_up"

        # FY task leakage guard: ensure train/test do not share same fiscal_year labels.
        # For target_fy_* tasks, split by fiscal_year is more robust than date split on capped shards.
        fy_split_enabled = bool(train_cfg.get("fy_split_by_fiscal_year", True))
        fy_targets = {"target_fy_up", "target_fy_value", "target_fy_value_yoy"}
        if fy_split_enabled and "fiscal_year" in model_df.columns and (
            reg_target_col in fy_targets or cls_target_col in fy_targets
        ):
            fy_series = pd.to_numeric(model_df["fiscal_year"], errors="coerce")
            years = sorted(int(y) for y in fy_series.dropna().unique())
            fy_test_years = max(1, int(train_cfg.get("fy_test_years", 1)))
            if len(years) > fy_test_years:
                test_years = set(years[-fy_test_years:])
                train = model_df[~fy_series.isin(test_years)]
                test = model_df[fy_series.isin(test_years)]

        if "is_fy_row" in train.columns and bool(self.config.get("label", {}).get("exclude_fy_rows_for_training", True)):
            train = train[~train["is_fy_row"].fillna(False)]
            test = test[~test["is_fy_row"].fillna(False)]

        stock_median_lookback_years = int(train_cfg.get("stock_median_lookback_years", 3))
        recent_start = pd.Timestamp(cutoff) - pd.DateOffset(years=stock_median_lookback_years)
        train_recent = train[train["trade_date"] >= recent_start]

        # Fit imputation statistics on train only to avoid test leakage.
        train_global_median = train[feature_cols].median(numeric_only=True)
        train_industry_median = train.groupby("industry_name")[feature_cols].median(numeric_only=True)
        train_tscode_median = train_recent.groupby("ts_code")[feature_cols].median(numeric_only=True)

        def _apply_hierarchical_impute(part: pd.DataFrame) -> pd.DataFrame:
            x = part[["ts_code", "industry_name"] + feature_cols].copy()
            x["__row_id"] = part.index

            ts_med = train_tscode_median.add_suffix("__ts").reset_index()
            ind_med = train_industry_median.add_suffix("__ind").reset_index()
            x = x.merge(ts_med, on="ts_code", how="left")
            x = x.merge(ind_med, on="industry_name", how="left")

            for col in feature_cols:
                x[col] = x[col].fillna(x.get(f"{col}__ts"))
                x[col] = x[col].fillna(x.get(f"{col}__ind"))
                x[col] = x[col].fillna(train_global_median.get(col))

            x = x.set_index("__row_id", drop=True)
            return x[feature_cols]

        x_train = _apply_hierarchical_impute(train)
        x_test = _apply_hierarchical_impute(test)

        reg_mask_train = train[reg_target_col].notna()
        reg_mask_test = test[reg_target_col].notna()
        cls_min_test_rows = max(1, int(train_cfg.get("cls_min_test_rows", 1000)))

        # Some split datasets (e.g. one report_type shard) may not have FY labels for every row.
        # Fallback to valuation label if requested classification target has no trainable samples.
        cls_candidates = []
        for c in [requested_cls_target, "target_valuation_up"]:
            c = str(c or "").strip()
            if c and c in train.columns and c not in cls_candidates:
                cls_candidates.append(c)

        selected_cls_target = None
        cls_mask_train = None
        cls_mask_test = None
        for candidate in cls_candidates:
            mask_train = train[candidate].notna()
            mask_test = test[candidate].notna()
            if int(mask_train.sum()) <= 0:
                continue
            if train.loc[mask_train, candidate].nunique(dropna=True) < 2:
                continue
            if int(mask_test.sum()) < cls_min_test_rows:
                continue
            if test.loc[mask_test, candidate].nunique(dropna=True) < 2:
                continue
            selected_cls_target = candidate
            cls_mask_train = mask_train
            cls_mask_test = mask_test
            break

        if selected_cls_target is None:
            candidate_text = ",".join(cls_candidates) if cls_candidates else requested_cls_target
            raise ValueError(
                f"No usable classification labels in training split. candidates={candidate_text}, train_rows={len(train)}"
            )

        cls_target_col = selected_cls_target
        train_industry = train["industry_name"].fillna("UNKNOWN").astype(str)
        test_industry = test["industry_name"].fillna("UNKNOWN").astype(str)

        random_state = int(train_cfg.get("random_state", 42))
        classifier_algo = str(train_cfg.get("classifier_algo", "hgb"))
        regressor_algo = str(train_cfg.get("regressor_algo", "hgb"))
        industry_classifier_algo = str(train_cfg.get("industry_classifier_algo", classifier_algo))
        industry_regressor_algo = str(train_cfg.get("industry_regressor_algo", regressor_algo))

        reg = self._create_regressor(regressor_algo, random_state)
        clf = self._create_classifier(classifier_algo, random_state)

        def _safe_auc(y_true: pd.Series, y_prob: np.ndarray | pd.Series) -> float | None:
            ys = pd.Series(y_true).dropna()
            if ys.nunique() < 2:
                return None
            return float(roc_auc_score(ys, y_prob))

        reg_mae = None
        if reg_mask_train.sum() > 50:
            reg.fit(x_train.loc[reg_mask_train], train.loc[reg_mask_train, reg_target_col])
            if reg_mask_test.sum() > 0:
                reg_pred = reg.predict(x_test.loc[reg_mask_test])
                reg_mae = float(mean_absolute_error(test.loc[reg_mask_test, reg_target_col], reg_pred))
        else:
            reg = None

        clf.fit(x_train.loc[cls_mask_train], train.loc[cls_mask_train, cls_target_col])

        cls_acc = None
        cls_auc = None
        industry_eval: dict[str, dict[str, float]] = {}
        if cls_mask_test.sum() > 0:
            cls_pred = clf.predict(x_test.loc[cls_mask_test])
            cls_prob = clf.predict_proba(x_test.loc[cls_mask_test])[:, 1]
            cls_acc = float(accuracy_score(test.loc[cls_mask_test, cls_target_col], cls_pred))
            cls_auc = _safe_auc(test.loc[cls_mask_test, cls_target_col], cls_prob)

            eval_df = test.loc[cls_mask_test, ["industry_name", cls_target_col]].copy()
            eval_df["pred"] = cls_pred
            eval_df["prob"] = cls_prob
            min_samples = int(train_cfg.get("industry_eval_min_samples", 120))
            for industry_name, grp in eval_df.groupby("industry_name"):
                if len(grp) < min_samples:
                    continue
                y_true = grp[cls_target_col]
                y_pred = grp["pred"]
                y_prob = grp["prob"]
                ind_auc = _safe_auc(y_true, y_prob)
                industry_eval[str(industry_name)] = {
                    "samples": int(len(grp)),
                    "acc": float(accuracy_score(y_true, y_pred)),
                    "auc": float("nan") if ind_auc is None else float(ind_auc),
                }

        # Optional sector specialists: train per-industry models, fallback to global at inference.
        industry_models: dict[str, dict[str, Any]] = {}
        use_industry_models = bool(train_cfg.get("use_industry_models", True))
        industry_train_min_rows = int(train_cfg.get("industry_train_min_rows", 240))
        industry_reg_min_rows = int(train_cfg.get("industry_reg_min_rows", 80))
        if use_industry_models:
            for industry_name, industry_idx in train.groupby(train_industry).groups.items():
                idx = list(industry_idx)
                if len(idx) < industry_train_min_rows:
                    continue

                cls_idx = train.loc[idx, cls_target_col].dropna().index
                cls_series = train.loc[cls_idx, cls_target_col]
                if cls_series.nunique() < 2:
                    continue

                x_i = x_train.loc[cls_idx]
                y_cls_i = train.loc[cls_idx, cls_target_col]
                cls_i = self._create_classifier(industry_classifier_algo, random_state)
                cls_i.fit(x_i, y_cls_i)

                reg_i = None
                reg_idx = train.loc[idx, reg_target_col].dropna().index
                if len(reg_idx) >= industry_reg_min_rows:
                    reg_i = self._create_regressor(industry_regressor_algo, random_state)
                    reg_i.fit(x_train.loc[reg_idx], train.loc[reg_idx, reg_target_col])

                industry_models[str(industry_name)] = {
                    "classifier": cls_i,
                    "regressor": reg_i,
                    "train_rows": int(len(idx)),
                    "reg_rows": int(len(reg_idx)),
                }

        # Evaluate industry specialists on same-industry test rows to compare with global model.
        industry_model_eval: dict[str, dict[str, float]] = {}
        if industry_models and cls_mask_test.sum() > 0:
            for industry_name, meta in industry_models.items():
                test_idx = test[(test_industry == industry_name) & cls_mask_test].index
                if len(test_idx) == 0:
                    continue

                y_true = test.loc[test_idx, cls_target_col]
                cls_i = meta["classifier"]
                y_pred = cls_i.predict(x_test.loc[test_idx])
                y_prob = cls_i.predict_proba(x_test.loc[test_idx])[:, 1]

                ind_auc = _safe_auc(y_true, y_prob)

                industry_model_eval[industry_name] = {
                    "test_samples": int(len(test_idx)),
                    "acc": float(accuracy_score(y_true, y_pred)),
                    "auc": float("nan") if ind_auc is None else float(ind_auc),
                }

        run_id = self._build_run_id(
            classifier_algo=classifier_algo,
            regressor_algo=regressor_algo,
            train_rows=int(len(train)),
            test_rows=int(len(test)),
        )

        bundle = {
            "run_id": run_id,
            "regressor": reg,
            "classifier": clf,
            "industry_models": industry_models,
            "feature_cols": feature_cols,
            "metrics": {
                "run_id": run_id,
                "classifier_algo": classifier_algo,
                "regressor_algo": regressor_algo,
                "industry_classifier_algo": industry_classifier_algo,
                "industry_regressor_algo": industry_regressor_algo,
                "reg_target_col": reg_target_col,
                "cls_target_col": cls_target_col,
                "reg_train_rows_used": int(reg_mask_train.sum()),
                "reg_test_rows_used": int(reg_mask_test.sum()),
                "cls_train_rows_used": int(cls_mask_train.sum()),
                "cls_test_rows_used": int(cls_mask_test.sum()),
                "reg_mae": reg_mae,
                "cls_acc": cls_acc,
                "cls_auc": cls_auc,
                "industry_eval": industry_eval,
                "industry_model_count": int(len(industry_models)),
                "industry_model_eval": industry_model_eval,
                "stock_median_lookback_years": int(stock_median_lookback_years),
                "train_rows": int(len(train)),
                "test_rows": int(len(test)),
            },
        }

        model_version = str(train_cfg.get("model_version") or run_id).strip() or run_id

        model_file = output_cfg.get("model_file", "models.joblib")
        metrics_file = output_cfg.get("metrics_file", "metrics.json")
        joblib.dump(bundle, self.output_dir / model_file)

        metrics_text = json.dumps(bundle["metrics"], ensure_ascii=False, indent=2)
        (self.output_dir / metrics_file).write_text(metrics_text, encoding="utf-8")

        # Persist every experiment run for algorithm comparison and later audits.
        exp_root = self.output_dir / "experiments"
        run_dir = exp_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, run_dir / model_file)
        (run_dir / metrics_file).write_text(metrics_text, encoding="utf-8")

        # Versioned artifact directory for deterministic promotion/rollback.
        version_root = self.output_dir / str(output_cfg.get("model_versions_dir", "model_versions"))
        version_dir = version_root / model_version
        version_dir.mkdir(parents=True, exist_ok=True)
        version_model_path = version_dir / model_file
        version_metrics_path = version_dir / metrics_file
        joblib.dump(bundle, version_model_path)
        version_metrics_path.write_text(metrics_text, encoding="utf-8")

        # Persist predict-time median cache to avoid loading full dataset in online refresh.
        impute_stats = {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "model_version": model_version,
            "feature_cols": feature_cols,
            "global_median": {k: (None if pd.isna(v) else float(v)) for k, v in train_global_median.items()},
            "industry_median": {},
        }
        for industry_name, row in train_industry_median.iterrows():
            impute_stats["industry_median"][str(industry_name)] = {
                k: (None if pd.isna(v) else float(v)) for k, v in row.items()
            }
        (version_dir / "impute_stats.json").write_text(
            json.dumps(impute_stats, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        record = {
            "run_id": run_id,
            "model_version": model_version,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "config_path": str(self.config_path),
            "config_hash": self._config_hash(),
            "classifier_algo": classifier_algo,
            "regressor_algo": regressor_algo,
            "industry_classifier_algo": industry_classifier_algo,
            "industry_regressor_algo": industry_regressor_algo,
            "metrics": bundle["metrics"],
            "model_path": str((run_dir / model_file).resolve()),
            "metrics_path": str((run_dir / metrics_file).resolve()),
            "dataset_path": str(dataset_path.resolve()),
            "versioned_model_path": str(version_model_path.resolve()),
            "versioned_metrics_path": str(version_metrics_path.resolve()),
            "dataset_version": self._resolve_dataset_version() or None,
            "report_type": train_report_type or None,
        }
        history_file = self.output_dir / "experiment_runs.jsonl"
        with history_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        self._write_registry_record(
            {
                "created_at_utc": record["created_at_utc"],
                "run_id": run_id,
                "model_version": model_version,
                "model_name": str(train_cfg.get("model_name") or "earnings_forecast"),
                "report_type": train_report_type or None,
                "dataset_version": record["dataset_version"],
                "dataset_path": record["dataset_path"],
                "config_path": record["config_path"],
                "config_hash": record["config_hash"],
                "metrics": bundle["metrics"],
                "artifact": {
                    "model_path": record["versioned_model_path"],
                    "metrics_path": record["versioned_metrics_path"],
                },
                "status": "candidate",
            }
        )

        self._update_serving_pointer(
            {
                "run_id": run_id,
                "model_version": model_version,
                "model_name": str(train_cfg.get("model_name") or "earnings_forecast"),
                "report_type": train_report_type or None,
                "model_path": str(version_model_path.resolve()),
                "metrics_path": str(version_metrics_path.resolve()),
                "dataset_path": str(dataset_path.resolve()),
                "dataset_version": self._resolve_dataset_version() or None,
            },
            promote_to_production=bool(train_cfg.get("promote_to_production", False)),
        )

        return bundle["metrics"]

    def predict(
        self,
        ts_code: str,
        model_version: str | None = None,
        serving_slot: str = "production",
        requested_report_type: str | None = None,
        requested_financial_end_date: str | None = None,
        anchor_mode: str = "ann",
        asof_date: datetime | pd.Timestamp | str | None = None,
    ) -> dict[str, Any]:
        output_cfg = self.config.get("output", {})
        code = str(ts_code).strip()
        anchor_mode_normalized = str(anchor_mode or "ann").strip().lower()
        if anchor_mode_normalized in {"live", "live_latest", "latest"}:
            anchor_mode_normalized = "live_latest"
        else:
            anchor_mode_normalized = "ann"
        requested_report_type = str(requested_report_type or "").strip().upper()
        if requested_report_type in {"ANNUAL", "FULL_YEAR", "A"}:
            requested_report_type = "FY"
        if requested_report_type == "UNKNOWN":
            requested_report_type = ""
        requested_end_date = ""
        if requested_financial_end_date:
            parsed_end_date = pd.to_datetime(requested_financial_end_date, errors="coerce")
            if pd.notna(parsed_end_date):
                requested_end_date = pd.Timestamp(parsed_end_date).strftime("%Y-%m-%d")

        live_subset = self._build_live_predict_features(
            code,
            requested_report_type=requested_report_type or None,
            requested_financial_end_date=requested_end_date or None,
            asof_date=asof_date,
        )
        latest_report_type = None
        if live_subset is not None and not live_subset.empty and "report_type" in live_subset.columns:
            latest_report_type = str(live_subset["report_type"].iloc[-1] or "").strip().upper()

        preferred_report_type = requested_report_type or latest_report_type

        model_path = self._resolve_predict_model_path(
            latest_report_type=preferred_report_type,
            model_version=model_version,
            serving_slot=serving_slot,
        )
        if not model_path.exists():
            raise FileNotFoundError(f"model not found: {model_path}")

        effective_model_version = self._infer_model_version_from_path(model_path) or str(model_version or "").strip()
        served_model_report_type = self._infer_model_report_type_from_path(model_path)
        dataset_path = self._resolve_predict_dataset_path(
            model_version=effective_model_version,
            serving_slot=serving_slot,
        )
        if not dataset_path.exists():
            raise FileNotFoundError(f"dataset not found: {dataset_path}")

        def _select_anchor_row(frame: pd.DataFrame) -> pd.DataFrame:
            if frame is None or frame.empty:
                return frame

            local = frame.copy()
            if "trade_date" not in local.columns:
                return local.tail(1)

            local["trade_date"] = pd.to_datetime(local["trade_date"], errors="coerce")
            local = local.dropna(subset=["trade_date"])
            if local.empty:
                return frame.tail(1)

            if anchor_mode_normalized == "live_latest":
                return local.sort_values("trade_date").tail(1)

            if "ann_date" not in local.columns:
                return local.sort_values("trade_date").tail(1)

            local["ann_date"] = pd.to_datetime(local["ann_date"], errors="coerce")
            valid_ann = local.dropna(subset=["ann_date"])
            if valid_ann.empty:
                return local.sort_values("trade_date").tail(1)

            latest_ann_date = valid_ann["ann_date"].max()
            valid_ann = valid_ann[valid_ann["ann_date"] == latest_ann_date]
            if valid_ann.empty:
                return local.sort_values("trade_date").tail(1)

            # Anchor on the feature row closest to announcement date; tie-break prefers on/after ann_date.
            valid_ann["_delta_days"] = (valid_ann["trade_date"] - valid_ann["ann_date"]).dt.days
            valid_ann["_abs_delta_days"] = valid_ann["_delta_days"].abs()
            valid_ann["_is_before_ann"] = valid_ann["_delta_days"] < 0
            selected = valid_ann.sort_values(
                ["_abs_delta_days", "_is_before_ann", "trade_date"],
                ascending=[True, True, False],
            ).head(1)
            return selected.drop(columns=["_delta_days", "_abs_delta_days", "_is_before_ann"], errors="ignore")

        bundle_key = str(model_path.resolve())
        bundle = self._bundle_cache.get(bundle_key)
        if bundle is None:
            bundle = joblib.load(model_path)
            self._bundle_cache[bundle_key] = bundle

        # Prefer latest online data (market + financial snapshot) for serving,
        # and keep dataset fallback to avoid runtime interruption.
        data_source = "live_db"
        allow_dataset_fallback = bool(output_cfg.get("predict_allow_dataset_fallback", True))
        if live_subset is None or live_subset.empty:
            if not allow_dataset_fallback:
                raise ValueError(f"live features unavailable for ts_code={code}")
            subset = self._load_predict_subset_from_dataset(
                ts_code=code,
                dataset_path=dataset_path,
                requested_report_type=requested_report_type or None,
            )
            if subset.empty:
                raise ValueError(f"No rows for ts_code={code}")
            row = _select_anchor_row(subset)
            data_source = "dataset_fallback"
        else:
            # live subset is already built in ts_code/trade_date order
            subset = live_subset
            row = _select_anchor_row(subset)

        feature_cols = list(bundle["feature_cols"])
        x = row.reindex(columns=feature_cols).copy()
        x = x.replace([np.inf, -np.inf], np.nan)
        for col in feature_cols:
            x[col] = pd.to_numeric(x[col], errors="coerce")

        # Predict-time hierarchical fill: stock recent-N-year median -> industry median -> global median.
        # Only compute heavy impute stats when current row really has missing features.
        if bool(x.isna().to_numpy().any()):
            stock_median_lookback_years = int(self.config.get("train", {}).get("stock_median_lookback_years", 3))
            row_trade_date = pd.Timestamp(row["trade_date"].iloc[0])
            stock_recent_start = row_trade_date - pd.DateOffset(years=stock_median_lookback_years)
            stock_hist = (
                subset[subset["trade_date"] >= stock_recent_start]
                .reindex(columns=feature_cols)
                .replace([np.inf, -np.inf], np.nan)
                .apply(pd.to_numeric, errors="coerce")
            )
            stock_med = stock_hist.median(numeric_only=True)
            ind_name = str(row.get("industry_name", pd.Series(["UNKNOWN"])) .iloc[0])
            global_med, industry_median_df = self._load_predict_impute_stats(
                model_version=effective_model_version,
                feature_cols=feature_cols,
                dataset_path=dataset_path,
            )
            if not industry_median_df.empty and ind_name in industry_median_df.index:
                ind_med = industry_median_df.loc[ind_name]
            else:
                ind_med = pd.Series(dtype=float)

            for col in feature_cols:
                x[col] = x[col].fillna(stock_med.get(col))
                x[col] = x[col].fillna(ind_med.get(col))
                x[col] = x[col].fillna(global_med.get(col))
        industry_name = str(row.get("industry_name", pd.Series(["UNKNOWN"])) .iloc[0])
        report_type = str(row.get("report_type", pd.Series(["UNKNOWN"])) .iloc[0] or "UNKNOWN").upper()
        ann_date = str(row.get("ann_date", pd.Series([""])) .iloc[0] or "")
        end_date = str(row.get("end_date", pd.Series([""])) .iloc[0] or "")
        fy_raw = pd.to_numeric(row.get("fiscal_year", pd.Series([np.nan])), errors="coerce").iloc[0]
        fiscal_year = int(fy_raw) if pd.notna(fy_raw) else None
        report_meta_source = "live"

        # If live metadata is missing, fallback to latest record from versioned dataset for traceability.
        if report_type in {"", "UNKNOWN"} or not ann_date or not end_date or fiscal_year is None:
            meta = self._resolve_report_meta_from_dataset(
                ts_code=code,
                dataset_path=dataset_path,
                requested_report_type=requested_report_type or None,
            )
            if meta:
                report_type = str(meta.get("report_type") or report_type or "UNKNOWN").upper()
                ann_date = str(meta.get("ann_date") or ann_date or "")
                end_date = str(meta.get("end_date") or end_date or "")
                fiscal_year = meta.get("fiscal_year") if meta.get("fiscal_year") is not None else fiscal_year
                report_meta_source = "dataset_latest"

        if report_meta_source == "live":
            report_source = self._resolve_report_source_from_raw(
                ts_code=code,
                report_type=report_type,
                end_date=end_date,
            )
        else:
            report_source = report_meta_source

        model_source = "global"
        classifier = bundle["classifier"]
        regressor = bundle.get("regressor")
        industry_models = bundle.get("industry_models") or {}
        if isinstance(industry_models, dict) and industry_name in industry_models:
            item = industry_models.get(industry_name) or {}
            if item.get("classifier") is not None:
                classifier = item["classifier"]
                model_source = f"industry:{industry_name}"
            if item.get("regressor") is not None:
                regressor = item["regressor"]

        earnings_pred = None
        if regressor is not None:
            earnings_pred = float(regressor.predict(x)[0])
        valuation_up_prob = float(classifier.predict_proba(x)[0][1])
        valuation_mapping = self._valuation_mapping(
            valuation_up_prob=valuation_up_prob,
            earnings_growth=earnings_pred,
        )

        stance = str(valuation_mapping.get("stance") or "HOLD").upper()
        score = float(valuation_mapping.get("score") or 0.0)
        action_map = {
            "STRONG_BUY": "BUY",
            "BUY": "BUY",
            "HOLD": "HOLD",
            "REDUCE": "SELL_PART",
            "SELL": "SELL",
        }
        risk_level = self._risk_level_from_score(score)
        quality_guard = self._apply_quality_risk_guard(row=x, base_score=score, base_risk_level=risk_level)
        score = float(quality_guard.get("score") or score)
        risk_level = str(quality_guard.get("risk_level") or risk_level).upper()

        picked = self._pick_valuation_band(score)
        stance = str(picked.get("stance") or stance or "HOLD").upper()
        confidence = str(picked.get("confidence") or valuation_mapping.get("confidence") or "MEDIUM").upper()
        be_action = action_map.get(stance, "HOLD")

        valuation_mapping["score"] = round(score, 2)
        valuation_mapping["stance"] = stance
        valuation_mapping["confidence"] = confidence
        valuation_mapping["quality_risk_guard"] = {
            "applied": bool(quality_guard.get("applied", False)),
            "penalty_total": quality_guard.get("penalty_total", 0.0),
            "reasons": quality_guard.get("reasons") or [],
        }

        market_regime_meta = self._detect_market_regime(asof_trade_date=row["trade_date"].iloc[0])
        market_regime = str(market_regime_meta.get("regime") or "BALANCE").upper()

        current_price = self._to_float_or_none(row.get("close", pd.Series([np.nan])).iloc[0])
        current_market_cap = self._to_float_or_none(row.get("total_mv", pd.Series([np.nan])).iloc[0])
        if current_market_cap is None and subset is not None and not subset.empty and "total_mv" in subset.columns:
            mv_series = pd.to_numeric(subset["total_mv"], errors="coerce").dropna()
            if not mv_series.empty:
                current_market_cap = self._to_float_or_none(mv_series.iloc[-1])
        industry_rank = self._to_float_or_none(row.get("pe_ind_rank", pd.Series([np.nan])).iloc[0])
        realized_volatility = self._to_float_or_none(row.get("vol_lb_std", pd.Series([np.nan])).iloc[0])
        quant_target = self._build_quantitative_target(
            score=score,
            current_price=current_price,
            current_market_cap=current_market_cap,
            valuation_up_prob=valuation_up_prob,
            earnings_growth=earnings_pred,
            industry_rank=industry_rank,
            risk_level=risk_level,
            realized_volatility=realized_volatility,
            market_regime=market_regime,
            asof_trade_date=row["trade_date"].iloc[0],
        )
        market_overall_adjustment = ((quant_target.get("components") or {}).get("market_overall_adjustment") or {})

        return {
            "ts_code": code,
            "trade_date": str(row["trade_date"].iloc[0]),
            "industry_name": industry_name,
            "feature_data_source": data_source,
            "financial_report_type": report_type,
            "financial_ann_date": ann_date,
            "financial_end_date": end_date,
            "financial_fiscal_year": fiscal_year,
            "financial_report_source": report_source,
            "financial_meta_source": report_meta_source,
            "requested_report_type": requested_report_type or None,
            "anchor_mode": anchor_mode_normalized,
            "latest_available_report_type": latest_report_type or report_type,
            "model_path": str(model_path),
            "model_version": effective_model_version,
            "served_model_report_type": served_model_report_type,
            "serving_slot": str(serving_slot or "production"),
            "model_source": model_source,
            "pred_earnings_growth": earnings_pred,
            "pred_valuation_up_prob": valuation_up_prob,
            "valuation_mapping": valuation_mapping,
            "quality_risk_guard": valuation_mapping.get("quality_risk_guard"),
            "market_regime": market_regime_meta,
            "market_overall_adjustment": market_overall_adjustment,
            "quantitative_target": quant_target,
            "target_return_pct": quant_target.get("target_return_pct"),
            "target_price": quant_target.get("target_price"),
            "target_market_cap": quant_target.get("target_market_cap"),
            "be_payload": {
                "signal_score": score,
                "action": be_action,
                "risk_level": risk_level,
                "market_regime": market_regime,
                "market_overall_state": market_overall_adjustment.get("state"),
                "market_overall_multiplier": market_overall_adjustment.get("multiplier"),
                "target_return_pct": quant_target.get("target_return_pct"),
                "target_price": quant_target.get("target_price"),
                "target_market_cap": quant_target.get("target_market_cap"),
            },
            # Backward compatibility aliases; can be removed after BE fully migrates to be_payload.
            "signal_score": score,
            "action": be_action,
            "risk_level": risk_level,
        }

    def predict_fusion(
        self,
        ts_code: str,
        model_version: str | None = None,
        serving_slot: str = "production",
        report_types: list[str] | None = None,
        anchor_mode: str = "ann",
        asof_date: datetime | pd.Timestamp | str | None = None,
    ) -> dict[str, Any]:
        code = str(ts_code or "").strip().upper()
        if not code:
            raise ValueError("ts_code is required")

        anchor_mode_normalized = str(anchor_mode or "ann").strip().lower()
        if anchor_mode_normalized in {"live", "live_latest", "latest"}:
            anchor_mode_normalized = "live_latest"
        else:
            anchor_mode_normalized = "ann"

        target_report_types = report_types or ["Q1", "H1", "Q3", "FY"]
        normalized_types: list[str] = []
        for rt in target_report_types:
            x = str(rt or "").strip().upper()
            if x in {"ANNUAL", "FULL_YEAR", "A"}:
                x = "FY"
            if x in {"Q1", "H1", "Q3", "FY"} and x not in normalized_types:
                normalized_types.append(x)
        if not normalized_types:
            normalized_types = ["Q1", "H1", "Q3", "FY"]

        cfg = (self.config.get("valuation_mapping") or {}).get("fusion") or {}
        base_weights_cfg = cfg.get("base_weights") or {"Q1": 0.9, "H1": 1.0, "Q3": 1.1, "FY": 1.0}
        confidence_weights_cfg = cfg.get("confidence_weights") or {"HIGH": 1.0, "MEDIUM": 0.8, "LOW": 0.6}
        half_life_days = max(1.0, float(cfg.get("freshness_half_life_days", 365.0)))

        components: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []

        for rt in normalized_types:
            try:
                result = self.predict(
                    ts_code=code,
                    model_version=model_version,
                    serving_slot=serving_slot,
                    requested_report_type=rt,
                    anchor_mode=anchor_mode_normalized,
                    asof_date=asof_date,
                )

                ann_raw = result.get("financial_ann_date") or result.get("trade_date")
                ann_dt = pd.to_datetime(ann_raw, errors="coerce")
                asof_ts = pd.to_datetime(asof_date, errors="coerce") if asof_date is not None else pd.NaT
                age_anchor = (
                    pd.Timestamp(asof_ts).normalize()
                    if pd.notna(asof_ts)
                    else pd.Timestamp.now().normalize()
                )
                if pd.isna(ann_dt):
                    age_days = 365.0
                else:
                    age_days = max(0.0, float((age_anchor - ann_dt.normalize()).days))

                freshness_weight = float(np.exp(-age_days / half_life_days))
                confidence_key = str((result.get("valuation_mapping") or {}).get("confidence") or "MEDIUM").upper()
                confidence_weight = float(confidence_weights_cfg.get(confidence_key, 0.8))
                base_weight = float(base_weights_cfg.get(rt, 1.0))
                final_weight = max(1e-6, base_weight * freshness_weight * confidence_weight)

                components.append(
                    {
                        "report_type": rt,
                        "result": result,
                        "weight": final_weight,
                        "weight_components": {
                            "base": base_weight,
                            "freshness": freshness_weight,
                            "confidence": confidence_weight,
                            "age_days": round(age_days, 2),
                        },
                    }
                )
            except Exception as exc:
                failures.append({"report_type": rt, "error": str(exc)})

        if not components:
            raise ValueError(f"fusion predict failed for {code}, no successful components: {failures}")

        weight_sum = sum(float(item["weight"]) for item in components)
        if weight_sum <= 0:
            weight_sum = float(len(components))

        for item in components:
            item["weight_norm"] = float(item["weight"]) / weight_sum

        def _weighted(name: str) -> float | None:
            acc = 0.0
            used = 0.0
            for item in components:
                val = self._to_float_or_none(item["result"].get(name))
                if val is None:
                    continue
                w = float(item["weight_norm"])
                acc += w * val
                used += w
            if used <= 0:
                return None
            return acc / used

        fused_prob = _weighted("pred_valuation_up_prob")
        fused_earn = _weighted("pred_earnings_growth")
        valuation_mapping = self._valuation_mapping(
            valuation_up_prob=0.5 if fused_prob is None else fused_prob,
            earnings_growth=fused_earn,
        )

        score = float(valuation_mapping.get("score") or 0.0)
        stance = str(valuation_mapping.get("stance") or "HOLD").upper()
        action_map = {
            "STRONG_BUY": "BUY",
            "BUY": "BUY",
            "HOLD": "HOLD",
            "REDUCE": "SELL_PART",
            "SELL": "SELL",
        }
        be_action = action_map.get(stance, "HOLD")
        if score >= 65:
            risk_level = "LOW"
        elif score >= 50:
            risk_level = "MEDIUM"
        else:
            risk_level = "HIGH"

        trade_dates = [
            pd.to_datetime(item["result"].get("trade_date"), errors="coerce")
            for item in components
        ]
        valid_trade_dates = [x for x in trade_dates if pd.notna(x)]
        fused_trade_date = max(valid_trade_dates).isoformat() if valid_trade_dates else None

        market_regime_meta = components[0]["result"].get("market_regime") or {"regime": "BALANCE", "source": "fusion"}
        market_regime = str(market_regime_meta.get("regime") or "BALANCE").upper()

        fused_target_return = _weighted("target_return_pct")
        fused_target_price = _weighted("target_price")
        fused_target_market_cap = _weighted("target_market_cap")
        fused_target_return_low = _weighted("target_return_low_pct")
        fused_target_return_high = _weighted("target_return_high_pct")
        fused_target_price_low = _weighted("target_price_low")
        fused_target_price_high = _weighted("target_price_high")
        fused_target_market_cap_low = _weighted("target_market_cap_low")
        fused_target_market_cap_high = _weighted("target_market_cap_high")

        band_pct = float((self.config.get("valuation_mapping") or {}).get("target_band_pct", 0.1) or 0.1)
        band_pct = max(0.01, min(0.5, band_pct))
        if fused_target_return is not None:
            if fused_target_return_low is None:
                fused_target_return_low = fused_target_return * (1.0 - band_pct)
            if fused_target_return_high is None:
                fused_target_return_high = fused_target_return * (1.0 + band_pct)
        if fused_target_price is not None:
            if fused_target_price_low is None:
                fused_target_price_low = fused_target_price * (1.0 - band_pct)
            if fused_target_price_high is None:
                fused_target_price_high = fused_target_price * (1.0 + band_pct)
        if fused_target_market_cap is not None:
            if fused_target_market_cap_low is None:
                fused_target_market_cap_low = fused_target_market_cap * (1.0 - band_pct)
            if fused_target_market_cap_high is None:
                fused_target_market_cap_high = fused_target_market_cap * (1.0 + band_pct)

        component_summaries = []
        for item in components:
            r = item["result"]
            component_summaries.append(
                {
                    "report_type": item["report_type"],
                    "weight": round(float(item["weight_norm"]), 6),
                    "score": self._to_float_or_none(r.get("signal_score")),
                    "action": r.get("action"),
                    "risk_level": r.get("risk_level"),
                    "model_version": r.get("model_version"),
                    "trade_date": r.get("trade_date"),
                    "financial_ann_date": r.get("financial_ann_date"),
                    "weight_components": item.get("weight_components") or {},
                }
            )

        return {
            "ts_code": code,
            "trade_date": fused_trade_date,
            "industry_name": components[0]["result"].get("industry_name"),
            "feature_data_source": "fusion",
            "financial_report_type": "FUSION",
            "financial_ann_date": "",
            "financial_end_date": "",
            "financial_fiscal_year": None,
            "financial_report_source": "fusion",
            "requested_report_type": "FUSION",
            "anchor_mode": anchor_mode_normalized,
            "latest_available_report_type": "FUSION",
            "served_model_report_type": "FUSION",
            "model_path": "",
            "model_version": "fusion",
            "serving_slot": str(serving_slot or "production"),
            "model_source": "fusion",
            "pred_earnings_growth": fused_earn,
            "pred_valuation_up_prob": fused_prob,
            "valuation_mapping": valuation_mapping,
            "market_regime": market_regime_meta,
            "quantitative_target": {
                "target_return_pct": fused_target_return,
                "target_return_low_pct": fused_target_return_low,
                "target_return_high_pct": fused_target_return_high,
                "target_price": fused_target_price,
                "target_price_low": fused_target_price_low,
                "target_price_high": fused_target_price_high,
                "target_market_cap": fused_target_market_cap,
                "target_market_cap_low": fused_target_market_cap_low,
                "target_market_cap_high": fused_target_market_cap_high,
                "components": {"mode": "fusion"},
            },
            "target_return_pct": fused_target_return,
            "target_return_low_pct": fused_target_return_low,
            "target_return_high_pct": fused_target_return_high,
            "target_price": fused_target_price,
            "target_price_low": fused_target_price_low,
            "target_price_high": fused_target_price_high,
            "target_market_cap": fused_target_market_cap,
            "target_market_cap_low": fused_target_market_cap_low,
            "target_market_cap_high": fused_target_market_cap_high,
            "be_payload": {
                "signal_score": score,
                "action": be_action,
                "risk_level": risk_level,
                "market_regime": market_regime,
                "target_return_pct": fused_target_return,
                "target_price": fused_target_price,
                "target_market_cap": fused_target_market_cap,
            },
            "signal_score": score,
            "action": be_action,
            "risk_level": risk_level,
            "fusion": {
                "components": component_summaries,
                "failed_components": failures,
                "weights_version": str(cfg.get("version") or "v1"),
            },
        }

    def _load_predict_impute_stats(
        self,
        model_version: str,
        feature_cols: list[str],
        dataset_path: Path,
    ) -> tuple[pd.Series, pd.DataFrame]:
        cache_key = f"{model_version}|{str(dataset_path.resolve())}"
        cached = self._impute_stats_cache.get(cache_key)
        if cached is not None:
            return cached

        stats_path = self._resolve_impute_stats_path(model_version=model_version)
        global_med = pd.Series(dtype=float)
        industry_med = pd.DataFrame(columns=feature_cols)

        if stats_path.exists():
            try:
                payload = json.loads(stats_path.read_text(encoding="utf-8"))
                gm = payload.get("global_median") or {}
                im = payload.get("industry_median") or {}
                global_med = pd.Series(gm, dtype=float)
                if isinstance(im, dict) and im:
                    industry_med = pd.DataFrame.from_dict(im, orient="index")
                    industry_med = industry_med.reindex(columns=feature_cols)
                    for col in industry_med.columns:
                        industry_med[col] = pd.to_numeric(industry_med[col], errors="coerce")
            except (OSError, ValueError, TypeError):
                global_med = pd.Series(dtype=float)
                industry_med = pd.DataFrame(columns=feature_cols)

        if global_med.empty:
            df_stats = pd.read_parquet(dataset_path, columns=["industry_name", *feature_cols])
            df_stats = df_stats.replace([np.inf, -np.inf], np.nan)
            for col in feature_cols:
                df_stats[col] = pd.to_numeric(df_stats[col], errors="coerce")
            global_med = df_stats[feature_cols].median(numeric_only=True)
            if "industry_name" in df_stats.columns:
                industry_med = df_stats.groupby("industry_name")[feature_cols].median(numeric_only=True)
            else:
                industry_med = pd.DataFrame(columns=feature_cols)

            snapshot = {
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "model_version": model_version,
                "feature_cols": feature_cols,
                "global_median": {k: (None if pd.isna(v) else float(v)) for k, v in global_med.items()},
                "industry_median": {},
            }
            for industry_name, row in industry_med.iterrows():
                snapshot["industry_median"][str(industry_name)] = {
                    k: (None if pd.isna(v) else float(v)) for k, v in row.items()
                }
            stats_path.parent.mkdir(parents=True, exist_ok=True)
            stats_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        global_med = global_med.reindex(feature_cols)
        industry_med = industry_med.reindex(columns=feature_cols)
        self._impute_stats_cache[cache_key] = (global_med, industry_med)
        return global_med, industry_med

    def _resolve_impute_stats_path(self, model_version: str) -> Path:
        output_cfg = self.config.get("output", {})
        version = str(model_version or "").strip()
        if version:
            version_root = self.output_dir / str(output_cfg.get("model_versions_dir", "model_versions"))
            return version_root / version / "impute_stats.json"
        return self.output_dir / "impute_stats.json"

    @staticmethod
    def _load_predict_subset_from_dataset(
        ts_code: str,
        dataset_path: Path,
        requested_report_type: str | None = None,
    ) -> pd.DataFrame:
        code = str(ts_code or "").strip()
        if not code or not dataset_path.exists():
            return pd.DataFrame()

        requested_rt = str(requested_report_type or "").strip().upper()
        df = pd.DataFrame()

        try:
            import pyarrow.dataset as ds

            filter_expr = ds.field("ts_code") == code
            if requested_rt:
                filter_expr = filter_expr & (ds.field("report_type") == requested_rt)
            table = ds.dataset(str(dataset_path), format="parquet").to_table(filter=filter_expr)
            if table.num_rows > 0:
                df = table.to_pandas()
        except (ImportError, OSError, ValueError, TypeError):
            try:
                filters = [("ts_code", "==", code)]
                if requested_rt:
                    filters.append(("report_type", "==", requested_rt))
                df = pd.read_parquet(dataset_path, filters=filters)
            except (OSError, ValueError, TypeError, KeyError):
                return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
            df = df.dropna(subset=["trade_date"]).sort_values(["ts_code", "trade_date"])
        return df

    @staticmethod
    def _resolve_report_meta_from_dataset(
        ts_code: str,
        dataset_path: Path,
        requested_report_type: str | None = None,
    ) -> dict[str, Any]:
        code = str(ts_code or "").strip()
        if not code or not dataset_path.exists():
            return {}

        requested_rt = str(requested_report_type or "").strip().upper()
        if not requested_rt:
            requested_rt = ""

        cols = ["ts_code", "trade_date", "report_type", "ann_date", "end_date", "fiscal_year"]
        df = pd.DataFrame()

        try:
            import pyarrow.dataset as ds

            table = ds.dataset(str(dataset_path), format="parquet").to_table(
                columns=cols,
                filter=ds.field("ts_code") == code,
            )
            if table.num_rows > 0:
                df = table.to_pandas()
        except (ImportError, OSError, ValueError, TypeError):
            try:
                raw = pd.read_parquet(dataset_path, columns=cols)
                df = raw[raw["ts_code"].astype(str) == code]
            except (OSError, ValueError, TypeError, KeyError):
                return {}

        if df is None or df.empty:
            return {}

        if requested_rt and "report_type" in df.columns:
            df = df[df["report_type"].astype(str).str.upper() == requested_rt]

        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
        df = df.dropna(subset=["trade_date"]).sort_values("trade_date")
        if df.empty:
            return {}

        latest = df.tail(1).iloc[0]
        fy_raw = pd.to_numeric(pd.Series([latest.get("fiscal_year")]), errors="coerce").iloc[0]
        return {
            "report_type": str(latest.get("report_type") or "UNKNOWN").upper(),
            "ann_date": str(latest.get("ann_date") or ""),
            "end_date": str(latest.get("end_date") or ""),
            "fiscal_year": int(fy_raw) if pd.notna(fy_raw) else None,
        }

    def _resolve_serving_entry(self, serving_slot: str = "production") -> dict[str, Any] | None:
        output_cfg = self.config.get("output", {})
        pointer_file = self.output_dir / str(output_cfg.get("serving_pointer_file", "serving.yaml"))
        if not pointer_file.exists():
            return None
        try:
            payload = yaml.safe_load(pointer_file.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None

        slot = str(serving_slot or "production").strip().lower()
        if slot not in {"production", "candidate"}:
            slot = "production"
        node = payload.get(slot)
        if not isinstance(node, dict):
            return None
        return node

    def _resolve_serving_model_version(self, serving_slot: str = "production") -> str | None:
        node = self._resolve_serving_entry(serving_slot=serving_slot)
        if not node:
            return None
        version = str(node.get("model_version") or "").strip()
        return version or None

    def _resolve_predict_model_path(
        self,
        latest_report_type: str | None = None,
        model_version: str | None = None,
        serving_slot: str = "production",
    ) -> Path:
        output_cfg = self.config.get("output", {})

        target_version = str(model_version or "").strip()
        if not target_version:
            target_version = str(self._resolve_serving_model_version(serving_slot=serving_slot) or "").strip()

        if target_version:
            version_root = self.output_dir / str(output_cfg.get("model_versions_dir", "model_versions"))
            version_dir = version_root / target_version

            rt = str(latest_report_type or "").strip().upper()
            if rt:
                rt_file = version_dir / f"models_{rt}.joblib"
                if rt_file.exists():
                    return rt_file

            configured_name = str(output_cfg.get("model_file", "models.joblib"))
            configured = version_dir / configured_name
            if configured.exists():
                return configured

            candidates = sorted(
                version_dir.glob("models_*.joblib"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                return candidates[0]

        configured = self.output_dir / output_cfg.get("model_file", "models.joblib")
        if configured.exists():
            return configured

        rt = str(latest_report_type or "").strip().upper()
        if rt:
            rt_file = self.output_dir / f"models_{rt}.joblib"
            if rt_file.exists():
                return rt_file

        candidates = sorted(
            self.output_dir.glob("models_*.joblib"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]
        return configured

    @staticmethod
    def _infer_model_version_from_path(model_path: Path) -> str:
        parts = list(model_path.parts)
        if "model_versions" in parts:
            idx = parts.index("model_versions")
            if idx + 1 < len(parts):
                return str(parts[idx + 1])
        return ""

    @staticmethod
    def _infer_model_report_type_from_path(model_path: Path) -> str:
        stem = str(model_path.stem or "").strip().upper()
        if stem.startswith("MODELS_"):
            return stem.split("MODELS_", 1)[1] or "UNKNOWN"
        return "UNKNOWN"

    def _resolve_predict_dataset_path(self, model_version: str | None = None, serving_slot: str = "production") -> Path:
        output_cfg = self.config.get("output", {})
        dataset_name = str(output_cfg.get("dataset_file", "dataset.parquet"))
        configured = self.output_dir / dataset_name
        version_root = self.output_dir / str(output_cfg.get("dataset_versions_dir", "datasets"))

        def _from_serving_node(node: dict[str, Any]) -> Path | None:
            dataset_path_text = str(node.get("dataset_path") or "").strip()
            if dataset_path_text:
                path = Path(dataset_path_text)
                if path.exists():
                    return path
            dataset_version = str(node.get("dataset_version") or "").strip()
            if dataset_version:
                path = version_root / dataset_version / dataset_name
                if path.exists():
                    return path
            return None

        target_version = str(model_version or "").strip()
        if target_version:
            versioned = version_root / target_version / dataset_name
            if versioned.exists():
                return versioned

            pointer_file = self.output_dir / str(output_cfg.get("serving_pointer_file", "serving.yaml"))
            if pointer_file.exists():
                try:
                    payload = yaml.safe_load(pointer_file.read_text(encoding="utf-8")) or {}
                except (OSError, ValueError, TypeError):
                    payload = {}
                if isinstance(payload, dict):
                    for slot_name in ("production", "candidate"):
                        node = payload.get(slot_name)
                        if not isinstance(node, dict):
                            continue
                        if str(node.get("model_version") or "").strip() != target_version:
                            continue
                        matched = _from_serving_node(node)
                        if matched is not None:
                            return matched

        slot_node = self._resolve_serving_entry(serving_slot=serving_slot)
        if slot_node:
            matched = _from_serving_node(slot_node)
            if matched is not None:
                return matched

        return configured

    def _build_live_predict_features(
        self,
        ts_code: str,
        requested_report_type: str | None = None,
        requested_financial_end_date: str | None = None,
        asof_date: datetime | pd.Timestamp | str | None = None,
    ) -> pd.DataFrame:
        code = str(ts_code or "").strip()
        if not code:
            return pd.DataFrame()

        asof_ts = pd.to_datetime(asof_date, errors="coerce") if asof_date is not None else pd.NaT
        asof_cache_key = code
        if pd.notna(asof_ts):
            asof_cache_key = f"{code}|{pd.Timestamp(asof_ts).strftime('%Y-%m-%d')}"

        requested_rt = str(requested_report_type or "").strip().upper()
        if not requested_rt:
            requested_rt = ""

        cached_frame = self._live_feature_cache.get(asof_cache_key)
        if cached_frame is None:
            feature_cfg = self.config.get("feature", {})
            try:
                trading, fundamental = self._load_market_frames_for_ts_code(code)
                if trading.empty:
                    return pd.DataFrame()

                financial_cache = self._load_financial_cache_for_ts_code(code)
                if isinstance(financial_cache, dict):
                    financial_cache["__prepare_sampling__"] = feature_cfg.get("prepare_sampling") or {}
                else:
                    financial_cache = {}

                industry_map = self._load_industry_mapping_for_ts_code(code)

                frame = self._build_features(
                    trading=trading,
                    fundamental=fundamental,
                    financial_cache=financial_cache,
                    industry_map=industry_map,
                    lookback_days=int(feature_cfg.get("lookback_days", 20)),
                    min_history_rows=1,
                )
                if frame is None or frame.empty:
                    return pd.DataFrame()

                # Predict path should prefer the latest snapshot financial values.
                latest_snapshot = self._load_financial_latest_snapshot_for_ts_code(code, asof_date=asof_ts)
                if latest_snapshot is not None and not latest_snapshot.empty:
                    snap = latest_snapshot.iloc[0].to_dict()
                    fill_cols = [
                        "report_type",
                        "ann_date",
                        "end_date",
                        "fiscal_year",
                        "revenue",
                        "total_revenue",
                        "operate_profit",
                        "total_profit",
                        "n_income",
                        "n_income_attr_p",
                        "basic_eps",
                        "diluted_eps",
                        "roe",
                        "roe_dt",
                        "roa",
                        "q_dt_roe",
                        "tr_yoy",
                        "netprofit_yoy",
                        "grossprofit_margin",
                        "netprofit_margin",
                        "debt_to_assets",
                        "current_ratio",
                        "quick_ratio",
                        "cash_ratio",
                        "assets_turn",
                        "ocf_to_or",
                        "total_assets",
                        "total_liab",
                        "total_hldr_eqy_exc_min_int",
                        "money_cap",
                        "accounts_receiv",
                        "inventories",
                        "st_borr",
                        "lt_borr",
                        "n_cashflow_act",
                        "n_cashflow_inv_act",
                        "n_cash_flows_fnc_act",
                        "n_incr_cash_cash_equ",
                    ]
                    for col in fill_cols:
                        v = snap.get(col)
                        if col not in frame.columns:
                            frame[col] = np.nan if v is None else v
                        elif v is not None:
                            frame[col] = frame[col].fillna(v)

                    if "report_type" in frame.columns:
                        frame["report_type"] = frame["report_type"].fillna("UNKNOWN").astype(str).str.upper()
                    if "report_type_code" not in frame.columns and "report_type" in frame.columns:
                        frame["report_type_code"] = frame["report_type"].astype("category").cat.codes.astype(float)
                    if "ann_date" in frame.columns:
                        frame["ann_date"] = pd.to_datetime(frame["ann_date"], errors="coerce")
                    if "end_date" in frame.columns:
                        frame["end_date"] = pd.to_datetime(frame["end_date"], errors="coerce")
                    if "fiscal_year" in frame.columns:
                        frame["fiscal_year"] = pd.to_numeric(frame["fiscal_year"], errors="coerce")
                    if "ann_date_lag_days" not in frame.columns and "ann_date" in frame.columns and "trade_date" in frame.columns:
                        frame["ann_date_lag_days"] = (pd.to_datetime(frame["trade_date"], errors="coerce") - frame["ann_date"]).dt.days

                snapshot = financial_cache.get("snapshot") if isinstance(financial_cache, dict) else None
                if isinstance(snapshot, pd.DataFrame) and not snapshot.empty:
                    required = {"report_type", "ann_date", "end_date", "fiscal_year"}
                    missing_cols = [c for c in required if c not in frame.columns]
                    for col in missing_cols:
                        frame[col] = np.nan

                    need_backfill = frame[list(required)].isna().all(axis=1).any()
                    if need_backfill and {"ann_date", "report_type"}.issubset(set(snapshot.columns)):
                        s2 = snapshot.copy()
                        if "ts_code" in s2.columns:
                            s2 = s2[s2["ts_code"].astype(str) == code]
                        if not s2.empty:
                            s2["ann_date"] = pd.to_datetime(s2["ann_date"], errors="coerce")
                            if pd.notna(asof_ts):
                                s2 = s2[s2["ann_date"] <= pd.Timestamp(asof_ts)]
                            s2 = s2.dropna(subset=["ann_date"]).sort_values("ann_date")
                            if not s2.empty:
                                latest = s2.tail(1).iloc[0]
                                latest_report_type = str(latest.get("report_type") or "UNKNOWN").upper()
                                latest_ann_date = latest.get("ann_date")
                                latest_end_date = latest.get("end_date")
                                latest_fiscal_year = pd.to_numeric(pd.Series([latest.get("fiscal_year")]), errors="coerce").iloc[0]

                                frame["report_type"] = frame["report_type"].fillna(latest_report_type)
                                frame["ann_date"] = pd.to_datetime(frame["ann_date"], errors="coerce").fillna(latest_ann_date)
                                frame["end_date"] = pd.to_datetime(frame["end_date"], errors="coerce").fillna(
                                    pd.to_datetime(latest_end_date, errors="coerce")
                                )
                                frame["fiscal_year"] = pd.to_numeric(frame["fiscal_year"], errors="coerce").fillna(latest_fiscal_year)

                frame = frame[frame["ts_code"].astype(str) == code].copy()
                if "trade_date" in frame.columns:
                    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
                    frame = frame.dropna(subset=["trade_date"]).sort_values(["ts_code", "trade_date"])
                    if pd.notna(asof_ts):
                        frame = frame[frame["trade_date"] <= pd.Timestamp(asof_ts)]

                if pd.notna(asof_ts) and "ann_date" in frame.columns:
                    ann_dt = pd.to_datetime(frame["ann_date"], errors="coerce")
                    frame = frame[ann_dt.isna() | (ann_dt <= pd.Timestamp(asof_ts))]

                cached_frame = frame
                self._live_feature_cache[asof_cache_key] = frame.copy()
            except (SQLAlchemyError, ValueError, TypeError, KeyError, OSError):
                return pd.DataFrame()

        if requested_rt and "report_type" in cached_frame.columns:
            frame = cached_frame[
                cached_frame["report_type"].fillna("UNKNOWN").astype(str).str.upper() == requested_rt
            ]

            if requested_financial_end_date and "end_date" in frame.columns:
                requested_end_date_ts = pd.to_datetime(requested_financial_end_date, errors="coerce")
                if pd.notna(requested_end_date_ts):
                    requested_end_date_token = pd.Timestamp(requested_end_date_ts).strftime("%Y-%m-%d")
                    frame_end_dates = pd.to_datetime(frame["end_date"], errors="coerce").dt.strftime("%Y-%m-%d")
                    frame = frame[frame_end_dates == requested_end_date_token]

            # Same-day multi-report announcements (for example Q1 and FY both announced
            # on the same day) can cause the mixed merge_asof frame to retain only the
            # non-requested report type for the latest period while older requested rows
            # still exist. Rebuild against a requested-report-type-only panel whenever the
            # filtered frame is empty or lags behind the latest requested report ann_date.
            try:
                feature_cfg = self.config.get("feature", {})
                financial_cache = self._load_financial_cache_for_ts_code(code)
                snapshot = financial_cache.get("snapshot") if isinstance(financial_cache, dict) else None
                snap_filtered = pd.DataFrame()
                latest_snapshot_ann_date = pd.NaT
                latest_frame_ann_date = pd.NaT

                if isinstance(snapshot, pd.DataFrame) and not snapshot.empty and "report_type" in snapshot.columns:
                    snap_filtered = snapshot[
                        snapshot["report_type"].fillna("UNKNOWN").astype(str).str.upper() == requested_rt
                    ].copy()
                    if not snap_filtered.empty and "ann_date" in snap_filtered.columns:
                        if pd.notna(asof_ts):
                            snap_filtered = snap_filtered[
                                pd.to_datetime(snap_filtered["ann_date"], errors="coerce") <= pd.Timestamp(asof_ts)
                            ]
                        latest_snapshot_ann_date = pd.to_datetime(
                            snap_filtered["ann_date"], errors="coerce"
                        ).max()

                if not frame.empty and "ann_date" in frame.columns:
                    latest_frame_ann_date = pd.to_datetime(frame["ann_date"], errors="coerce").max()

                needs_rebuild = frame.empty or (
                    pd.notna(latest_snapshot_ann_date)
                    and (pd.isna(latest_frame_ann_date) or latest_frame_ann_date < latest_snapshot_ann_date)
                )

                if needs_rebuild and not snap_filtered.empty:
                    trading, fundamental = self._load_market_frames_for_ts_code(code)
                    if not trading.empty:
                        financial_cache = dict(financial_cache) if isinstance(financial_cache, dict) else {}
                        financial_cache["snapshot"] = snap_filtered
                        financial_cache["__prepare_sampling__"] = feature_cfg.get("prepare_sampling") or {}

                        industry_map = self._load_industry_mapping_for_ts_code(code)
                        rebuilt = self._build_features(
                            trading=trading,
                            fundamental=fundamental,
                            financial_cache=financial_cache,
                            industry_map=industry_map,
                            lookback_days=int(feature_cfg.get("lookback_days", 20)),
                            min_history_rows=1,
                        )
                        if rebuilt is not None and not rebuilt.empty and "report_type" in rebuilt.columns:
                            rebuilt = rebuilt[rebuilt["ts_code"].astype(str) == code].copy()
                            if "trade_date" in rebuilt.columns:
                                rebuilt["trade_date"] = pd.to_datetime(rebuilt["trade_date"], errors="coerce")
                                rebuilt = rebuilt.dropna(subset=["trade_date"]).sort_values(["ts_code", "trade_date"])
                            frame = rebuilt[
                                rebuilt["report_type"].fillna("UNKNOWN").astype(str).str.upper() == requested_rt
                            ]
            except (SQLAlchemyError, ValueError, TypeError, KeyError, OSError):
                pass
            if not frame.empty and "trade_date" in frame.columns:
                lookback_years = int(self.config.get("train", {}).get("stock_median_lookback_years", 3))
                latest_trade_date = pd.to_datetime(frame["trade_date"], errors="coerce").max()
                if pd.notna(latest_trade_date):
                    cutoff = latest_trade_date - pd.DateOffset(years=lookback_years)
                    frame = frame[pd.to_datetime(frame["trade_date"], errors="coerce") >= cutoff]
            return frame.copy()
        return cached_frame.copy()
