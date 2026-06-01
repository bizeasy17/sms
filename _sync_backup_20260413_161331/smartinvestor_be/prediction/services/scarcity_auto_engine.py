import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from django.conf import settings

from datastore.models import StockTradingHistory


class ScarcityAutoEngine:
    SCARCITY_AUTO_PROFILE_DEFAULTS = {
        "risk_weights": {
            "vol_z": 0.30,
            "risk_disp": 0.25,
            "data_gap": 0.20,
            "dd_z": 0.25,
        },
        "thresholds": {
            "conservative_min": 0.68,
            "balanced_min": 0.42,
        },
        "hysteresis": {
            "up_shift": 0.03,
            "down_shift": 0.03,
        },
        "confirmation_days": 3,
        "cooldown_days": 5,
        "missing_policy": {
            "min_available_indicators": 4,
            "fallback_profile": "balanced",
        },
        "circuit_breaker": {
            "enabled": True,
            "extreme_risk_min": 0.90,
            "force_profile": "conservative",
            "force_days": 3,
            "extreme_flags": ["extreme_market", "circuit_breaker", "halted"],
        },
        "legacy_signal_weights": {
            "score": 1.0,
            "confidence": 1.0,
        },
        "fallback_profile": "balanced",
    }
    SCARCITY_PROFILE_PRESETS = {
        "conservative": {
            "enabled": True,
            "beta": 0.35,
            "cap_pct": 30.0,
            "confidence_floor": 0.35,
        },
        "balanced": {
            "enabled": True,
            "beta": 0.50,
            "cap_pct": 45.0,
            "confidence_floor": 0.35,
        },
        "aggressive": {
            "enabled": True,
            "beta": 0.70,
            "cap_pct": 60.0,
            "confidence_floor": 0.35,
        },
        "off": {
            "enabled": False,
        },
    }
    SCARCITY_AUTOFILL_DEFAULTS = {
        "enabled": True,
        "beta": 1.0,
        "cap_pct": 80.0,
        "score": 0.35,
        "confidence": 0.55,
        "confidence_floor": 0.35,
    }

    _scarcity_auto_profile_cache = {}

    @staticmethod
    def _safe_float(value, default=None):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _clamp_unit(value):
        value_float = ScarcityAutoEngine._safe_float(value, default=None)
        if value_float is None:
            return None
        return max(0.0, min(1.0, value_float))

    @staticmethod
    def _parse_run_date(value):
        if isinstance(value, date):
            return value
        text = str(value or "").strip()
        if not text:
            return datetime.utcnow().date()
        if len(text) == 8 and text.isdigit():
            text = f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
        try:
            return datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError:
            return datetime.utcnow().date()

    @staticmethod
    def _format_run_date(value):
        if isinstance(value, date):
            return value.isoformat()
        return None

    @classmethod
    def _load_scarcity_auto_state(cls, market="CN"):
        market_key = str(market or "CN").strip().upper() or "CN"
        state_path = (
            Path(settings.BASE_DIR)
            / "static"
            / "valuation_config"
            / f"scarcity_auto_state_{market_key}.json"
        )
        if not state_path.exists():
            return state_path, {"market": market_key, "profiles": {}, "updated_at": None}
        try:
            with state_path.open("r", encoding="utf-8") as file_obj:
                payload = json.load(file_obj)
        except (OSError, ValueError):
            payload = {"market": market_key, "profiles": {}, "updated_at": None}

        profiles = payload.get("profiles")
        if not isinstance(profiles, dict):
            profiles = {}
        payload["market"] = market_key
        payload["profiles"] = profiles
        return state_path, payload

    @classmethod
    def _save_scarcity_auto_state(cls, state_path, state_payload):
        state_payload["updated_at"] = datetime.utcnow().isoformat(timespec="seconds")
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with state_path.open("w", encoding="utf-8") as file_obj:
            json.dump(state_payload, file_obj, ensure_ascii=False, indent=2)

    @classmethod
    def _autofill_scarcity_kwargs(cls, scarcity_kwargs):
        merged = dict(scarcity_kwargs or {})
        filled_keys = []
        for key, default_value in cls.SCARCITY_AUTOFILL_DEFAULTS.items():
            if merged.get(key) is None:
                merged[key] = default_value
                filled_keys.append(key)
        return merged, filled_keys

    @classmethod
    def _derive_auto_risk_indicators_from_df(cls, trading_df, run_day=None):
        if trading_df is None or trading_df.empty:
            return {}

        df = trading_df.copy()
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
            df = df.sort_values("trade_date").dropna(subset=["trade_date"])

        if "close_qfq" in df.columns or "close" in df.columns:
            df["close_price"] = pd.to_numeric(df.get("close_qfq"), errors="coerce")
            close_fallback = pd.to_numeric(df.get("close"), errors="coerce")
            df["close_price"] = df["close_price"].where(df["close_price"].notna(), close_fallback)
        else:
            return {}

        pct_qfq = pd.to_numeric(df.get("pct_change_qfq"), errors="coerce")
        pct_raw = pd.to_numeric(df.get("pct_change"), errors="coerce")
        returns_pct = pct_qfq.where(pct_qfq.notna(), pct_raw)
        if returns_pct.isna().all():
            returns_pct = df["close_price"].pct_change() * 100.0
        df["returns"] = pd.to_numeric(returns_pct, errors="coerce") / 100.0

        df = df.dropna(subset=["close_price"])  # keep returns NaN for first row
        if df.empty:
            return {}

        run_day = cls._parse_run_date(run_day)
        latest_trade_day = pd.to_datetime(df["trade_date"].iloc[-1]).date()
        staleness_days = max((run_day - latest_trade_day).days, 0)

        returns = pd.to_numeric(df["returns"], errors="coerce")
        abs_returns = returns.abs()

        rolling20 = returns.rolling(window=20).std().dropna()
        vol_20 = cls._safe_float(rolling20.iloc[-1], 0.0) if not rolling20.empty else 0.0
        vol_median = cls._safe_float(rolling20.median(), vol_20) if not rolling20.empty else vol_20
        vol_mad = cls._safe_float((rolling20 - vol_median).abs().median(), 0.0) if not rolling20.empty else 0.0
        vol_z_raw = (vol_20 - vol_median) / (vol_mad + 1e-6)
        vol_z = cls._clamp_unit((vol_z_raw + 3.0) / 6.0)

        abs_tail_20 = abs_returns.tail(20).dropna()
        abs_tail_120 = abs_returns.tail(120).dropna()
        if abs_tail_20.empty:
            risk_disp = None
        else:
            dispersion_recent = cls._safe_float(abs_tail_20.std(), 0.0)
            dispersion_base = cls._safe_float(abs_tail_120.median(), 0.0) if not abs_tail_120.empty else 0.0
            dispersion_ratio = dispersion_recent / (dispersion_base + 1e-6)
            risk_disp = cls._clamp_unit((dispersion_ratio - 0.8) / 1.2)

        closes = pd.to_numeric(df["close_price"], errors="coerce").dropna()
        if closes.empty:
            dd_z = None
        else:
            rolling_peak = closes.cummax()
            drawdown = 1.0 - (closes / rolling_peak)
            drawdown = drawdown.fillna(0.0)
            dd_now = cls._safe_float(drawdown.iloc[-1], 0.0)
            dd_ref = cls._safe_float(drawdown.tail(120).quantile(0.9), 0.0)
            dd_ref = max(dd_ref, 0.08)
            dd_z = cls._clamp_unit(dd_now / dd_ref)

        observed_last_60 = int(df.tail(60)["close_price"].notna().sum())
        expected_last_60 = 60.0
        coverage_ratio = max(0.0, min(1.0, observed_last_60 / expected_last_60))
        staleness_ratio = max(0.0, min(1.0, staleness_days / 5.0))
        data_gap = cls._clamp_unit(0.7 * (1.0 - coverage_ratio) + 0.3 * staleness_ratio)

        latest_ret = cls._safe_float(returns.iloc[-1], 0.0)
        status_flags = []
        if latest_ret <= -0.095:
            status_flags.append("limit_down_like")
        if (vol_z is not None and vol_z >= 0.9) and (dd_z is not None and dd_z >= 0.85):
            status_flags.append("extreme_market")

        return {
            "vol_z": round(vol_z, 6) if vol_z is not None else None,
            "risk_disp": round(risk_disp, 6) if risk_disp is not None else None,
            "data_gap": round(data_gap, 6) if data_gap is not None else None,
            "dd_z": round(dd_z, 6) if dd_z is not None else None,
            "extreme_market": bool("extreme_market" in status_flags),
            "status_flags": status_flags,
            "latest_trade_date": latest_trade_day.isoformat(),
            "staleness_days": staleness_days,
        }

    @classmethod
    def _compute_auto_risk_indicators(cls, tscode, trade_date=None):
        ts_code = str(tscode or "").strip().upper()
        if not ts_code:
            return {}

        target_day = cls._parse_run_date(trade_date)
        qs = StockTradingHistory.objects.filter(ts_code=ts_code, freq="D")
        if target_day is not None:
            qs = qs.filter(trade_date__lte=target_day)

        rows = list(
            qs.order_by("-trade_date")
            .values("trade_date", "close_qfq", "close", "pct_change_qfq", "pct_change")[:320]
        )
        if not rows:
            return {}
        rows.reverse()
        trading_df = pd.DataFrame(rows)
        return cls._derive_auto_risk_indicators_from_df(trading_df=trading_df, run_day=target_day)

    @classmethod
    def _load_scarcity_auto_profile(cls, market="CN"):
        market_key = str(market or "CN").strip().upper() or "CN"
        if market_key in cls._scarcity_auto_profile_cache:
            return cls._scarcity_auto_profile_cache[market_key]

        resolved = {
            "risk_weights": dict(cls.SCARCITY_AUTO_PROFILE_DEFAULTS["risk_weights"]),
            "thresholds": dict(cls.SCARCITY_AUTO_PROFILE_DEFAULTS["thresholds"]),
            "hysteresis": dict(cls.SCARCITY_AUTO_PROFILE_DEFAULTS["hysteresis"]),
            "confirmation_days": cls.SCARCITY_AUTO_PROFILE_DEFAULTS["confirmation_days"],
            "cooldown_days": cls.SCARCITY_AUTO_PROFILE_DEFAULTS["cooldown_days"],
            "missing_policy": dict(cls.SCARCITY_AUTO_PROFILE_DEFAULTS["missing_policy"]),
            "circuit_breaker": dict(cls.SCARCITY_AUTO_PROFILE_DEFAULTS["circuit_breaker"]),
            "legacy_signal_weights": dict(cls.SCARCITY_AUTO_PROFILE_DEFAULTS["legacy_signal_weights"]),
            "fallback_profile": cls.SCARCITY_AUTO_PROFILE_DEFAULTS["fallback_profile"],
        }

        config_path = (
            Path(settings.BASE_DIR)
            / "static"
            / "valuation_config"
            / f"scarcity_auto_profile_{market_key}.json"
        )
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as file_obj:
                config_data = json.load(file_obj)

            risk_weights = config_data.get("risk_weights") or {}
            for key in ["vol_z", "risk_disp", "data_gap", "dd_z"]:
                try:
                    value = float(risk_weights.get(key, resolved["risk_weights"][key]))
                except (TypeError, ValueError):
                    value = resolved["risk_weights"][key]
                if value < 0:
                    value = resolved["risk_weights"][key]
                resolved["risk_weights"][key] = value

            thresholds = config_data.get("thresholds") or {}
            for key in ["conservative_min", "balanced_min"]:
                try:
                    value = float(thresholds.get(key, resolved["thresholds"][key]))
                except (TypeError, ValueError):
                    value = resolved["thresholds"][key]
                value = max(0.0, min(1.0, value))
                resolved["thresholds"][key] = value

            hysteresis = config_data.get("hysteresis") or {}
            for key in ["up_shift", "down_shift"]:
                try:
                    value = float(hysteresis.get(key, resolved["hysteresis"][key]))
                except (TypeError, ValueError):
                    value = resolved["hysteresis"][key]
                value = max(0.0, min(0.5, value))
                resolved["hysteresis"][key] = value

            for key in ["confirmation_days", "cooldown_days"]:
                try:
                    raw_val = int(config_data.get(key, resolved[key]))
                except (TypeError, ValueError):
                    raw_val = resolved[key]
                resolved[key] = max(1, raw_val)

            missing_policy = config_data.get("missing_policy") or {}
            try:
                min_available = int(
                    missing_policy.get(
                        "min_available_indicators",
                        resolved["missing_policy"]["min_available_indicators"],
                    )
                )
            except (TypeError, ValueError):
                min_available = resolved["missing_policy"]["min_available_indicators"]
            min_available = max(1, min(4, min_available))
            resolved["missing_policy"]["min_available_indicators"] = min_available
            fallback_missing = str(
                missing_policy.get(
                    "fallback_profile",
                    resolved["missing_policy"]["fallback_profile"],
                )
                or ""
            ).strip().lower()
            if fallback_missing in ["conservative", "balanced", "aggressive", "off"]:
                resolved["missing_policy"]["fallback_profile"] = fallback_missing

            circuit_breaker = config_data.get("circuit_breaker") or {}
            resolved["circuit_breaker"]["enabled"] = bool(
                circuit_breaker.get("enabled", resolved["circuit_breaker"]["enabled"])
            )
            try:
                extreme_risk = float(
                    circuit_breaker.get(
                        "extreme_risk_min",
                        resolved["circuit_breaker"]["extreme_risk_min"],
                    )
                )
            except (TypeError, ValueError):
                extreme_risk = resolved["circuit_breaker"]["extreme_risk_min"]
            resolved["circuit_breaker"]["extreme_risk_min"] = max(0.0, min(1.0, extreme_risk))

            force_profile = str(
                circuit_breaker.get("force_profile", resolved["circuit_breaker"]["force_profile"])
                or ""
            ).strip().lower()
            if force_profile in ["conservative", "balanced", "aggressive", "off"]:
                resolved["circuit_breaker"]["force_profile"] = force_profile

            try:
                force_days = int(
                    circuit_breaker.get("force_days", resolved["circuit_breaker"]["force_days"])
                )
            except (TypeError, ValueError):
                force_days = resolved["circuit_breaker"]["force_days"]
            resolved["circuit_breaker"]["force_days"] = max(1, force_days)

            flags = circuit_breaker.get("extreme_flags")
            if isinstance(flags, list):
                normalized_flags = [
                    str(item).strip().lower() for item in flags if str(item).strip()
                ]
                if normalized_flags:
                    resolved["circuit_breaker"]["extreme_flags"] = normalized_flags

            legacy_signal_weights = config_data.get("legacy_signal_weights") or config_data.get("signal_weights") or {}
            for key in ["score", "confidence"]:
                try:
                    value = float(
                        legacy_signal_weights.get(key, resolved["legacy_signal_weights"][key])
                    )
                except (TypeError, ValueError):
                    value = resolved["legacy_signal_weights"][key]
                if value <= 0:
                    value = resolved["legacy_signal_weights"][key]
                resolved["legacy_signal_weights"][key] = value

            fallback_profile = str(config_data.get("fallback_profile") or "").strip().lower()
            if fallback_profile in ["conservative", "balanced", "aggressive", "off"]:
                resolved["fallback_profile"] = fallback_profile

        cls._scarcity_auto_profile_cache[market_key] = resolved
        return resolved

    @classmethod
    def _resolve_auto_target_profile(cls, risk_score, last_profile, auto_profile_cfg):
        thresholds = auto_profile_cfg.get("thresholds") or {}
        hysteresis = auto_profile_cfg.get("hysteresis") or {}

        conservative_min = cls._safe_float(thresholds.get("conservative_min"), 0.68)
        balanced_min = cls._safe_float(thresholds.get("balanced_min"), 0.42)
        up_shift = cls._safe_float(hysteresis.get("up_shift"), 0.03)
        down_shift = cls._safe_float(hysteresis.get("down_shift"), 0.03)

        conservative_min = max(0.0, min(1.0, conservative_min))
        balanced_min = max(0.0, min(1.0, balanced_min))
        up_shift = max(0.0, min(0.5, up_shift))
        down_shift = max(0.0, min(0.5, down_shift))
        if balanced_min > conservative_min:
            balanced_min = conservative_min

        conservative_enter = conservative_min + (up_shift if last_profile != "conservative" else -down_shift)
        balanced_enter = balanced_min + (
            up_shift if last_profile == "aggressive" else (-down_shift if last_profile == "balanced" else 0.0)
        )
        conservative_enter = max(0.0, min(1.0, conservative_enter))
        balanced_enter = max(0.0, min(1.0, balanced_enter))

        if risk_score >= conservative_enter:
            target = "conservative"
        elif risk_score >= balanced_enter:
            target = "balanced"
        else:
            target = "aggressive"
        return target, {
            "conservative_min": conservative_min,
            "balanced_min": balanced_min,
            "conservative_enter": conservative_enter,
            "balanced_enter": balanced_enter,
        }

    @classmethod
    def _resolve_auto_scarcity_profile(
        cls,
        scarcity_kwargs,
        auto_profile_cfg=None,
        tscode=None,
        market="CN",
        run_date=None,
    ):
        enabled = bool(scarcity_kwargs.get("enabled", True))
        if not enabled:
            return "off", "enabled_false"

        auto_profile_cfg = auto_profile_cfg or cls.SCARCITY_AUTO_PROFILE_DEFAULTS

        risk_weights = auto_profile_cfg.get("risk_weights") or {}
        indicator_names = ["vol_z", "risk_disp", "data_gap", "dd_z"]
        indicators = {name: cls._clamp_unit(scarcity_kwargs.get(name)) for name in indicator_names}

        score = cls._clamp_unit(scarcity_kwargs.get("score"))
        confidence = cls._clamp_unit(scarcity_kwargs.get("confidence"))
        legacy_weights = auto_profile_cfg.get("legacy_signal_weights") or {}
        score_weight = max(0.0, cls._safe_float(legacy_weights.get("score"), 1.0))
        confidence_weight = max(0.0, cls._safe_float(legacy_weights.get("confidence"), 1.0))
        legacy_risk = None
        if score is not None and confidence is not None:
            legacy_signal = (score * score_weight) * (confidence * confidence_weight)
            legacy_risk = cls._clamp_unit(1.0 - legacy_signal)

        if indicators.get("vol_z") is None and score is not None:
            indicators["vol_z"] = score
        if indicators.get("risk_disp") is None and confidence is not None:
            indicators["risk_disp"] = cls._clamp_unit(1.0 - confidence)
        if indicators.get("data_gap") is None and confidence is not None:
            indicators["data_gap"] = cls._clamp_unit(1.0 - confidence)
        if indicators.get("dd_z") is None and legacy_risk is not None:
            indicators["dd_z"] = legacy_risk

        weighted_sum = 0.0
        weight_sum = 0.0
        available = []
        for name in indicator_names:
            value = indicators.get(name)
            weight = max(0.0, cls._safe_float(risk_weights.get(name), 0.0))
            if value is None or weight <= 0:
                continue
            weighted_sum += value * weight
            weight_sum += weight
            available.append(name)
        risk_score = (weighted_sum / weight_sum) if weight_sum > 0 else None

        missing_policy = auto_profile_cfg.get("missing_policy") or {}
        min_available = int(cls._safe_float(missing_policy.get("min_available_indicators"), 4) or 4)
        min_available = max(1, min(4, min_available))
        missing_fallback = str(
            missing_policy.get("fallback_profile", auto_profile_cfg.get("fallback_profile", "balanced"))
            or "balanced"
        ).strip().lower()
        if missing_fallback not in ["conservative", "balanced", "aggressive", "off"]:
            missing_fallback = "balanced"

        run_day = cls._parse_run_date(run_date)
        state_path, state_payload = cls._load_scarcity_auto_state(market=market)
        profile_state = (state_payload.get("profiles") or {}).get(tscode or "", {}) if tscode else {}
        last_profile = str(profile_state.get("last_profile") or "").strip().lower() or None
        pending_profile = str(profile_state.get("pending_profile") or "").strip().lower() or None
        pending_count = int(cls._safe_float(profile_state.get("pending_count"), 0) or 0)
        cooldown_until = cls._parse_run_date(profile_state.get("cooldown_until")) if profile_state.get("cooldown_until") else None
        force_until = cls._parse_run_date(profile_state.get("force_conservative_until")) if profile_state.get("force_conservative_until") else None

        circuit_breaker = auto_profile_cfg.get("circuit_breaker") or {}
        breaker_enabled = bool(circuit_breaker.get("enabled", True))
        breaker_min = cls._safe_float(circuit_breaker.get("extreme_risk_min"), 0.90)
        breaker_min = max(0.0, min(1.0, breaker_min))
        breaker_profile = str(circuit_breaker.get("force_profile") or "conservative").strip().lower() or "conservative"
        if breaker_profile not in ["conservative", "balanced", "aggressive", "off"]:
            breaker_profile = "conservative"
        breaker_days = int(cls._safe_float(circuit_breaker.get("force_days"), 3) or 3)
        breaker_days = max(1, breaker_days)
        extreme_flags = [str(item).strip().lower() for item in (circuit_breaker.get("extreme_flags") or []) if str(item).strip()]
        extreme_market = bool(scarcity_kwargs.get("extreme_market", False))
        status_flags = [str(item).strip().lower() for item in (scarcity_kwargs.get("status_flags") or []) if str(item).strip()]
        breaker_by_flag = bool(extreme_flags and any(flag in status_flags for flag in extreme_flags))
        breaker_by_risk = risk_score is not None and risk_score >= breaker_min

        reason_parts = []
        if breaker_enabled and (breaker_by_flag or extreme_market or breaker_by_risk):
            force_until = run_day + timedelta(days=breaker_days - 1)
            effective_profile = breaker_profile
            reason_parts.append("auto_mode=circuit_breaker_triggered")
        elif force_until is not None and run_day <= force_until:
            effective_profile = breaker_profile
            reason_parts.append("auto_mode=circuit_breaker_window")
        elif len(available) < min_available or risk_score is None:
            effective_profile = missing_fallback
            reason_parts.append("auto_mode=missing_indicator_fallback")
            pending_profile = None
            pending_count = 0
        else:
            target_profile, threshold_meta = cls._resolve_auto_target_profile(
                risk_score=risk_score,
                last_profile=last_profile,
                auto_profile_cfg=auto_profile_cfg,
            )
            reason_parts.append(
                f"risk={risk_score:.4f};thresholds=({threshold_meta['conservative_min']:.3f},{threshold_meta['balanced_min']:.3f});"
                f"hyst=({threshold_meta['conservative_enter']:.3f},{threshold_meta['balanced_enter']:.3f})"
            )

            if last_profile is None:
                effective_profile = target_profile
                reason_parts.append("auto_mode=cold_start")
                pending_profile = None
                pending_count = 0
                cooldown_until = None
            elif cooldown_until is not None and run_day <= cooldown_until and target_profile != last_profile:
                effective_profile = last_profile
                reason_parts.append("auto_mode=cooldown_hold")
            elif target_profile == last_profile:
                effective_profile = last_profile
                pending_profile = None
                pending_count = 0
                reason_parts.append("auto_mode=stable")
            else:
                if pending_profile == target_profile:
                    pending_count += 1
                else:
                    pending_profile = target_profile
                    pending_count = 1

                confirmation_days = int(cls._safe_float(auto_profile_cfg.get("confirmation_days"), 3) or 3)
                confirmation_days = max(1, confirmation_days)
                if pending_count >= confirmation_days:
                    effective_profile = target_profile
                    pending_profile = None
                    pending_count = 0
                    cooldown_days = int(cls._safe_float(auto_profile_cfg.get("cooldown_days"), 5) or 5)
                    cooldown_days = max(1, cooldown_days)
                    cooldown_until = run_day + timedelta(days=cooldown_days)
                    reason_parts.append("auto_mode=confirmed_switch")
                else:
                    effective_profile = last_profile
                    reason_parts.append(
                        f"auto_mode=pending_confirm({pending_count}/{int(cls._safe_float(auto_profile_cfg.get('confirmation_days'), 3) or 3)})"
                    )

        updated_state = {
            "last_profile": effective_profile,
            "pending_profile": pending_profile,
            "pending_count": pending_count,
            "cooldown_until": cls._format_run_date(cooldown_until),
            "force_conservative_until": cls._format_run_date(force_until),
            "last_risk_score": round(risk_score, 6) if risk_score is not None else None,
            "last_date": cls._format_run_date(run_day),
        }

        if tscode:
            state_payload.setdefault("profiles", {})[tscode] = updated_state
            cls._save_scarcity_auto_state(state_path, state_payload)

        reason_parts.append(f"indicators={','.join(available) if available else 'none'}")
        reason_parts.append(
            "values=(vol_z:{0},risk_disp:{1},data_gap:{2},dd_z:{3})".format(
                indicators.get("vol_z"),
                indicators.get("risk_disp"),
                indicators.get("data_gap"),
                indicators.get("dd_z"),
            )
        )
        if legacy_risk is not None:
            reason_parts.append(f"legacy_risk={legacy_risk:.4f}")
        reason_parts.append(
            "weights=(vol_z:{0:.3f},risk_disp:{1:.3f},data_gap:{2:.3f},dd_z:{3:.3f})".format(
                cls._safe_float(risk_weights.get("vol_z"), 0.0),
                cls._safe_float(risk_weights.get("risk_disp"), 0.0),
                cls._safe_float(risk_weights.get("data_gap"), 0.0),
                cls._safe_float(risk_weights.get("dd_z"), 0.0),
            )
        )
        return effective_profile, ";".join(reason_parts)

    @classmethod
    def _apply_scarcity_profile(
        cls,
        valuation_params,
        scarcity_profile,
        market="CN",
        tscode=None,
        trade_date=None,
    ):
        requested_profile = (scarcity_profile or "").strip().lower()
        merged, filled_keys = cls._autofill_scarcity_kwargs(valuation_params.get("scarcity_kwargs"))

        effective_profile = requested_profile or None
        auto_reason = None
        auto_profile_cfg = cls._load_scarcity_auto_profile(market=market)
        if requested_profile == "auto":
            runtime_indicators = cls._compute_auto_risk_indicators(
                tscode=tscode,
                trade_date=trade_date,
            )
            injected_auto_indicator_keys = []
            for key, value in (runtime_indicators or {}).items():
                if merged.get(key) is None:
                    merged[key] = value
                    injected_auto_indicator_keys.append(key)
            effective_profile, auto_reason = cls._resolve_auto_scarcity_profile(
                merged,
                auto_profile_cfg=auto_profile_cfg,
                tscode=tscode,
                market=market,
                run_date=trade_date,
            )
            if not effective_profile:
                effective_profile = auto_profile_cfg.get("fallback_profile") or "balanced"
        else:
            injected_auto_indicator_keys = []

        preset = cls.SCARCITY_PROFILE_PRESETS.get(effective_profile or "")
        if preset is not None:
            merged.update(preset)

        valuation_params["scarcity_kwargs"] = merged
        return valuation_params, {
            "requested_profile": requested_profile or None,
            "effective_profile": effective_profile,
            "auto_reason": auto_reason,
            "autofilled_keys": filled_keys,
            "auto_injected_indicator_keys": injected_auto_indicator_keys,
            "auto_profile_cfg": auto_profile_cfg,
        }
