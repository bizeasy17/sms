from __future__ import annotations

import datetime
import math
from statistics import median
from typing import Any


DEFAULT_ENGINE_VERSION = 'v1_5_ruleset_20260411'


REPORT_END_SUFFIX = {
    'Q1': '0331',
    'H1': '0630',
    'Q3': '0930',
    'ANNUAL': '1231',
}


def _to_float(value):
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_date(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _clamp(value, lower=0.0, upper=100.0):
    return max(lower, min(upper, value))


def _risk_level(score):
    if score >= 66:
        return 'HIGH'
    if score >= 33:
        return 'MEDIUM'
    return 'LOW'


def _severity(score):
    if score >= 70:
        return 'HIGH'
    if score >= 40:
        return 'MEDIUM'
    return 'LOW'


def _summarize_factors(factors):
    triggered = [item for item in factors if item.get('is_triggered')]
    top = sorted(triggered, key=lambda item: item.get('factor_score') or 0.0, reverse=True)[:3]
    if not top:
        return '估值风险较低，当前未发现明显脆弱点。'
    return '；'.join(str(item.get('reason') or item.get('factor_name') or '') for item in top if item.get('reason') or item.get('factor_name'))


def _build_factor(dimension, factor_code, factor_name, factor_score, reason, *, factor_value='', threshold='', payload=None):
    score = round(float(factor_score or 0.0), 2)
    return {
        'dimension': dimension,
        'factor_code': factor_code,
        'factor_name': factor_name,
        'factor_score': score,
        'severity': _severity(score),
        'factor_value': factor_value,
        'threshold': threshold,
        'reason': reason,
        'is_triggered': score >= 40,
        'payload': payload or {},
    }


def _score_method_coverage(valid_methods):
    count = len(valid_methods)
    if count >= 5:
        return 10.0
    if count == 4:
        return 20.0
    if count == 3:
        return 40.0
    if count == 2:
        return 70.0
    if count == 1:
        return 90.0
    return 100.0


def _score_method_dispersion(valid_prices):
    if len(valid_prices) <= 1:
        return 75.0
    center = median(valid_prices)
    if not center or center <= 0:
        return 65.0
    variance = sum((price - center) ** 2 for price in valid_prices) / len(valid_prices)
    dispersion = math.sqrt(variance) / center
    return round(_clamp(dispersion / 0.35 * 100.0), 2)


def _score_freshness(trade_date, report_ann_date, report_end_date=None):
    trade_dt = _normalize_date(trade_date)
    ann_dt = _normalize_date(report_ann_date)
    end_dt = _normalize_date(report_end_date)
    if trade_dt is None or ann_dt is None:
        return 55.0, None, 'missing'
    if end_dt is not None and ann_dt < end_dt:
        return 62.0, None, 'ann_before_report_end'
    if ann_dt > trade_dt:
        return 58.0, None, 'ann_after_trade_date'
    age_days = max(0, (trade_dt - ann_dt).days)
    if age_days <= 45:
        return 10.0, age_days, 'ok'
    if age_days <= 120:
        return 28.0, age_days, 'ok'
    if age_days <= 240:
        return 55.0, age_days, 'ok'
    return 78.0, age_days, 'ok'


def _build_freshness_reason(age_days, freshness_status):
    if freshness_status == 'ann_before_report_end':
        return '利润口径公告日早于报告期末日，公告日期存在异常，已按保守风险处理。'
    if freshness_status == 'ann_after_trade_date':
        return '利润口径公告日晚于估值交易日，公告可见性存在异常，已按保守风险处理。'
    return f'估值依赖的利润口径公告距交易日已过去 {age_days if age_days is not None else "未知"} 天。'


def _score_profit_source(profit_data_source):
    source = str(profit_data_source or '').strip().lower()
    if source == 'fina_indicator_income':
        return 15.0
    if source == 'express_vip_blended':
        return 48.0
    if source == 'express_vip':
        return 68.0
    if source:
        return 35.0
    return 45.0


def _score_variant_dependency(valuation_variant):
    variant = str(valuation_variant or 'default').strip().lower()
    if variant == 'default':
        return 10.0
    if variant.startswith('sw_l3_baseline'):
        return 35.0
    if variant.startswith('business_match'):
        return 58.0
    return 42.0


def _score_core_method_presence(valid_methods):
    method_set = set(valid_methods)
    core = {'pe', 'pb', 'ps'}
    support = {'fcff_dcf', 'ddm', 'peg'}
    core_count = len(core.intersection(method_set))
    support_count = len(support.intersection(method_set))
    if core_count >= 3:
        return 12.0
    if core_count == 2 and support_count >= 1:
        return 28.0
    if core_count == 2:
        return 36.0
    if core_count == 1:
        return 62.0
    return 78.0


def _score_data_completeness(*, report_type, report_end_date, report_ann_date, source):
    score = 0.0
    if not report_type:
        score += 25.0
    if _normalize_date(report_end_date) is None:
        score += 25.0
    if _normalize_date(report_ann_date) is None:
        score += 30.0
    if not source:
        score += 20.0
    return _clamp(score)


def _score_report_alignment(report_type, report_end_date):
    rpt = str(report_type or '').strip().upper()
    end_dt = _normalize_date(report_end_date)
    if not rpt or rpt not in REPORT_END_SUFFIX or end_dt is None:
        return 45.0
    md = end_dt.strftime('%m%d')
    if md == REPORT_END_SUFFIX[rpt]:
        return 8.0
    return 72.0


def _score_gap_pressure(summary):
    if not isinstance(summary, dict):
        return 40.0
    comp_gap = _to_float(summary.get('composite_valuation_gap_pct'))
    cons_gap = _to_float(summary.get('conservative_valuation_gap_pct'))
    values = [abs(val) for val in [comp_gap, cons_gap] if val is not None]
    if not values:
        return 40.0
    pressure = max(values)
    if pressure <= 10:
        return 15.0
    if pressure <= 20:
        return 28.0
    if pressure <= 35:
        return 48.0
    return 68.0


def _normalize_pct(value):
    num = _to_float(value)
    if num is None:
        return None
    if -1.0 <= num <= 1.0:
        num = num * 100.0
    return num


def _fmt_pct(value):
    num = _normalize_pct(value)
    if num is None:
        return "未知"
    return f"{round(num, 2)}%"


def _build_method_dispersion_reason(valid_prices):
    if not valid_prices:
        return '缺少可用估值价格，方法分歧度暂按保守风险分处理。'
    min_price = min(valid_prices)
    max_price = max(valid_prices)
    if min_price <= 0:
        return '不同估值方法给出的价格分歧较大，估值结论稳健性下降。'
    spread_pct = (max_price - min_price) / min_price * 100.0
    return (
        f'不同估值方法给出的价格区间为 {round(min_price, 2)} 到 {round(max_price, 2)}，'
        f'价差约 {round(spread_pct, 2)}%，估值结论稳健性下降。'
    )


def _build_gap_pressure_reason(summary):
    if not isinstance(summary, dict):
        return '缺少组合/保守估值汇总，当前按保守风险分处理。'

    comp_gap = _to_float(summary.get('composite_valuation_gap_pct'))
    cons_gap = _to_float(summary.get('conservative_valuation_gap_pct'))
    if comp_gap is None and cons_gap is None:
        return '缺少组合/保守估值偏离数据，当前按保守风险分处理。'

    parts = []
    if comp_gap is not None:
        parts.append(f'组合估值偏离 {round(comp_gap, 2)}%')
    if cons_gap is not None:
        parts.append(f'保守估值偏离 {round(cons_gap, 2)}%')
    return '；'.join(parts) + '，风险应更审慎解读。'


def _build_leverage_reason(debt_to_assets):
    if debt_to_assets is None:
        return '缺少资产负债率数据，当前按保守风险分处理。'
    return f'资产负债率为 {round(debt_to_assets, 2)}%，杠杆水平会影响估值安全边际。'


def _build_profitability_reason(profitability_payload, profitability_quality_score):
    available_count = profitability_payload.get('available_count') or 0
    if available_count == 0:
        return '盈利质量核心指标缺失，当前按保守风险分处理。'

    weak_signals = []
    roe = profitability_payload.get('roe')
    netprofit_margin = profitability_payload.get('netprofit_margin')
    gross_margin = profitability_payload.get('gross_margin')

    if roe is not None and roe < 10:
        weak_signals.append(f'ROE 偏低({round(roe, 2)}% < 10%)')
    if netprofit_margin is not None and netprofit_margin < 8:
        weak_signals.append(f'净利率偏低({round(netprofit_margin, 2)}% < 8%)')
    if gross_margin is not None and gross_margin < 20:
        weak_signals.append(f'毛利率偏低({round(gross_margin, 2)}% < 20%)')

    if weak_signals and profitability_quality_score >= 40:
        return '；'.join(weak_signals) + '，会压缩估值可持续性。'

    if weak_signals:
        return '；'.join(weak_signals) + '，但整体盈利质量风险仍可控。'

    return 'ROE/净利率/毛利率处于健康区间，盈利质量风险可控。'


def _score_leverage_stress(financial_profile):
    profile = financial_profile or {}
    debt_to_assets = _normalize_pct(profile.get('debt_to_assets'))
    if debt_to_assets is None:
        return 38.0, None
    if debt_to_assets <= 45:
        return 12.0, debt_to_assets
    if debt_to_assets <= 60:
        return 28.0, debt_to_assets
    if debt_to_assets <= 75:
        return 52.0, debt_to_assets
    return 74.0, debt_to_assets


def _score_liquidity_structure(financial_profile):
    profile = financial_profile or {}
    ca_to_assets = _normalize_pct(profile.get('ca_to_assets'))
    if ca_to_assets is None:
        return 42.0, None
    if ca_to_assets < 20:
        return 72.0, ca_to_assets
    if ca_to_assets < 30:
        return 55.0, ca_to_assets
    if ca_to_assets < 40:
        return 32.0, ca_to_assets
    if ca_to_assets <= 70:
        return 18.0, ca_to_assets
    return 28.0, ca_to_assets


def _score_profitability_quality(financial_profile):
    profile = financial_profile or {}
    roe = _normalize_pct(profile.get('roe') if profile.get('roe') is not None else profile.get('roe_dt'))
    netprofit_margin = _normalize_pct(profile.get('netprofit_margin'))
    gross_margin = _normalize_pct(profile.get('gross_margin'))

    available_count = sum(1 for value in [roe, netprofit_margin, gross_margin] if value is not None)
    if available_count == 0:
        return 45.0, {'roe': None, 'netprofit_margin': None, 'gross_margin': None}

    score = 8.0
    if roe is not None:
        if roe < 5:
            score += 35.0
        elif roe < 10:
            score += 20.0
        elif roe < 15:
            score += 8.0

    if netprofit_margin is not None:
        if netprofit_margin < 3:
            score += 25.0
        elif netprofit_margin < 8:
            score += 12.0

    if gross_margin is not None:
        if gross_margin < 12:
            score += 18.0
        elif gross_margin < 20:
            score += 8.0

    score += max(0, 3 - available_count) * 4.0
    return _clamp(score), {
        'roe': roe,
        'netprofit_margin': netprofit_margin,
        'gross_margin': gross_margin,
        'available_count': available_count,
    }


def _score_receivable_pressure(financial_profile):
    profile = financial_profile or {}
    ar_to_assets = _normalize_pct(profile.get('ar_to_assets'))
    if ar_to_assets is None:
        return 35.0, None
    if ar_to_assets <= 10:
        return 12.0, ar_to_assets
    if ar_to_assets <= 20:
        return 30.0, ar_to_assets
    if ar_to_assets <= 35:
        return 55.0, ar_to_assets
    return 75.0, ar_to_assets


def _score_inventory_pressure(financial_profile):
    profile = financial_profile or {}
    inventory_to_assets = _normalize_pct(profile.get('inventory_to_assets'))
    if inventory_to_assets is None:
        return 38.0, None
    if inventory_to_assets <= 12:
        return 15.0, inventory_to_assets
    if inventory_to_assets <= 25:
        return 35.0, inventory_to_assets
    if inventory_to_assets <= 40:
        return 58.0, inventory_to_assets
    return 78.0, inventory_to_assets


def _score_goodwill_pressure(financial_profile):
    profile = financial_profile or {}
    goodwill_to_assets = _normalize_pct(profile.get('goodwill_to_assets'))
    if goodwill_to_assets is None:
        return 30.0, None
    if goodwill_to_assets <= 5:
        return 10.0, goodwill_to_assets
    if goodwill_to_assets <= 15:
        return 32.0, goodwill_to_assets
    if goodwill_to_assets <= 30:
        return 55.0, goodwill_to_assets
    return 76.0, goodwill_to_assets


def build_valuation_risk_payload(
    *,
    ts_code: str,
    market: str = 'CN',
    trade_date=None,
    valuation_variant: str = 'default',
    profit_report_type: str | None = None,
    profit_report_end_date=None,
    profit_report_ann_date=None,
    profit_data_source: str | None = None,
    current_price=None,
    rows: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
    financial_profile: dict[str, Any] | None = None,
    base_band_pct: float | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = rows or []
    summary = summary or {}
    valid_rows = []
    valid_methods = []
    valid_prices = []
    for row in rows:
        price = _to_float((row or {}).get('valuation_price'))
        method = str((row or {}).get('valuation_method') or '').strip().lower()
        if not method or price is None or price <= 0:
            continue
        valid_rows.append(row)
        valid_methods.append(method)
        valid_prices.append(price)

    coverage_score = _score_method_coverage(valid_methods)
    dispersion_score = _score_method_dispersion(valid_prices)
    freshness_score, age_days, freshness_status = _score_freshness(
        trade_date,
        profit_report_ann_date,
        profit_report_end_date,
    )
    source_score = _score_profit_source(profit_data_source)
    variant_score = _score_variant_dependency(valuation_variant)

    core_method_score = _score_core_method_presence(valid_methods)
    completeness_score = _score_data_completeness(
        report_type=profit_report_type,
        report_end_date=profit_report_end_date,
        report_ann_date=profit_report_ann_date,
        source=profit_data_source,
    )
    report_alignment_score = _score_report_alignment(profit_report_type, profit_report_end_date)
    gap_pressure_score = _score_gap_pressure(summary)
    leverage_stress_score, debt_to_assets = _score_leverage_stress(financial_profile)
    liquidity_structure_score, ca_to_assets = _score_liquidity_structure(financial_profile)
    profitability_quality_score, profitability_payload = _score_profitability_quality(financial_profile)
    receivable_pressure_score, ar_to_assets = _score_receivable_pressure(financial_profile)
    inventory_pressure_score, inventory_to_assets = _score_inventory_pressure(financial_profile)
    goodwill_pressure_score, goodwill_to_assets = _score_goodwill_pressure(financial_profile)

    weighted_score = (
        coverage_score * 0.15
        + dispersion_score * 0.15
        + core_method_score * 0.07
        + freshness_score * 0.09
        + source_score * 0.07
        + completeness_score * 0.06
        + report_alignment_score * 0.07
        + variant_score * 0.04
        + gap_pressure_score * 0.04
        + leverage_stress_score * 0.05
        + liquidity_structure_score * 0.05
        + profitability_quality_score * 0.05
        + receivable_pressure_score * 0.04
        + inventory_pressure_score * 0.04
        + goodwill_pressure_score * 0.03
    )
    risk_score = round(_clamp(weighted_score), 2)
    confidence = 85.0
    if len(valid_methods) < 3:
        confidence -= 15.0
    if _normalize_date(profit_report_ann_date) is None:
        confidence -= 10.0
    if not profit_data_source:
        confidence -= 10.0
    confidence = round(_clamp(confidence), 2)

    factors = [
        _build_factor(
            'valuation_stability',
            'method_coverage',
            '方法覆盖度',
            coverage_score,
            f'当前仅有 {len(valid_methods)} 个有效估值方法可用于交叉验证。',
            factor_value=str(len(valid_methods)),
            threshold='>=4 methods preferred',
        ),
        _build_factor(
            'valuation_stability',
            'method_dispersion',
            '方法分歧度',
            dispersion_score,
            _build_method_dispersion_reason(valid_prices),
            factor_value=','.join(f'{price:.2f}' for price in valid_prices[:6]),
            threshold='dispersion <= 35%',
        ),
        _build_factor(
            'valuation_stability',
            'core_method_presence',
            '核心方法结构',
            core_method_score,
            '核心估值方法（PE/PB/PS）覆盖不足会降低结论稳健性。',
            factor_value=','.join(valid_methods),
            threshold='>=2 core methods preferred',
        ),
        _build_factor(
            'disclosure_quality',
            'report_freshness',
            '财报时效性',
            freshness_score,
            _build_freshness_reason(age_days, freshness_status),
            factor_value=f'age_days={age_days if age_days is not None else ""},status={freshness_status}',
            threshold='<=120 days preferred',
        ),
        _build_factor(
            'disclosure_quality',
            'data_completeness',
            '口径字段完备度',
            completeness_score,
            '风险评估依赖的财报口径字段存在缺失。',
            factor_value=f'type={profit_report_type or ""},end={profit_report_end_date or ""},ann={profit_report_ann_date or ""},src={profit_data_source or ""}',
            threshold='all critical fields present',
        ),
        _build_factor(
            'disclosure_quality',
            'report_alignment',
            '报告类型一致性',
            report_alignment_score,
            '财报类型与报告期末日可能存在不一致。',
            factor_value=f'{profit_report_type or ""}|{profit_report_end_date or ""}',
            threshold='Q1/0331 H1/0630 Q3/0930 ANNUAL/1231',
        ),
        _build_factor(
            'valuation_output',
            'gap_pressure',
            '估值偏离压力',
            gap_pressure_score,
            _build_gap_pressure_reason(summary),
            factor_value=f'composite_gap={summary.get("composite_valuation_gap_pct")},conservative_gap={summary.get("conservative_valuation_gap_pct")}',
            threshold='abs_gap <= 20%',
        ),
        _build_factor(
            'disclosure_quality',
            'profit_source',
            '利润口径来源',
            source_score,
            f'当前利润口径来源为 {profit_data_source or "unknown"}。',
            factor_value=str(profit_data_source or ''),
            threshold='formal report preferred',
        ),
        _build_factor(
            'context_dependency',
            'variant_dependency',
            '估值变体依赖',
            variant_score,
            f'当前估值结果依赖 {valuation_variant or "default"} 变体。',
            factor_value=str(valuation_variant or 'default'),
            threshold='default preferred',
        ),
        _build_factor(
            'asset_quality',
            'leverage_stress',
            '杠杆压力',
            leverage_stress_score,
            _build_leverage_reason(debt_to_assets),
            factor_value=f'debt_to_assets={round(debt_to_assets, 2) if debt_to_assets is not None else ""}',
            threshold='debt_to_assets <= 60%',
        ),
        _build_factor(
            'asset_quality',
            'liquidity_structure',
            '流动性结构',
            liquidity_structure_score,
            '流动资产结构偏弱时，利润兑现和现金流弹性风险上升。',
            factor_value=f'ca_to_assets={round(ca_to_assets, 2) if ca_to_assets is not None else ""}',
            threshold='ca_to_assets >= 30%',
        ),
        _build_factor(
            'asset_quality',
            'profitability_quality',
            '盈利质量',
            profitability_quality_score,
            _build_profitability_reason(profitability_payload, profitability_quality_score),
            factor_value=(
                f"roe={round(profitability_payload.get('roe'), 2) if profitability_payload.get('roe') is not None else ''},"
                f"net_margin={round(profitability_payload.get('netprofit_margin'), 2) if profitability_payload.get('netprofit_margin') is not None else ''},"
                f"gross_margin={round(profitability_payload.get('gross_margin'), 2) if profitability_payload.get('gross_margin') is not None else ''}"
            ),
            threshold='roe>=10%, net_margin>=8%, gross_margin>=20%',
            payload=profitability_payload,
        ),
        _build_factor(
            'asset_quality',
            'receivable_pressure',
            '应收压力',
            receivable_pressure_score,
            '应收资产占比偏高可能意味着回款质量与利润兑现风险。',
            factor_value=f'ar_to_assets={round(ar_to_assets, 2) if ar_to_assets is not None else ""}',
            threshold='ar_to_assets <= 20%',
        ),
        _build_factor(
            'asset_quality',
            'inventory_pressure',
            '存货压力',
            inventory_pressure_score,
            '存货占比偏高会提高减值与周转风险。',
            factor_value=f'inventory_to_assets={round(inventory_to_assets, 2) if inventory_to_assets is not None else ""}',
            threshold='inventory_to_assets <= 25%',
        ),
        _build_factor(
            'asset_quality',
            'goodwill_pressure',
            '商誉压力',
            goodwill_pressure_score,
            '商誉占比高会增加并购整合与减值冲击风险。',
            factor_value=f'goodwill_to_assets={round(goodwill_to_assets, 2) if goodwill_to_assets is not None else ""}',
            threshold='goodwill_to_assets <= 15%',
        ),
    ]

    discount_pct = round(min(0.35, max(0.03, risk_score / 250.0)), 4)
    effective_band_pct = None
    if base_band_pct is not None:
        effective_band_pct = round(float(base_band_pct) * (1 + risk_score / 100.0), 4)

    composite_price = _to_float(summary.get('composite_valuation_price'))
    conservative_price = _to_float(summary.get('conservative_valuation_price'))

    if extra_metadata:
        metadata = dict(extra_metadata)
    else:
        metadata = {}
    metadata.update(
        {
            'valid_method_count': len(valid_methods),
            'valid_methods': valid_methods,
            'report_age_days': age_days,
            'financial_profile': financial_profile or {},
        }
    )

    return {
        'ts_code': ts_code,
        'market': market,
        'trade_date': trade_date,
        'valuation_variant': valuation_variant or 'default',
        'profit_report_type': profit_report_type,
        'profit_report_end_date': profit_report_end_date,
        'profit_report_ann_date': profit_report_ann_date,
        'profit_data_source': profit_data_source,
        'risk_score': risk_score,
        'risk_level': _risk_level(risk_score),
        'confidence': confidence,
        'summary': _summarize_factors(factors),
        'engine_version': DEFAULT_ENGINE_VERSION,
        'status': 'READY',
        'dimensions': {
            'valuation_stability': round((coverage_score * 0.34 + dispersion_score * 0.33 + core_method_score * 0.33), 2),
            'disclosure_quality': round((freshness_score * 0.30 + source_score * 0.25 + completeness_score * 0.25 + report_alignment_score * 0.20), 2),
            'context_dependency': round(variant_score, 2),
            'valuation_output': round(gap_pressure_score, 2),
            'asset_quality': round(
                (
                    leverage_stress_score * 0.24
                    + liquidity_structure_score * 0.18
                    + profitability_quality_score * 0.18
                    + receivable_pressure_score * 0.16
                    + inventory_pressure_score * 0.14
                    + goodwill_pressure_score * 0.10
                ),
                2,
            ),
        },
        'adjustment': {
            'valuation_discount_pct': discount_pct,
            'effective_band_pct': effective_band_pct,
            'adjusted_composite_valuation_price': round(composite_price * (1 - discount_pct), 4)
            if composite_price is not None
            else None,
            'adjusted_conservative_valuation_price': round(conservative_price * (1 - discount_pct), 4)
            if conservative_price is not None
            else None,
        },
        'metadata': metadata,
        'factors': factors,
    }
