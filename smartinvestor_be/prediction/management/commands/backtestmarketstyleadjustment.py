import json
import random
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from api.views import _normalize_valuation_method_name
from valuation.services.valuation_summary import summarize_buy_candidate
from datastore.models import StockTradingHistory
from prediction.management.commands.exportlocalvaluationcompare import _build_local_variant_payload
from prediction.management.commands.prefillvaluationsnapshot import _normalize_valuation_variant
from valuation.models import StockValuationSnapshot
from valuation.services.valuation_engine import get_stock_valuation_snapshot


PROJECT_ROOT = Path(__file__).resolve().parents[3]


STYLE_PARAMS = {
    "unified": {
        "risk_blend_map": {0: 0.75, 1: 0.6, 2: 0.45, 3: 0.35},
        "risk_cap_map": {2: 0.85, 3: 0.8},
        "quality_penalties": {
            "netprofit_neg": 0.78,
            "fcff_neg": 0.85,
            "pe_missing": 0.92,
            "growth_neg": 0.9,
        },
        "quality_bounds": (0.5, 1.05),
    },
    "industry": {
        "defensive": {
            "risk_blend_map": {0: 0.68, 1: 0.55, 2: 0.42, 3: 0.32},
            "risk_cap_map": {2: 0.83, 3: 0.78},
            "quality_penalties": {
                "netprofit_neg": 0.8,
                "fcff_neg": 0.88,
                "pe_missing": 0.94,
                "growth_neg": 0.93,
            },
            "quality_bounds": (0.55, 1.03),
        },
        "growth": {
            "risk_blend_map": {0: 0.9, 1: 0.8, 2: 0.65, 3: 0.55},
            "risk_cap_map": {2: 0.95, 3: 0.9},
            "quality_penalties": {
                "netprofit_neg": 0.92,
                "fcff_neg": 0.94,
                "pe_missing": 0.98,
                "growth_neg": 0.97,
            },
            "quality_bounds": (0.7, 1.1),
        },
        "growth_military_aerospace": {
            "risk_blend_map": {0: 0.98, 1: 0.96, 2: 0.93, 3: 0.9},
            "risk_cap_map": {},
            "quality_penalties": {
                "netprofit_neg": 0.995,
                "fcff_neg": 0.995,
                "pe_missing": 1.0,
                "growth_neg": 0.998,
            },
            "quality_bounds": (0.99, 1.01),
        },
        "growth_military_electronics": {
            "risk_blend_map": {0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0},
            "risk_cap_map": {},
            "quality_penalties": {
                "netprofit_neg": 1.0,
                "fcff_neg": 1.0,
                "pe_missing": 1.0,
                "growth_neg": 1.0,
            },
            "quality_bounds": (1.0, 1.0),
        },
        "growth_semis_design": {
            "risk_blend_map": {0: 0.92, 1: 0.83, 2: 0.68, 3: 0.57},
            "risk_cap_map": {2: 0.96, 3: 0.9},
            "quality_penalties": {
                "netprofit_neg": 0.94,
                "fcff_neg": 0.95,
                "pe_missing": 0.99,
                "growth_neg": 0.98,
            },
            "quality_bounds": (0.72, 1.12),
        },
        "growth_semis_software": {
            "risk_blend_map": {0: 0.95, 1: 0.86, 2: 0.7, 3: 0.58},
            "risk_cap_map": {2: 0.97, 3: 0.91},
            "quality_penalties": {
                "netprofit_neg": 0.95,
                "fcff_neg": 0.96,
                "pe_missing": 1.0,
                "growth_neg": 0.98,
            },
            "quality_bounds": (0.74, 1.14),
        },
        "growth_semis_equipment": {
            "risk_blend_map": {0: 0.86, 1: 0.76, 2: 0.62, 3: 0.52},
            "risk_cap_map": {2: 0.93, 3: 0.88},
            "quality_penalties": {
                "netprofit_neg": 0.91,
                "fcff_neg": 0.93,
                "pe_missing": 0.97,
                "growth_neg": 0.96,
            },
            "quality_bounds": (0.68, 1.08),
        },
        "growth_semis_materials": {
            "risk_blend_map": {0: 0.84, 1: 0.74, 2: 0.6, 3: 0.5},
            "risk_cap_map": {2: 0.92, 3: 0.87},
            "quality_penalties": {
                "netprofit_neg": 0.9,
                "fcff_neg": 0.92,
                "pe_missing": 0.97,
                "growth_neg": 0.95,
            },
            "quality_bounds": (0.66, 1.08),
        },
        "growth_semis_manufacturing": {
            "risk_blend_map": {0: 0.88, 1: 0.78, 2: 0.64, 3: 0.54},
            "risk_cap_map": {2: 0.94, 3: 0.89},
            "quality_penalties": {
                "netprofit_neg": 0.9,
                "fcff_neg": 0.92,
                "pe_missing": 0.97,
                "growth_neg": 0.96,
            },
            "quality_bounds": (0.68, 1.09),
        },
        "cyclical": {
            "risk_blend_map": {0: 0.82, 1: 0.72, 2: 0.58, 3: 0.48},
            "risk_cap_map": {2: 0.92, 3: 0.87},
            "quality_penalties": {
                "netprofit_neg": 0.88,
                "fcff_neg": 0.91,
                "pe_missing": 0.96,
                "growth_neg": 0.95,
            },
            "quality_bounds": (0.62, 1.08),
        },
        "balanced": {
            "risk_blend_map": {0: 0.8, 1: 0.68, 2: 0.54, 3: 0.44},
            "risk_cap_map": {2: 0.9, 3: 0.85},
            "quality_penalties": {
                "netprofit_neg": 0.85,
                "fcff_neg": 0.9,
                "pe_missing": 0.95,
                "growth_neg": 0.94,
            },
            "quality_bounds": (0.6, 1.08),
        },
    },
}


def _resolve_style_params(style_profile, industry_group):
    profile = str(style_profile or "unified").strip().lower()
    group = str(industry_group or "balanced").strip().lower()
    if profile == "adaptive":
        group_params = STYLE_PARAMS["industry"].get(group)
        if not group_params:
            group = "balanced"
            group_params = STYLE_PARAMS["industry"][group]
        return group_params, "adaptive", group
    if profile != "industry":
        return STYLE_PARAMS["unified"], "unified", "balanced"
    group_params = STYLE_PARAMS["industry"].get(group)
    if not group_params:
        group = "balanced"
        group_params = STYLE_PARAMS["industry"][group]
    return group_params, "industry", group


def _detect_market_phase(regime):
    risk_score = int(regime.get("risk_score") or 0)
    mom_60 = regime.get("mom_60")
    drawdown_120 = regime.get("drawdown_120")

    if risk_score >= 2:
        return "risk_off"
    if mom_60 is not None and mom_60 > 0.12 and (drawdown_120 is None or drawdown_120 > -0.1):
        return "risk_on"
    if mom_60 is not None and mom_60 > -0.02 and risk_score <= 1:
        return "recovery"
    return "neutral"


def _adaptive_phase_controls(phase, industry_group):
    group = str(industry_group or "balanced").lower()
    phase_maps = {
        "defensive": {
            "risk_on": {"blend_shift": 0.03, "quality_factor": 1.01, "cap_factor": 1.02},
            "recovery": {"blend_shift": 0.01, "quality_factor": 1.0, "cap_factor": 1.0},
            "neutral": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "risk_off": {"blend_shift": -0.08, "quality_factor": 0.97, "cap_factor": 0.95},
        },
        "growth": {
            "risk_on": {"blend_shift": 0.12, "quality_factor": 1.05, "cap_factor": 1.08},
            "recovery": {"blend_shift": 0.06, "quality_factor": 1.03, "cap_factor": 1.04},
            "neutral": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "risk_off": {"blend_shift": -0.2, "quality_factor": 0.9, "cap_factor": 0.88},
        },
        "growth_military_aerospace": {
            "risk_on": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "recovery": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "neutral": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "risk_off": {"blend_shift": -0.03, "quality_factor": 0.995, "cap_factor": 1.0},
        },
        "growth_military_electronics": {
            "risk_on": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "recovery": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "neutral": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "risk_off": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
        },
        "growth_semis_design": {
            "risk_on": {"blend_shift": 0.14, "quality_factor": 1.06, "cap_factor": 1.1},
            "recovery": {"blend_shift": 0.07, "quality_factor": 1.04, "cap_factor": 1.05},
            "neutral": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "risk_off": {"blend_shift": -0.22, "quality_factor": 0.89, "cap_factor": 0.87},
        },
        "growth_semis_software": {
            "risk_on": {"blend_shift": 0.16, "quality_factor": 1.07, "cap_factor": 1.11},
            "recovery": {"blend_shift": 0.08, "quality_factor": 1.05, "cap_factor": 1.06},
            "neutral": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "risk_off": {"blend_shift": -0.24, "quality_factor": 0.88, "cap_factor": 0.86},
        },
        "growth_semis_equipment": {
            "risk_on": {"blend_shift": 0.1, "quality_factor": 1.04, "cap_factor": 1.06},
            "recovery": {"blend_shift": 0.05, "quality_factor": 1.02, "cap_factor": 1.03},
            "neutral": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "risk_off": {"blend_shift": -0.16, "quality_factor": 0.92, "cap_factor": 0.9},
        },
        "growth_semis_materials": {
            "risk_on": {"blend_shift": 0.09, "quality_factor": 1.03, "cap_factor": 1.05},
            "recovery": {"blend_shift": 0.04, "quality_factor": 1.01, "cap_factor": 1.02},
            "neutral": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "risk_off": {"blend_shift": -0.15, "quality_factor": 0.92, "cap_factor": 0.9},
        },
        "growth_semis_manufacturing": {
            "risk_on": {"blend_shift": 0.11, "quality_factor": 1.04, "cap_factor": 1.07},
            "recovery": {"blend_shift": 0.05, "quality_factor": 1.02, "cap_factor": 1.03},
            "neutral": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "risk_off": {"blend_shift": -0.18, "quality_factor": 0.91, "cap_factor": 0.89},
        },
        "cyclical": {
            "risk_on": {"blend_shift": 0.08, "quality_factor": 1.03, "cap_factor": 1.05},
            "recovery": {"blend_shift": 0.03, "quality_factor": 1.01, "cap_factor": 1.02},
            "neutral": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "risk_off": {"blend_shift": -0.12, "quality_factor": 0.94, "cap_factor": 0.92},
        },
        "balanced": {
            "risk_on": {"blend_shift": 0.06, "quality_factor": 1.02, "cap_factor": 1.03},
            "recovery": {"blend_shift": 0.03, "quality_factor": 1.01, "cap_factor": 1.01},
            "neutral": {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0},
            "risk_off": {"blend_shift": -0.1, "quality_factor": 0.95, "cap_factor": 0.93},
        },
    }
    group_map = phase_maps.get(group, phase_maps["balanced"])
    return group_map.get(phase, group_map["neutral"])


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_div(numerator, denominator):
    if denominator in (None, 0):
        return None
    return numerator / denominator


def _safe_metric_delta(adjusted, baseline):
    if adjusted is None or baseline is None:
        return None
    return adjusted - baseline


def _safe_metric_improvement_ratio(baseline, adjusted):
    if baseline in (None, 0) or adjusted is None:
        return None
    return (baseline - adjusted) / baseline


def _clamp(value, lower, upper):
    return max(lower, min(upper, value))


def _variant_composite_gap(summary_by_variant, variant, current_price):
    if current_price in (None, 0):
        return None
    variant_summary = (summary_by_variant or {}).get(variant) or {}
    composite_price = _to_float(variant_summary.get("composite_valuation_price"))
    if composite_price is None:
        return None
    return abs(composite_price - float(current_price)) / abs(float(current_price))


def _pick_active_variant(summary_by_variant, variant_meta, current_price=None):
    if not summary_by_variant:
        return None

    available = set(summary_by_variant.keys())
    sw_variants = [v for v in available if str(v).startswith("sw_l3_baseline|")]
    business_variants = [v for v in available if str(v).startswith("business_match|")]
    if business_variants:
        business_variants.sort(key=lambda v: -(variant_meta.get(v, {}).get("max_match_score") or 0.0))

    if sw_variants:
        selected_sw = sorted(sw_variants)[0]
        if business_variants:
            selected_business = business_variants[0]
            business_score = float(variant_meta.get(selected_business, {}).get("max_match_score") or 0.0)
            sw_gap = _variant_composite_gap(summary_by_variant, selected_sw, current_price)
            business_gap = _variant_composite_gap(summary_by_variant, selected_business, current_price)

            # Allow strong business-match variants to override SW baseline when
            # they are materially closer to spot price.
            if (
                business_score >= 20.0
                and sw_gap is not None
                and business_gap is not None
                and business_gap <= (sw_gap - 0.08)
            ):
                return selected_business

        return selected_sw

    if business_variants:
        return business_variants[0]

    if "default" in available:
        return "default"

    return sorted(available)[0]


def _build_regime_features(price_series, idx):
    if idx < 2:
        return {"mom_60": None, "vol_20": None, "drawdown_120": None, "risk_score": 0}

    current_price = price_series[idx][1]

    mom_60 = None
    if idx >= 60:
        base = price_series[idx - 60][1]
        mom_60 = _safe_div(current_price - base, base)

    vol_20 = None
    if idx >= 20:
        returns = []
        for i in range(idx - 19, idx + 1):
            prev = price_series[i - 1][1]
            curr = price_series[i][1]
            if prev and prev > 0:
                returns.append((curr - prev) / prev)
        if returns:
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / len(returns)
            vol_20 = variance ** 0.5 * (252 ** 0.5)

    drawdown_120 = None
    if idx >= 120:
        window = [p for _, p in price_series[idx - 119 : idx + 1]]
        peak = max(window) if window else None
        if peak and peak > 0:
            drawdown_120 = (current_price - peak) / peak

    risk_score = 0
    if mom_60 is not None and mom_60 < -0.1:
        risk_score += 1
    if vol_20 is not None and vol_20 > 0.45:
        risk_score += 1
    if drawdown_120 is not None and drawdown_120 < -0.25:
        risk_score += 1

    return {
        "mom_60": mom_60,
        "vol_20": vol_20,
        "drawdown_120": drawdown_120,
        "risk_score": risk_score,
    }


def _build_quality_multiplier(snapshot, style_params):
    quality = 1.0
    netprofit = _to_float(snapshot.get("netprofit"))
    fcff = _to_float(snapshot.get("fcff"))
    pe_ttm = _to_float(snapshot.get("pe_ttm"))
    growth = _to_float(snapshot.get("peg_growth_yoy_pct"))

    penalties = style_params.get("quality_penalties") or {}
    if netprofit is not None and netprofit < 0:
        quality *= float(penalties.get("netprofit_neg", 1.0))
    if fcff is not None and fcff < 0:
        quality *= float(penalties.get("fcff_neg", 1.0))
    if pe_ttm is None:
        quality *= float(penalties.get("pe_missing", 1.0))
    if growth is not None and growth < 0:
        quality *= float(penalties.get("growth_neg", 1.0))

    lower, upper = style_params.get("quality_bounds") or (0.5, 1.05)
    return max(float(lower), min(float(upper), quality))


def _apply_market_style_adjustment(composite_price, conservative_price, snapshot, regime, style_params, style_profile, industry_group):
    if composite_price is None:
        return None, {}
    if composite_price <= 0:
        return composite_price, {"note": "non_positive_composite"}

    risk_score = int(regime.get("risk_score") or 0)
    risk_blend_map = style_params.get("risk_blend_map") or {0: 0.75, 1: 0.6, 2: 0.45, 3: 0.35}
    blend_weight = float(risk_blend_map.get(risk_score, min(risk_blend_map.values())))
    anchor_price = conservative_price if conservative_price is not None else composite_price

    phase = "neutral"
    phase_controls = {"blend_shift": 0.0, "quality_factor": 1.0, "cap_factor": 1.0}
    if style_profile == "adaptive":
        phase = _detect_market_phase(regime)
        phase_controls = _adaptive_phase_controls(phase, industry_group)
        blend_weight = _clamp(blend_weight + float(phase_controls.get("blend_shift", 0.0)), 0.2, 0.95)

    blended_price = blend_weight * composite_price + (1.0 - blend_weight) * anchor_price

    quality_multiplier = _build_quality_multiplier(snapshot, style_params)
    quality_multiplier = quality_multiplier * float(phase_controls.get("quality_factor", 1.0))
    lower, upper = style_params.get("quality_bounds") or (0.5, 1.05)
    quality_multiplier = _clamp(quality_multiplier, float(lower), float(upper))
    adjusted = blended_price * quality_multiplier

    risk_cap_map = style_params.get("risk_cap_map") or {}
    cap_multiplier = risk_cap_map.get(risk_score)
    if cap_multiplier is not None:
        cap_multiplier = float(cap_multiplier) * float(phase_controls.get("cap_factor", 1.0))
        adjusted = min(adjusted, composite_price * cap_multiplier)

    return adjusted, {
        "blend_weight": blend_weight,
        "anchor_price": anchor_price,
        "blended_price": blended_price,
        "quality_multiplier": quality_multiplier,
        "risk_score": risk_score,
        "phase": phase,
    }


def _load_price_series(ts_code, year, freq="D"):
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    rows = list(
        StockTradingHistory.objects.filter(
            ts_code=ts_code,
            freq=freq,
            trade_date__gte=start,
            trade_date__lte=end,
        )
        .order_by("trade_date")
        .values("trade_date", "close_qfq", "close")
    )
    series = []
    for row in rows:
        price = _to_float(row.get("close_qfq"))
        if price is None:
            price = _to_float(row.get("close"))
        if price is None:
            continue
        series.append((row.get("trade_date"), price))
    return series


def _load_snapshot_rows(ts_code, snapshot_trade_date, market="CN"):
    rows = list(
        StockValuationSnapshot.objects.filter(
            ts_code=ts_code,
            trade_date=snapshot_trade_date,
            market=market,
        )
        .order_by("valuation_variant", "valuation_method", "-updated_at")
        .values(
            "valuation_variant",
            "valuation_method",
            "valuation_price",
            "match_score",
            "compare_group",
        )
    )
    return rows


def _build_summary_by_variant(snapshot_rows, current_price, band_pct):
    rows_by_variant = {}
    variant_meta = {}
    for row in snapshot_rows:
        method = _normalize_valuation_method_name(row.get("valuation_method"))
        if not method:
            continue
        variant = _normalize_valuation_variant(row.get("valuation_variant"), fallback="default")
        valuation_price = _to_float(row.get("valuation_price"))
        if valuation_price is None:
            continue
        method_map = rows_by_variant.setdefault(variant, {})
        method_map[method] = {
            "valuation_price": valuation_price,
        }

        score = _to_float(row.get("match_score"))
        meta = variant_meta.setdefault(
            variant,
            {
                "max_match_score": None,
                "compare_group": row.get("compare_group"),
            },
        )
        if score is not None and (meta.get("max_match_score") is None or score > meta.get("max_match_score")):
            meta["max_match_score"] = score

    summary_by_variant = {
        variant: summarize_buy_candidate(
            current_price=current_price,
            method_map=method_map,
            band_pct=band_pct,
        )
        for variant, method_map in rows_by_variant.items()
    }
    return summary_by_variant, variant_meta


def _build_summary_by_variant_from_recompute(ts_code, sample_date, current_price, band_pct, freq):
    payload = _build_local_variant_payload(
        ts_code=ts_code,
        trade_date=sample_date.isoformat(),
        report_end_date=None,
        business_topn=3,
        band_pct=band_pct,
        freq=freq,
        asof_trade_date=sample_date.isoformat(),
    )
    summary_by_variant = payload.get("summary_by_variant") or {}
    variant_meta = {}
    for item in payload.get("valuation_variants") or []:
        variant = item.get("valuation_variant")
        if not variant:
            continue
        variant_meta[variant] = {
            "max_match_score": item.get("match_score"),
            "compare_group": item.get("compare_group"),
        }
    if current_price is not None:
        return summary_by_variant, variant_meta
    return summary_by_variant, variant_meta


class Command(BaseCommand):
    help = "Random-sample backtest for market-style adjusted valuation against future realized prices."

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, required=True, help="TS code, e.g. 688599.SH")
        parser.add_argument("--year", type=int, default=2025, help="Backtest year, default 2025")
        parser.add_argument("--sample-size", type=int, default=30, help="Random sample size, default 30")
        parser.add_argument("--seed", type=int, default=42, help="Random seed, default 42")
        parser.add_argument("--horizon", type=int, default=20, help="Future trading-day horizon, default 20")
        parser.add_argument("--market", type=str, default="CN", help="Market code, default CN")
        parser.add_argument("--freq", type=str, default="D", help="Trading frequency, default D")
        parser.add_argument("--valuation-band-pct", type=float, default=0.1, help="Band percent for summary calculation")
        parser.add_argument(
            "--valuation-source",
            type=str,
            default="auto",
            help="Valuation source mode: auto or snapshot or recompute",
        )
        parser.add_argument(
            "--style-profile",
            type=str,
            default="unified",
            help="Style profile: unified or industry or adaptive",
        )
        parser.add_argument(
            "--industry-group",
            type=str,
            default="balanced",
            help="Industry group used when style-profile=industry: defensive/growth/growth_military_aerospace/growth_military_electronics/growth_semis_design/growth_semis_software/growth_semis_equipment/growth_semis_materials/growth_semis_manufacturing/cyclical/balanced",
        )
        parser.add_argument("--output", type=str, default=None, help="Optional output file path")

    def handle(self, *args, **options):
        ts_code = str(options.get("tscode") or "").strip().upper()
        year = int(options.get("year") or 2025)
        sample_size = int(options.get("sample_size") or 30)
        seed = int(options.get("seed") or 42)
        horizon = int(options.get("horizon") or 20)
        market = str(options.get("market") or "CN").strip().upper() or "CN"
        freq = str(options.get("freq") or "D").strip().upper() or "D"
        band_pct = float(options.get("valuation_band_pct") or 0.1)
        valuation_source = str(options.get("valuation_source") or "auto").strip().lower()
        style_profile = str(options.get("style_profile") or "unified").strip().lower()
        industry_group = str(options.get("industry_group") or "balanced").strip().lower()
        style_params, resolved_profile, resolved_group = _resolve_style_params(style_profile, industry_group)

        if not ts_code:
            raise CommandError("--tscode is required")
        if sample_size <= 0:
            raise CommandError("--sample-size must be > 0")
        if horizon <= 0:
            raise CommandError("--horizon must be > 0")

        price_series = _load_price_series(ts_code=ts_code, year=year, freq=freq)
        if len(price_series) <= horizon + 5:
            raise CommandError("Insufficient trading history for requested horizon.")

        trade_dates = [d for d, _ in price_series]
        prices = [p for _, p in price_series]

        snapshot_dates = list(
            StockValuationSnapshot.objects.filter(
                ts_code=ts_code,
                market=market,
                trade_date__gte=f"{year}-01-01",
                trade_date__lte=f"{year}-12-31",
            )
            .values_list("trade_date", flat=True)
            .distinct()
        )
        snapshot_dates = sorted(snapshot_dates)
        if valuation_source == "snapshot" and not snapshot_dates:
            raise CommandError("No valuation snapshots found for the requested year.")

        sample_candidates = trade_dates[:-horizon]
        if not sample_candidates:
            raise CommandError("No candidate sample dates after applying horizon.")

        random.seed(seed)
        sample_dates = random.sample(sample_candidates, min(sample_size, len(sample_candidates)))
        sample_dates.sort()

        detail_rows = []
        baseline_abs_errors = []
        adjusted_abs_errors = []
        baseline_apes = []
        adjusted_apes = []
        improve_count = 0
        source_counts = {"snapshot": 0, "recompute": 0}

        for sample_date in sample_dates:
            idx = trade_dates.index(sample_date)
            future_date = trade_dates[idx + horizon]
            current_price = prices[idx]
            future_price = prices[idx + horizon]

            usable_snapshot_dates = [d for d in snapshot_dates if d <= sample_date]
            snapshot_trade_date = usable_snapshot_dates[-1] if usable_snapshot_dates else None

            summary_by_variant = {}
            variant_meta = {}
            valuation_source_used = None
            if valuation_source in {"auto", "snapshot"} and snapshot_trade_date is not None:
                snapshot_rows = _load_snapshot_rows(ts_code, snapshot_trade_date=snapshot_trade_date, market=market)
                summary_by_variant, variant_meta = _build_summary_by_variant(snapshot_rows, current_price, band_pct)
                if summary_by_variant:
                    valuation_source_used = "snapshot"

            if (valuation_source == "recompute") or (valuation_source == "auto" and not summary_by_variant):
                summary_by_variant, variant_meta = _build_summary_by_variant_from_recompute(
                    ts_code=ts_code,
                    sample_date=sample_date,
                    current_price=current_price,
                    band_pct=band_pct,
                    freq=freq,
                )
                if summary_by_variant:
                    valuation_source_used = "recompute"

            if not summary_by_variant:
                continue

            source_counts[valuation_source_used] = source_counts.get(valuation_source_used, 0) + 1
            active_variant = _pick_active_variant(summary_by_variant, variant_meta, current_price=current_price)
            if not active_variant:
                continue

            active_summary = summary_by_variant.get(active_variant) or {}
            baseline_price = _to_float(active_summary.get("composite_valuation_price"))
            conservative_price = _to_float(active_summary.get("conservative_valuation_price"))
            if baseline_price is None:
                continue

            snapshot = get_stock_valuation_snapshot(
                ts_code=ts_code,
                trade_date=sample_date.isoformat(),
                strict_express_match=True,
                express_max_age_days=180,
            )
            regime = _build_regime_features(price_series, idx)
            adjusted_price, adjust_meta = _apply_market_style_adjustment(
                baseline_price,
                conservative_price,
                snapshot,
                regime,
                style_params,
                resolved_profile,
                resolved_group,
            )

            baseline_abs = abs(baseline_price - future_price)
            baseline_abs_errors.append(baseline_abs)
            baseline_ape = abs((baseline_price - future_price) / future_price) if future_price else None
            if baseline_ape is not None:
                baseline_apes.append(baseline_ape)

            adjusted_abs = None
            adjusted_ape = None
            if adjusted_price is not None:
                adjusted_abs = abs(adjusted_price - future_price)
                adjusted_abs_errors.append(adjusted_abs)
                adjusted_ape = abs((adjusted_price - future_price) / future_price) if future_price else None
                if adjusted_ape is not None:
                    adjusted_apes.append(adjusted_ape)
                if adjusted_abs < baseline_abs:
                    improve_count += 1

            detail_rows.append(
                {
                    "sample_trade_date": sample_date,
                    "snapshot_trade_date_used": snapshot_trade_date,
                    "valuation_source_used": valuation_source_used,
                    "future_trade_date": future_date,
                    "current_price": round(current_price, 4),
                    "future_price": round(future_price, 4),
                    "active_variant": active_variant,
                    "baseline_composite_price": round(baseline_price, 4),
                    "baseline_conservative_price": round(conservative_price, 4) if conservative_price is not None else None,
                    "adjusted_market_style_price": round(adjusted_price, 4) if adjusted_price is not None else None,
                    "baseline_abs_error": round(baseline_abs, 4),
                    "adjusted_abs_error": round(adjusted_abs, 4) if adjusted_abs is not None else None,
                    "baseline_ape": round(baseline_ape, 6) if baseline_ape is not None else None,
                    "adjusted_ape": round(adjusted_ape, 6) if adjusted_ape is not None else None,
                    "regime": {
                        "mom_60": round(regime.get("mom_60"), 6) if regime.get("mom_60") is not None else None,
                        "vol_20": round(regime.get("vol_20"), 6) if regime.get("vol_20") is not None else None,
                        "drawdown_120": round(regime.get("drawdown_120"), 6) if regime.get("drawdown_120") is not None else None,
                        "risk_score": regime.get("risk_score"),
                    },
                    "adjustment_meta": {
                        "blend_weight": round(adjust_meta.get("blend_weight"), 4)
                        if adjust_meta.get("blend_weight") is not None
                        else None,
                        "quality_multiplier": round(adjust_meta.get("quality_multiplier"), 4)
                        if adjust_meta.get("quality_multiplier") is not None
                        else None,
                        "anchor_price": round(adjust_meta.get("anchor_price"), 4)
                        if adjust_meta.get("anchor_price") is not None
                        else None,
                        "phase": adjust_meta.get("phase"),
                        "style_profile": resolved_profile,
                        "industry_group": resolved_group,
                    },
                    "snapshot_quality": {
                        "netprofit": _to_float(snapshot.get("netprofit")),
                        "fcff": _to_float(snapshot.get("fcff")),
                        "pe_ttm": _to_float(snapshot.get("pe_ttm")),
                        "peg_growth_yoy_pct": _to_float(snapshot.get("peg_growth_yoy_pct")),
                        "profit_data_source": snapshot.get("profit_data_source"),
                    },
                }
            )

        if not detail_rows:
            raise CommandError("No usable sampled rows could be evaluated.")

        mae_baseline = sum(baseline_abs_errors) / len(baseline_abs_errors) if baseline_abs_errors else None
        mae_adjusted = sum(adjusted_abs_errors) / len(adjusted_abs_errors) if adjusted_abs_errors else None
        mape_baseline = sum(baseline_apes) / len(baseline_apes) if baseline_apes else None
        mape_adjusted = sum(adjusted_apes) / len(adjusted_apes) if adjusted_apes else None
        improve_rate = improve_count / len(adjusted_abs_errors) if adjusted_abs_errors else None
        mae_delta = _safe_metric_delta(mae_adjusted, mae_baseline)
        mape_delta = _safe_metric_delta(mape_adjusted, mape_baseline)
        mae_improvement_ratio = _safe_metric_improvement_ratio(mae_baseline, mae_adjusted)
        mape_improvement_ratio = _safe_metric_improvement_ratio(mape_baseline, mape_adjusted)

        output_path = options.get("output")
        if output_path:
            output_file = Path(output_path)
        else:
            output_dir = PROJECT_ROOT / "output" / "local_valuation_checks"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / f"{ts_code.replace('.', '_')}_{year}_market_style_backtest.json"

        payload = {
            "meta": {
                "ts_code": ts_code,
                "year": year,
                "sample_size_requested": sample_size,
                "sample_size_used": len(detail_rows),
                "seed": seed,
                "horizon_trading_days": horizon,
                "freq": freq,
                "market": market,
                "valuation_band_pct": band_pct,
                "valuation_source": valuation_source,
                "valuation_source_counts": source_counts,
                "style_profile": resolved_profile,
                "industry_group": resolved_group,
                "metrics_schema_version": "v2_abs_rel_pp",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "generation_mode": "dev_local_file_only_market_style_backtest",
                "note": "This backtest writes local artifact only and does not persist valuation snapshots.",
            },
            "metrics": {
                "mae_baseline": round(mae_baseline, 4) if mae_baseline is not None else None,
                "mae_adjusted": round(mae_adjusted, 4) if mae_adjusted is not None else None,
                "mae_delta": round(mae_delta, 4) if mae_delta is not None else None,
                "mae_delta_abs": round(mae_delta, 4) if mae_delta is not None else None,
                "mae_improvement_ratio": round(mae_improvement_ratio, 6)
                if mae_improvement_ratio is not None
                else None,
                "mae_improvement_pct": round(mae_improvement_ratio * 100.0, 4)
                if mae_improvement_ratio is not None
                else None,
                "mape_baseline": round(mape_baseline, 6) if mape_baseline is not None else None,
                "mape_adjusted": round(mape_adjusted, 6) if mape_adjusted is not None else None,
                "mape_delta": round(mape_delta, 6) if mape_delta is not None else None,
                "mape_delta_abs": round(mape_delta, 6) if mape_delta is not None else None,
                "mape_delta_pct_point": round(mape_delta * 100.0, 4) if mape_delta is not None else None,
                "mape_improvement_ratio": round(mape_improvement_ratio, 6)
                if mape_improvement_ratio is not None
                else None,
                "mape_improvement_pct": round(mape_improvement_ratio * 100.0, 4)
                if mape_improvement_ratio is not None
                else None,
                "adjusted_better_count": improve_count,
                "adjusted_better_rate": round(improve_rate, 6) if improve_rate is not None else None,
            },
            "samples": detail_rows,
        }

        output_file.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")
        self.stdout.write(str(output_file))