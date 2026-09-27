from __future__ import annotations

from datetime import date
from typing import Any

from django.db.models import Q

from financials.models import (
    FinancialBalanceSheetRecord,
    FinancialCashFlowRecord,
    FinancialIncomeRecord,
    FinancialIndicatorRecord,
    FinancialMainBusinessRecord,
)
from market_data.models import (
    Security,
    StockDailyFundamentalHistory,
    StockDailyFundamentalLatest,
)
from .classification_mapping import load_classification_mapping

TS_CODE_LENGTH = 9
DIMENSIONS = (
    ('growth_momentum', '增长动能', 0.18, '收入与利润增长趋势以及持续性'),
    ('profitability_quality', '盈利质量', 0.18, '回报能力与利润结构质量'),
    ('cashflow_resilience', '现金流韧性', 0.16, '经营、投资、筹资现金流的承压能力'),
    ('balance_sheet_safety', '资产负债安全', 0.16, '杠杆水平与偿债安全边际'),
    ('valuation_position', '估值与市场位置', 0.16, '估值水平与市场定价位置'),
    ('operation_efficiency', '经营效率与周转', 0.16, '资产周转与经营效率表现'),
)
_MAPPING = load_classification_mapping()
STYLE_PRIORITY = list(_MAPPING['style_priority'])
STYLE_MAPPING = dict(_MAPPING['style_mapping'])
SOURCE_WEIGHTS = dict(_MAPPING['source_weights'])
GENERIC_TERM_SCORE_MULTIPLIERS = dict(_MAPPING['generic_term_score_multipliers'])
MATCHING_RULES = dict(_MAPPING.get('matching_rules') or {})
FALLBACK_RULES = dict(_MAPPING.get('fallback_rules') or {})
NOISE_POLICY = dict(_MAPPING.get('noise_word_downgrade_policy') or {})
CONFLICT_RULES = list((_MAPPING.get('conflict_resolution') or {}).get('rules') or [])
NOISE_WORD_RULES = dict(_MAPPING.get('noise_word_rules') or {})


def normalize_ts_code(raw: str) -> str:
    code = (raw or '').strip().upper()
    if len(code) == TS_CODE_LENGTH and code[:6].isdigit() and code[6:] in {'.SH', '.SZ', '.BJ'}:
        return code
    if len(code) == 6 and code.isdigit():
        if code.startswith(('4', '8')):
            return f'{code}.BJ'
        if code.startswith(('5', '6', '9')):
            return f'{code}.SH'
        return f'{code}.SZ'
    raise ValueError('ts_code format invalid')


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result and abs(result) != float('inf') else default


def _normalize(value: float | None, low: float, high: float, *, invert: bool = False) -> float:
    if value is None or high <= low:
        return 50.0
    score = max(0.0, min(100.0, (value - low) * 100.0 / (high - low)))
    return 100.0 - score if invert else score


def _latest(model, security: Security):
    return model.objects.filter(security=security).order_by('-end_date', '-ann_date', '-id').first()


def _context(ts_code: str, asof_date: str | None = None) -> dict[str, Any]:
    code = normalize_ts_code(ts_code)
    security = Security.objects.select_related('industry').filter(ts_code=code, asset_type='STOCK').first()
    if security is None:
        raise LookupError('security not found')

    indicator = _latest(FinancialIndicatorRecord, security)
    income = _latest(FinancialIncomeRecord, security)
    balance = _latest(FinancialBalanceSheetRecord, security)
    cashflow = _latest(FinancialCashFlowRecord, security)
    main_business = _latest(FinancialMainBusinessRecord, security)
    bz_query = FinancialMainBusinessRecord.objects.filter(security=security, end_date=main_business.end_date) if main_business else FinancialMainBusinessRecord.objects.none()
    bz_items = list(bz_query.exclude(bz_item='').values_list('bz_item', flat=True).distinct())
    market_asof_date = None
    if asof_date:
        text = str(asof_date).strip()
        market_asof_date = date.fromisoformat(text) if '-' in text else date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    daily_history = StockDailyFundamentalHistory.objects.filter(security=security)
    if market_asof_date:
        daily_history = daily_history.filter(trade_date__lte=market_asof_date)
    daily_row = daily_history.order_by('-trade_date', '-id').first()
    if daily_row is None and market_asof_date is None:
        daily_row = StockDailyFundamentalLatest.objects.filter(security=security).first()

    if not any((indicator, income, balance, cashflow, daily_row)):
        raise ValueError('financial snapshot missing')

    def value(model, field: str):
        if model is None:
            return None
        raw_value = getattr(model, field, None)
        if raw_value is None:
            payload = getattr(model, 'raw_payload', None)
            if isinstance(payload, dict):
                raw_value = payload.get(field)
        return _number(raw_value)

    revenue = value(income, 'total_revenue') or value(income, 'revenue')
    oper_cost = value(income, 'oper_cost')
    gross_margin = value(indicator, 'grossprofit_margin')
    if gross_margin is None:
        fallback_gross_margin = value(indicator, 'gross_margin')
        if fallback_gross_margin is not None and -100.0 <= fallback_gross_margin <= 100.0:
            gross_margin = fallback_gross_margin
    gross_margin = gross_margin if gross_margin is not None else 0.0
    if abs(gross_margin) > 1000.0:
        gross_margin_revenue = value(income, 'revenue') or value(income, 'total_revenue') or 0.0
        gross_margin_cost = oper_cost or 0.0
        if gross_margin_revenue > 0:
            gross_margin = (gross_margin_revenue - gross_margin_cost) / gross_margin_revenue * 100.0

    operating_cashflow = value(cashflow, 'n_cashflow_act')
    investing_cashflow = value(cashflow, 'n_cashflow_inv_act')
    free_cashflow = value(cashflow, 'free_cashflow')
    roe_dt_value = value(indicator, 'roe_dt')
    if roe_dt_value is None and indicator is not None:
        roe_dt_row = FinancialIndicatorRecord.objects.filter(
            security=security,
            end_date=indicator.end_date,
            roe_dt__isnull=False,
        ).order_by('-ann_date', '-id').first()
        roe_dt_value = value(roe_dt_row, 'roe_dt')
    total_assets = value(balance, 'total_assets')
    total_equity = value(balance, 'total_hldr_eqy_exc_min_int')
    operating_cashflow_margin = operating_cashflow / revenue * 100.0 if operating_cashflow is not None and revenue else None
    free_cashflow_margin = free_cashflow / revenue * 100.0 if free_cashflow is not None and revenue else None

    features = {
        'or_yoy': value(indicator, 'or_yoy'),
        'tr_yoy': value(indicator, 'tr_yoy'),
        'netprofit_yoy': value(indicator, 'netprofit_yoy'),
        'ocf_yoy': value(indicator, 'ocf_yoy'),
        'roe': value(indicator, 'roe'),
        'roe_dt': roe_dt_value,
        'roa': value(indicator, 'roa'),
        'gross_margin': gross_margin,
        'grossprofit_margin': gross_margin,
        'netprofit_margin': value(indicator, 'netprofit_margin'),
        'n_cashflow_act': operating_cashflow,
        'n_cashflow_inv_act': investing_cashflow,
        'n_cash_flows_fnc_act': value(cashflow, 'n_cash_flows_fnc_act'),
        'n_incr_cash_cash_equ': value(cashflow, 'n_incr_cash_cash_equ'),
        'free_cashflow': free_cashflow,
        'operating_cashflow_margin': operating_cashflow_margin,
        'free_cashflow_margin': free_cashflow_margin,
        'ocf_to_or': value(indicator, 'ocf_to_or'),
        'debt_to_assets': value(indicator, 'debt_to_assets'),
        'current_ratio': value(indicator, 'current_ratio'),
        'quick_ratio': value(indicator, 'quick_ratio'),
        'cash_ratio': value(indicator, 'cash_ratio'),
        'total_assets': total_assets,
        'total_liab': value(balance, 'total_liab'),
        'total_hldr_eqy_exc_min_int': total_equity,
        'money_cap': value(balance, 'money_cap'),
        'st_borr': value(balance, 'st_borr'),
        'lt_borr': value(balance, 'lt_borr'),
        'assets_to_eqt': value(indicator, 'assets_to_eqt'),
        'accounts_receiv': value(balance, 'accounts_receiv'),
        'inventories': value(balance, 'inventories'),
        'assets_turn': value(indicator, 'assets_turn'),
        'turnover_rate': value(daily_row, 'turnover_rate'),
        'pe': value(daily_row, 'pe'),
        'pe_ttm': value(daily_row, 'pe_ttm'),
        'pb': value(daily_row, 'pb'),
        'ps': value(daily_row, 'ps'),
        'ps_ttm': value(daily_row, 'ps_ttm') or value(daily_row, 'ps'),
        'dv_ttm': value(daily_row, 'dv_ttm'),
        'total_mv': value(daily_row, 'total_mv'),
        'circ_mv': value(daily_row, 'circ_mv'),
        'revenue': revenue,
        'total_revenue': value(income, 'total_revenue'),
        'operate_profit': value(income, 'operate_profit'),
        'total_profit': value(income, 'total_profit'),
        'n_income': value(income, 'n_income'),
        'basic_eps': value(income, 'basic_eps'),
        'diluted_eps': value(income, 'diluted_eps'),
    }
    if daily_row is not None and security.industry_id:
        peer_rows = StockDailyFundamentalHistory.objects.filter(
            security__industry_id=security.industry_id,
            trade_date=daily_row.trade_date,
        )
        for metric, feature_key in (('pe', 'pe_ind_rank'), ('ps', 'ps_ind_rank')):
            target_value = value(daily_row, metric)
            peer_values = [
                _number(raw_value)
                for raw_value in peer_rows.filter(**{f'{metric}__gt': 0}).values_list(metric, flat=True)
            ]
            peer_values = [peer_value for peer_value in peer_values if peer_value is not None]
            if target_value is not None and target_value > 0 and len(peer_values) >= 2:
                features[feature_key] = sum(peer_value <= target_value for peer_value in peer_values) / len(peer_values)

        turnover_target = value(daily_row, 'turnover_rate')
        turnover_values = [
            parsed for raw_value in peer_rows.filter(turnover_rate__gt=0).values_list('turnover_rate', flat=True)
            if (parsed := _number(raw_value)) is not None
        ]
        if turnover_target is not None and turnover_target > 0 and len(turnover_values) >= 2:
            features['turnover_rate_ind_rank'] = sum(
                peer_value <= turnover_target for peer_value in turnover_values
            ) / len(turnover_values)

        current_pe = value(daily_row, 'pe')
        pe_history = list(
            StockDailyFundamentalHistory.objects.filter(
                security=security,
                trade_date__lte=daily_row.trade_date,
                pe__gt=0,
            )
            .order_by('-trade_date')
            .values_list('pe', flat=True)[:120]
        )
        if current_pe is not None and current_pe > 0 and len(pe_history) == 120:
            features['pe_rank_120d'] = sum(float(peer_value) <= current_pe for peer_value in pe_history) / 120

    normalization_overrides = {}
    if indicator is not None and security.industry_id:
        peer_security_ids = Security.objects.filter(
            asset_type='STOCK', industry_id=security.industry_id,
        ).values('id')
        for feature_key, field_name in (
            ('roe', 'roe'),
            ('roe_dt', 'roe_dt'),
            ('netprofit_margin', 'netprofit_margin'),
            ('gross_margin', 'grossprofit_margin'),
            ('grossprofit_margin', 'grossprofit_margin'),
            ('assets_turn', 'assets_turn'),
        ):
            target = features.get(feature_key)
            if target is None:
                continue
            peer_rows = FinancialIndicatorRecord.objects.filter(
                security_id__in=peer_security_ids,
                end_date=indicator.end_date,
            ).order_by('security_id', '-ann_date', '-id').distinct('security_id')
            peer_values = [
                parsed for raw in peer_rows.values_list(field_name, flat=True)
                if (parsed := _number(raw)) is not None
                and (field_name != 'assets_turn' or parsed != 0)
            ]
            if len(peer_values) < 20:
                market_rows = FinancialIndicatorRecord.objects.filter(
                    end_date=indicator.end_date,
                ).order_by('security_id', '-ann_date', '-id').distinct('security_id')
                peer_values = [
                    parsed for raw in market_rows.values_list(field_name, flat=True)
                    if (parsed := _number(raw)) is not None
                    and (field_name != 'assets_turn' or parsed != 0)
                ]
            if peer_values:
                normalization_overrides[feature_key] = sum(
                    peer_value <= target for peer_value in peer_values
                ) * 100.0 / len(peer_values)
    profile = getattr(security, 'company_profile', None)
    business_text = ' '.join(filter(None, [
        getattr(profile, 'main_business', '') if profile else '',
        getattr(profile, 'business_scope', '') if profile else '',
    ]))
    return {
        'security': security,
        'industry': security.industry.name if security.industry else '',
        'business_text': business_text,
        'bz_items': bz_items,
        'features': features,
        'normalization_overrides': normalization_overrides,
        'indicator': indicator,
        'income': income,
        'balance': balance,
        'cashflow': cashflow,
        'daily': daily_row,
    }


def _count_hits(text: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if keyword and keyword in text)


def _keyword_layers(mapping: dict[str, Any], key: str) -> tuple[list[str], list[str]]:
    value = mapping.get(key)
    if isinstance(value, dict):
        return list(value.get('strong') or []), list(value.get('weak') or [])
    return list(value or []), []


def _apply_noise_demotion(style: str, industry: str, business: str, raw_score: float) -> float:
    if raw_score <= 0 or style != 'finance_realestate':
        return raw_score
    rule = NOISE_WORD_RULES.get('finance_noise_in_tech') or {}
    trigger_keywords = rule.get('trigger_keywords') or []
    trigger_industries = rule.get('trigger_industries') or []
    action = str(rule.get('action') or '')
    if not trigger_keywords or not trigger_industries:
        return raw_score
    if not _count_hits(industry, trigger_industries) or not _count_hits(business, trigger_keywords):
        return raw_score
    if '0.3' in action:
        return raw_score * 0.3
    if '0.4' in action:
        return raw_score * 0.4
    return raw_score * 0.35 if 'downgrade' in action else raw_score * 0.3


def _rank_style_candidates(industry: str, business: str, bz_items: list[str]) -> list[dict[str, Any]]:
    industry_text = industry or ''
    business_text = business or ''
    bz_text = ' '.join(bz_items)
    source_text = {'industry': industry_text, 'business': business_text, 'bz': bz_text}
    ranked: list[dict[str, Any]] = []
    max_raw = 0.0
    for style in STYLE_PRIORITY:
        mapping = STYLE_MAPPING[style]
        unique = mapping.get('unique_keywords') or {}
        unique_keywords = unique.get('keywords', []) if isinstance(unique, dict) else unique
        unique_hits = _count_hits(f'{industry_text} {business_text} {bz_text}', unique_keywords or [])
        if not unique_hits and _count_hits(industry_text, mapping.get('exclude_industry') or []):
            continue
        if not unique_hits and _count_hits(business_text, mapping.get('exclude_business') or []):
            continue

        raw_score = 0.0
        hit_counts = {'industry': 0, 'main_business': 0, 'bz_item': 0}
        strong_hits = 0
        weak_hits = 0
        matches: list[str] = []
        for source_key, source_name in (('industry', 'industry'), ('business', 'main_business'), ('bz', 'bz_item')):
            text = source_text[source_key]
            strong, weak = _keyword_layers(mapping, source_key)
            weak_count = sum(text.count(keyword) for keyword in weak if keyword)
            weak_rules = mapping.get('weak_keyword_rules') or {}
            min_weak = int(weak_rules.get('min_weak_hits') or MATCHING_RULES.get('weak_keyword_min_count_to_score') or 0)
            require_industry = bool(weak_rules.get('require_industry_in_allowed_list', MATCHING_RULES.get('weak_keyword_requires_industry_match', False)))
            allowed_industries = weak_rules.get('allowed_industries_for_weak_match') or mapping.get('industry') or []
            weak_allowed = weak_count >= max(1, min_weak) and (not require_industry or _count_hits(industry_text, allowed_industries) > 0)
            for keywords, layer in ((strong, 'strong'), (weak if weak_allowed else [], 'weak')):
                for keyword in keywords:
                    count = text.count(keyword)
                    if not count:
                        continue
                    weight_key = source_key if source_key == 'industry' else f'{source_key}_{layer}'
                    weight = float(SOURCE_WEIGHTS.get(weight_key, SOURCE_WEIGHTS.get(source_key, 1.0)))
                    multiplier = float(GENERIC_TERM_SCORE_MULTIPLIERS.get(keyword, 1.0))
                    raw_score += count * weight * (1.0 + min(len(keyword), 8) / 12.0) * multiplier
                    hit_counts[source_name] += count
                    strong_hits += count if layer == 'strong' else 0
                    weak_hits += count if layer == 'weak' else 0
                    matches.append(f'{source_name}:{keyword}({count})')
        if unique_hits:
            raw_score += unique_hits * 4.0
            hit_counts['main_business'] += unique_hits
            matches.append(f'unique:命中 {unique_hits} 项')
        raw_score = _apply_noise_demotion(style, industry_text, business_text, raw_score)
        min_strong = int(MATCHING_RULES.get('minimum_strong_matches_for_valid') or 0)
        if raw_score <= 0 or (strong_hits < min_strong and weak_hits > 0):
            continue
        max_raw = max(max_raw, raw_score)
        ranked.append({'stock_type': style, 'raw_score': round(raw_score, 4), 'matched_keywords': matches, 'source_hits': hit_counts, 'score': 0})
    ranked.sort(key=lambda item: (-item['raw_score'], STYLE_PRIORITY.index(item['stock_type'])))
    if max_raw:
        for item in ranked:
            item['score'] = int(max(0, min(95, 55 + item['raw_score'] / max_raw * 40)))
    return ranked


def _resolve_noise_candidate(top: dict[str, Any], ranked: list[dict[str, Any]], industry: str) -> tuple[dict[str, Any] | None, str]:
    patterns = NOISE_POLICY.get('noise_patterns') or []
    matched = next((
        pattern for pattern in patterns
        if str(pattern.get('trigger_style') or '') == str(top.get('stock_type') or '')
        and (not pattern.get('trigger_industries') or _count_hits(industry, pattern.get('trigger_industries') or []) > 0)
    ), None)
    if not matched:
        return None, ''
    action = str(matched.get('action') or '')
    if NOISE_POLICY.get('prefer_top2_over_hardcode', False) and len(ranked) > 1:
        second = ranked[1]
        minimum = int(NOISE_POLICY.get('top2_min_score_to_use') or 60)
        allowed = {'growth_tech', 'platform_service', 'heavy_manufacturing', 'cyclical_resource'}
        if 'heavy_manufacturing' in action:
            allowed = {'heavy_manufacturing', 'growth_tech', 'platform_service', 'cyclical_resource'}
        if second.get('stock_type') != top.get('stock_type') and int(second.get('score') or 0) >= minimum and second.get('stock_type') in allowed:
            return second, '噪声词策略触发，采用 top2 候选'
    fallback = 'growth_tech' if 'growth_tech' in action else 'heavy_manufacturing' if 'heavy_manufacturing' in action else ''
    fallback = fallback or str(NOISE_POLICY.get('hardcode_fallback_if_no_top2') or 'stable_consumer')
    return {
        'stock_type': fallback,
        'score': max(60, int(float(top.get('score') or 70) - 8)),
        'raw_score': float(top.get('raw_score') or 1.0) * 0.55,
        'matched_keywords': [f"noise_policy:{top.get('stock_type', '')}_downgraded"],
        'source_hits': {'industry': 1, 'main_business': 0, 'bz_item': 0},
    }, '噪声词策略触发，采用策略兜底'


def _resolve_conflict_candidate(top: dict[str, Any], ranked: list[dict[str, Any]], industry: str) -> tuple[dict[str, Any] | None, str]:
    if len(ranked) < 2:
        return None, ''
    second = ranked[1]
    gap = float(top.get('score') or 0) - float(second.get('score') or 0)
    if gap >= float(MATCHING_RULES.get('score_gap_ambiguous_threshold') or 10):
        return None, ''
    for rule in CONFLICT_RULES:
        if rule.get('condition_top1') != top.get('stock_type') or rule.get('condition_top2') != second.get('stock_type'):
            continue
        industries = rule.get('trigger_industries') or []
        if industries and _count_hits(industry, industries) == 0:
            continue
        if rule.get('action') == 'use_top2':
            return second, f"冲突裁决触发: {rule.get('name') or 'use_top2'}"
    return None, ''


def _classify(industry: str, business_text: str, bz_items: list[str]) -> tuple[str, str, list[str], int, list[dict[str, Any]]]:
    ranked = _rank_style_candidates(industry, business_text, bz_items)
    if ranked:
        top = ranked[0]
        original_type = top['stock_type']
        noise_candidate, noise_reason = _resolve_noise_candidate(top, ranked, industry)
        if noise_candidate:
            top = noise_candidate
        conflict_candidate, conflict_reason = _resolve_conflict_candidate(top, ranked, industry)
        if conflict_candidate:
            top = conflict_candidate
        hits = top.get('source_hits') or {}
        reasons = [f'{source} 命中 {hits[key]} 项' for key, source in (('industry', 'industry'), ('main_business', 'main_business'), ('bz_item', 'bz_item')) if hits.get(key)]
        if original_type != top['stock_type']:
            reasons.append(f'候选重排序: {original_type} -> {top["stock_type"]}')
        if noise_reason:
            reasons.append(noise_reason)
        if conflict_reason:
            reasons.append(conflict_reason)
        return top['stock_type'], 'mapping', reasons, int(top['score']), ranked[:3]
    for industry_key, stock_type in dict(FALLBACK_RULES.get('industry_fallback_map') or {}).items():
        if industry_key and industry_key in (industry or ''):
            return str(stock_type), 'mapping', [f'按行业映射到 {stock_type}'], 50, []
    stock_type = str(FALLBACK_RULES.get('default_fallback') or 'stable_consumer')
    return stock_type, 'fallback', [f'缺少强分类信号，按配置回退到 {stock_type}'], 50, []


def _normalize_positive(value: float | None, low: float, high: float) -> float:
    if high <= low:
        return 50.0
    if value is None:
        value = 0.0
    return max(0.0, min(100.0, (value - low) * 100.0 / (high - low)))


def _normalize_negative(value: float | None, low: float, high: float) -> float:
    return 100.0 - _normalize_positive(value, low, high)


def _source_dimensions(stock_type: str, features: dict[str, float | None]) -> list[tuple[str, str, float, float, dict[str, float | None], str]]:
    debt = features.get('debt_to_assets') or 0.0
    debt_pct = debt * 100.0 if abs(debt) <= 1.0 else debt
    gross_margin = features.get('gross_margin') or 0.0
    market_cap = features.get('total_mv') or 0.0
    market_cap_for_scoring = market_cap * 10000.0 if market_cap > 0 else 0.0
    revenue_growth = _normalize_positive(features.get('or_yoy'), -20, 60)
    profit_growth = _normalize_positive(features.get('netprofit_yoy'), -30, 80)
    profitability = (
        _normalize_positive(features.get('roe'), 0, 25)
        + _normalize_positive(features.get('netprofit_margin'), 0, 40)
    ) / 2
    cash_quality = (
        _normalize_positive(features.get('n_cashflow_act'), -1, 1)
        + _normalize_positive(features.get('free_cashflow'), -1, 1)
    ) / 2
    safety = (
        _normalize_negative(debt_pct, 20, 85)
        + _normalize_positive(features.get('current_ratio') if features.get('current_ratio') is not None else 1, 0.8, 2.5)
    ) / 2
    valuation = _normalize_negative(features.get('pe_ttm') if features.get('pe_ttm') is not None else 30, 5, 80)

    if stock_type == 'growth_tech':
        return [
            ('growth_quality', '收入增长质量', 0.20, revenue_growth, {'or_yoy': features.get('or_yoy'), 'tr_yoy': features.get('tr_yoy')}, '营收增长与趋势稳定性'),
            ('profit_conversion', '利润兑现能力', 0.18, profit_growth, {'netprofit_yoy': features.get('netprofit_yoy')}, '收入增长向利润兑现的转化程度'),
            ('cash_runway', '现金续航能力', 0.16, cash_quality, {'n_cashflow_act': features.get('n_cashflow_act'), 'free_cashflow': features.get('free_cashflow')}, '经营与自由现金流表现'),
            ('rd_intensity_proxy', '研发投入强度代理', 0.16, _normalize_positive(gross_margin, 20, 70), {'gross_margin': gross_margin}, '以毛利与利润结构代理研发效率'),
            ('tech_moat_proxy', '技术壁垒代理', 0.15, _normalize_positive(features.get('roe_dt'), 0, 20), {'roe_dt': features.get('roe_dt')}, '扣非回报稳定性'),
            ('market_position_proxy', '市场卡位代理', 0.15, _normalize_positive(market_cap_for_scoring, 1e9, 3e11), {'total_mv': features.get('total_mv')}, '市值层级与市场认可度'),
        ]
    if stock_type == 'stable_consumer':
        return [
            ('moat_proxy', '品牌护城河代理', 0.20, _normalize_positive(gross_margin, 20, 75), {'gross_margin': gross_margin}, '毛利率稳定性'),
            ('profitability', '盈利能力', 0.18, profitability, {'roe': features.get('roe'), 'netprofit_margin': features.get('netprofit_margin')}, '利润率与回报水平'),
            ('channel_proxy', '渠道控制力代理', 0.16, _normalize_negative(features.get('assets_to_eqt'), 1, 8), {'assets_to_eqt': features.get('assets_to_eqt')}, '资金占用与渠道质量代理'),
            ('growth_stability', '成长稳定性', 0.16, (revenue_growth + profit_growth) / 2, {'or_yoy': features.get('or_yoy'), 'netprofit_yoy': features.get('netprofit_yoy')}, '营收与净利增长一致性'),
            ('cash_quality', '现金质量', 0.16, cash_quality, {'n_cashflow_act': features.get('n_cashflow_act'), 'free_cashflow': features.get('free_cashflow')}, '现金流含金量'),
            ('shareholder_return', '股东回报', 0.14, _normalize_positive(features.get('dv_ttm'), 0, 8), {'dv_ttm': features.get('dv_ttm')}, '股息水平与分红回报'),
        ]
    if stock_type == 'stable_income':
        return [
            ('cash_stability', '现金流稳定性', 0.20, cash_quality, {'n_cashflow_act': features.get('n_cashflow_act'), 'free_cashflow': features.get('free_cashflow')}, '经营现金流与自由现金流稳定度'),
            ('dividend_support', '分红支撑能力', 0.18, _normalize_positive(features.get('dv_ttm'), 0, 8), {'dv_ttm': features.get('dv_ttm')}, '分红率对稳定收入风格的支撑'),
            ('earnings_stability', '盈利稳定性', 0.16, _normalize_negative(abs(features.get('netprofit_yoy') or 0), 0, 80), {'netprofit_yoy': features.get('netprofit_yoy')}, '净利波动越小越稳定'),
            ('leverage_safety', '杠杆安全', 0.16, safety, {'debt_to_assets': debt_pct, 'assets_to_eqt': features.get('assets_to_eqt')}, '负债与流动性安全边际'),
            ('valuation_defense', '估值防御', 0.16, valuation, {'pe_ttm': features.get('pe_ttm'), 'pb': features.get('pb')}, '估值越便宜越具防御性'),
            ('moderate_growth', '温和成长', 0.14, _normalize_positive(features.get('or_yoy'), -10, 25), {'or_yoy': features.get('or_yoy'), 'tr_yoy': features.get('tr_yoy')}, '保持温和增长而非高波动扩张'),
        ]
    if stock_type == 'cyclical_resource':
        return [
            ('profit_elasticity', '盈利弹性', 0.20, profit_growth, {'netprofit_yoy': features.get('netprofit_yoy')}, '利润周期弹性'),
            ('cost_proxy', '成本竞争力代理', 0.18, _normalize_positive(gross_margin, 5, 50), {'gross_margin': gross_margin}, '毛利与成本端控制'),
            ('financial_safety', '财务安全', 0.16, safety, {'debt_to_assets': debt_pct}, '杠杆与偿债能力'),
            ('capital_discipline', '资本纪律代理', 0.16, cash_quality, {'free_cashflow': features.get('free_cashflow')}, '扩张与现金流匹配度'),
            ('operation_proxy', '库存与营运代理', 0.16, _normalize_positive(features.get('ocf_yoy'), -50, 100), {'ocf_yoy': features.get('ocf_yoy')}, '营运周转与现金改善'),
            ('cycle_position_proxy', '周期位置代理', 0.14, (valuation + _normalize_positive(features.get('dv_ttm'), 0, 10)) / 2, {'pe_ttm': features.get('pe_ttm'), 'dv_ttm': features.get('dv_ttm')}, '估值与股息组合定位'),
        ]
    if stock_type == 'finance_realestate':
        return [
            ('asset_quality_proxy', '资产质量代理', 0.20, _normalize_negative(debt_pct, 30, 90), {'debt_to_assets': debt_pct}, '资产负债结构'),
            ('capital_safety', '资本充足/杠杆安全', 0.18, _normalize_negative(features.get('assets_to_eqt'), 1, 20), {'assets_to_eqt': features.get('assets_to_eqt')}, '杠杆安全边际'),
            ('profitability', '盈利能力', 0.16, _normalize_positive(features.get('roe'), 3, 20), {'roe': features.get('roe')}, '回报稳定性'),
            ('risk_exposure_proxy', '风险敞口代理', 0.16, _normalize_negative(features.get('netprofit_yoy'), -100, 80), {'netprofit_yoy': features.get('netprofit_yoy')}, '业绩波动风险'),
            ('valuation_safety', '估值安全', 0.16, valuation, {'pe_ttm': features.get('pe_ttm'), 'pb': features.get('pb')}, '估值防御性'),
            ('growth_space_proxy', '成长空间代理', 0.14, revenue_growth, {'or_yoy': features.get('or_yoy')}, '收入增长空间'),
        ]
    if stock_type == 'heavy_manufacturing':
        return [
            ('capital_efficiency', '资本回报效率', 0.20, _normalize_positive(features.get('roe'), 0, 20), {'roe': features.get('roe'), 'roa': features.get('roa')}, '资本回报表现'),
            ('order_proxy', '订单质量代理', 0.18, revenue_growth, {'or_yoy': features.get('or_yoy')}, '收入增长兑现订单质量'),
            ('capacity_proxy', '产能利用率代理', 0.16, _normalize_positive(features.get('assets_to_eqt'), 0.8, 5), {'assets_to_eqt': features.get('assets_to_eqt')}, '资产结构与产能代理'),
            ('profitability', '盈利能力', 0.16, profitability, {'netprofit_margin': features.get('netprofit_margin')}, '利润能力'),
            ('operation_efficiency', '经营效率', 0.16, _normalize_positive(features.get('ocf_yoy'), -50, 100), {'ocf_yoy': features.get('ocf_yoy')}, '营运现金改善'),
            ('financial_safety', '财务安全', 0.14, safety, {'debt_to_assets': debt_pct}, '杠杆与流动性'),
        ]
    return [
        ('growth_quality', '收入增长质量', 0.20, revenue_growth, {'or_yoy': features.get('or_yoy')}, '增长质量'),
        ('income_quality', '收入质量', 0.18, _normalize_positive(gross_margin, 10, 80), {'gross_margin': gross_margin}, '毛利质量'),
        ('profit_path', '盈利路径', 0.16, profit_growth, {'netprofit_yoy': features.get('netprofit_yoy')}, '利润路径'),
        ('cash_runway', '现金续航', 0.16, cash_quality, {'free_cashflow': features.get('free_cashflow')}, '现金续航'),
        ('light_asset_proxy', '轻资产效率代理', 0.16, _normalize_positive(features.get('roa'), 0, 20), {'roa': features.get('roa')}, '资产效率'),
        ('competition_proxy', '竞争格局代理', 0.14, _normalize_positive(market_cap_for_scoring, 1e9, 3e11), {'total_mv': features.get('total_mv')}, '市值与格局代理'),
    ]


def _display_metrics(evidence: dict[str, float | None]) -> list[dict[str, str]]:
    return [
        {'key': key, 'label': key, 'value': f'{value:.2f}'}
        for key, value in evidence.items()
        if value is not None
    ][:3]


def classify_stock(ts_code: str, asof_date: str | None = None) -> dict[str, Any]:
    context = _context(ts_code, asof_date)
    security = context['security']
    stock_type, source, reasons, confidence, candidates = _classify(context['industry'], context['business_text'], context['bz_items'])
    return {
        'ts_code': security.ts_code,
        'stock_type': stock_type,
        'stock_type_source': source,
        'stock_type_confidence': confidence,
        'stock_type_reasons': reasons,
        'stock_type_candidates': candidates or [{'stock_type': stock_type, 'score': confidence, 'matched_keywords': []}],
        'asof_date': asof_date or '',
    }


def compute_score(
    ts_code: str,
    asof_date: str | None = None,
    force_recompute: bool = False,
    include_feature_values: bool = False,
) -> dict[str, Any]:
    del force_recompute
    context = _context(ts_code, asof_date)
    security = context['security']
    features = context['features']
    classification = classify_stock(security.ts_code, asof_date)
    dimension_specs = _source_dimensions(classification['stock_type'], features)
    dimensions = []
    weights: dict[str, float] = {}
    total = 0.0
    for key, name, weight, score, evidence, explanation in dimension_specs:
        score = max(0.0, min(100.0, score))
        dimensions.append({
            'key': key,
            'name': name,
            'score': round(score, 2),
            'weight': weight,
            'evidence': evidence,
            'explanation': explanation,
            'display_metrics': _display_metrics(evidence),
        })
        weights[key] = weight
        total += score * weight

    total = round(max(0.0, min(100.0, total)), 2)
    grade = 'A' if total >= 85 else 'B' if total >= 70 else 'C' if total >= 55 else 'D' if total >= 40 else 'E'
    risks: list[dict[str, str]] = []
    debt = features.get('debt_to_assets')
    if debt is not None and (debt * 100 if abs(debt) <= 1 else debt) > 75:
        risks.append({'code': 'high_leverage', 'level': 'warning', 'message': '资产负债率偏高'})
    if features.get('n_cashflow_act') is not None and features['n_cashflow_act'] < 0:
        risks.append({'code': 'negative_operating_cashflow', 'level': 'warning', 'message': '经营现金流为负'})
    if features.get('netprofit_yoy') is not None and features['netprofit_yoy'] < -30:
        risks.append({'code': 'profit_drop', 'level': 'warning', 'message': '净利润同比大幅下滑'})
    if features.get('pe_ttm') is not None and features['pe_ttm'] > 80:
        risks.append({'code': 'high_valuation', 'level': 'info', 'message': '估值水平较高'})

    financial_end_dates = [
        row.end_date
        for key in ('income', 'indicator', 'balance', 'cashflow', 'main_business')
        if (row := context.get(key)) is not None and row.end_date is not None
    ]
    snapshot_asof_date = max(financial_end_dates, default=None)
    if snapshot_asof_date is None and context.get('daily') is not None:
        snapshot_asof_date = context['daily'].trade_date

    result = {
        'ts_code': security.ts_code,
        'name': security.name,
        'industry': context['industry'],
        'stock_type': classification['stock_type'],
        'score_grade': grade,
        'total_score': total,
        'dimension_scores': dimensions,
        'dimension_weights': weights,
        'risk_flags': risks,
        'ai_summary': '评分基于当前财务与交易快照生成，缺失经营外延数据时已采用代理指标。',
        'stock_type_source': classification['stock_type_source'],
        'stock_type_confidence': classification['stock_type_confidence'],
        'stock_type_reasons': classification['stock_type_reasons'],
        'snapshot_asof_date': snapshot_asof_date.strftime('%Y%m%d') if snapshot_asof_date else '',
    }
    if include_feature_values:
        result['_feature_values'] = features
        result['_normalization_overrides'] = context['normalization_overrides']
    return result


def suggest_stocks(query: str, limit: int) -> list[dict[str, Any]]:
    term = (query or '').strip()
    if not term:
        return []
    rows = Security.objects.select_related('industry').filter(asset_type='STOCK').filter(
        Q(ts_code__icontains=term.upper()) | Q(symbol__icontains=term) | Q(name__icontains=term)
    ).order_by('list_status', 'ts_code')[:max(1, min(int(limit), 20))]
    return [
        {
            'ts_code': row.ts_code,
            'symbol': row.symbol or row.ts_code.split('.')[0],
            'name': row.name,
            'industry': row.industry.name if row.industry else '',
            'list_status': row.list_status,
            'match_type': 'code' if term.upper() in row.ts_code.upper() else 'name',
            'score': 1.0 if term.upper() == row.ts_code.upper() else 0.8,
        }
        for row in rows
    ]
