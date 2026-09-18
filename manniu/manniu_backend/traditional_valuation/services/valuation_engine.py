from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from django.db import transaction

from traditional_valuation.models import (
    TraditionalValuationParameterVersion,
    TraditionalValuationRiskSnapshot,
    TraditionalValuationSnapshot,
    TraditionalValuationSnapshotLatest,
    TraditionalValuationVariantSummaryLatest,
)
from .config import ValuationTemplateLoader
from .input_resolver import ValuationInputResolver
from .risk_service import build_risk_payload
from .buy_candidate_summary import summarize_buy_candidate
from market_data.services.business_match import build_business_industry_match
from .extended_methods import (
    calculate_ev_ebitda,
    calculate_scarcity_overlay,
    calculate_sw_history,
)


FINANCIAL_AMOUNT_TO_PER_SHARE_SCALE = 10_000.0


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _price(value):
    return round(float(value), 6) if value is not None and value > 0 else None


def _per_share(amount, shares):
    if amount is None or shares is None or shares <= 0:
        return None
    return amount / shares / FINANCIAL_AMOUNT_TO_PER_SHARE_SCALE


def _calculate_fcff_dcf(base_fcff, shares, cash, debt, dcf_kwargs):
    if base_fcff is None or shares is None or shares <= 0:
        return None
    dcf_kwargs = dcf_kwargs or {}
    discount_rate = float(dcf_kwargs.get('discount_rate', 0.105))
    terminal_growth_rate = float(dcf_kwargs.get('terminal_growth_rate', 0.015))
    growth_rates = [float(value) for value in (dcf_kwargs.get('growth_rates') or [])[:5]]
    if not growth_rates:
        growth_rates = [0.08, 0.06, 0.05, 0.04, 0.03]
    if len(growth_rates) != 5:
        raise ValueError('FCFF-DCF requires exactly five growth_rates.')
    if discount_rate <= terminal_growth_rate:
        raise ValueError('discount_rate must be greater than terminal_growth_rate.')

    forecast_fcff = []
    present_values = []
    current_fcff = float(base_fcff)
    for year, growth_rate in enumerate(growth_rates, start=1):
        current_fcff *= 1.0 + growth_rate
        forecast_fcff.append(current_fcff)
        present_values.append(current_fcff / ((1.0 + discount_rate) ** year))
    terminal_fcff = forecast_fcff[-1] * (1.0 + terminal_growth_rate)
    terminal_value = terminal_fcff / (discount_rate - terminal_growth_rate)
    terminal_pv = terminal_value / ((1.0 + discount_rate) ** len(forecast_fcff))
    enterprise_value = sum(present_values) + terminal_pv
    net_debt = None if cash is None or debt is None else debt - cash
    equity_value = enterprise_value - net_debt if net_debt is not None else None
    valuation_price = _per_share(equity_value, shares) if equity_value is not None else None
    return {
        'valuation_price': _price(valuation_price),
        'input': {
            'fcff': float(base_fcff),
            'fcff_per_share': _per_share(float(base_fcff), shares),
            'shares': shares,
            'cash': cash,
            'debt': debt,
            'net_debt': net_debt,
            'growth_rates': growth_rates,
            'forecast_fcff': forecast_fcff,
            'present_values': present_values,
            'discount_rate': discount_rate,
            'terminal_growth_rate': terminal_growth_rate,
            'terminal_fcff': terminal_fcff,
            'terminal_value': terminal_value,
            'terminal_present_value': terminal_pv,
            'enterprise_value': enterprise_value,
            'equity_value': equity_value,
        },
    }


def _tiered_template(valid_prices, optimized, current_price, template):
    if not valid_prices:
        return None
    conservative = min(valid_prices)
    balanced = optimized or sum(valid_prices) / len(valid_prices)
    aggressive = max(valid_prices)
    if balanced < conservative:
        balanced = conservative
    if aggressive < balanced:
        aggressive = balanced
    regime = template['industry_regime']
    return {
        'conservative': {'target_price': _price(conservative), 'position_guidance': 'LOW'},
        'balanced': {'target_price': _price(balanced), 'position_guidance': 'MEDIUM'},
        'aggressive': {'target_price': _price(aggressive), 'position_guidance': 'HIGH'},
        'selected_regime': regime.selected_regime,
        'regime_confidence': regime.regime_confidence,
        'regime_source': regime.regime_source,
        'regime_reasons': list(regime.regime_reasons),
        'industry_code': regime.industry_code,
        'index_code': regime.index_code,
        'mapping_version': regime.mapping_version,
        'rules_version': regime.rules_version,
        'tier_spacing': {
            'before': {'conservative': _price(min(valid_prices)), 'balanced': _price(optimized or sum(valid_prices) / len(valid_prices)), 'aggressive': _price(max(valid_prices))},
            'after': {'conservative': _price(conservative), 'balanced': _price(balanced), 'aggressive': _price(aggressive)},
        },
        'method_coverage': len(valid_prices),
        'current_price': _price(current_price),
        'downgrade_applied': regime.status != 'VALID',
        'downgrade_reason': regime.fallback_reason,
    }


class TraditionalValuationEngine:
    engine_version = '1.0'

    def __init__(self, loader=None, resolver=None):
        self.loader = loader or ValuationTemplateLoader()
        self.resolver = resolver or ValuationInputResolver()

    def calculate(self, security, asof_date, report_type='FY', financial_end_date=None, profit_bucket='formal', trigger_type='MANUAL', business_match_topn=0):
        template = self.loader.resolve(security.ts_code)
        inputs = self.resolver.resolve(
            security, asof_date, report_type=report_type, financial_end_date=financial_end_date,
            allow_express=profit_bucket == 'blended',
        )
        params = template['params']
        income = inputs['express'] if inputs['express'] is not None else inputs['income']
        indicator = inputs['indicator']
        balance = inputs['balance']
        fundamental = inputs['fundamental']
        shares = _number(getattr(fundamental, 'total_share', None)) if fundamental else None
        net_income = _number(inputs['ttm_net_income'] if inputs['express'] is None else getattr(income, 'n_income_attr_p', None) or getattr(income, 'n_income', None))
        revenue = _number(inputs['ttm_revenue'] if inputs['express'] is None else getattr(income, 'revenue', None))
        equity = _number(getattr(balance, 'total_hldr_eqy_exc_min_int', None)) if balance else None
        growth = _number(getattr(indicator, 'netprofit_yoy', None) or getattr(indicator, 'or_yoy', None)) if indicator else None
        price = _number(inputs['current_price'])
        methods = {}
        skipped_methods = {}
        if net_income and shares and shares > 0:
            eps = _per_share(net_income, shares)
            methods['pe'] = {'valuation_price': _price(eps * float(params.get('pe_target', 14))), 'input': {'eps': eps}}
            if growth and growth > 0:
                effective_growth = min(max(growth, 5.0), 80.0)
                target_pe = min(max(float(params.get('peg_target', 1)) * effective_growth, 5.0), 45.0)
                methods['peg'] = {
                    'valuation_price': _price(eps * target_pe),
                    'input': {
                        'eps': eps,
                        'growth_pct': effective_growth,
                        'raw_growth_pct': growth,
                        'target_pe': target_pe,
                    },
                }
        if revenue and shares and shares > 0:
            revenue_per_share = _per_share(revenue, shares)
            methods['ps'] = {'valuation_price': _price(revenue_per_share * float(params.get('ps_target', 1.8))), 'input': {'revenue_per_share': revenue_per_share}}
        if equity and shares and shares > 0:
            book_value_per_share = _per_share(equity, shares)
            methods['pb'] = {'valuation_price': _price(book_value_per_share * float(params.get('pb_target', 1.8))), 'input': {'book_value_per_share': book_value_per_share}}
        if inputs['cashflow'] and shares and shares > 0:
            fcff_dcf = _calculate_fcff_dcf(
                _number(inputs['ttm_cashflow']),
                shares,
                _number(inputs['cash']),
                _number(inputs['debt']),
                (params.get('dcf_kwargs') or {}),
            )
            if fcff_dcf and fcff_dcf['valuation_price'] is not None:
                methods['fcff_dcf'] = fcff_dcf
        if inputs['dividend'] and shares and shares > 0:
            dividend_per_ten = _number(inputs['dividend'].cash_div_tax or inputs['dividend'].stk_div)
            rate = float((params.get('ddm_kwargs') or {}).get('discount_rate', 0.115))
            growth_rate = float((params.get('ddm_kwargs') or {}).get('dividend_growth_rate', 0.015))
            if dividend_per_ten and rate > growth_rate:
                total_dividend = dividend_per_ten / 10.0 * shares
                methods['ddm'] = {
                    'valuation_price': _price(
                        total_dividend * (1.0 + growth_rate) / (rate - growth_rate) / shares
                    ),
                    'input': {
                        'dividend_per_share': dividend_per_ten / 10.0,
                        'discount_rate': rate,
                        'dividend_growth_rate': growth_rate,
                    },
                }

        ev_ebitda, ev_reason = calculate_ev_ebitda(
            income, balance, shares, params.get('ev_ebitda_target', 9.0),
            per_share_scale=FINANCIAL_AMOUNT_TO_PER_SHARE_SCALE,
        )
        if ev_ebitda is not None:
            methods['ev_ebitda'] = ev_ebitda
        else:
            skipped_methods['ev_ebitda'] = ev_reason

        sw_history, history_reason, history_meta = calculate_sw_history(
            template.get('metrics') or {}, shares, net_income, revenue, equity,
            per_share_scale=FINANCIAL_AMOUNT_TO_PER_SHARE_SCALE,
        )
        if sw_history is not None:
            methods['sw_history'] = sw_history
        else:
            skipped_methods['sw_history'] = history_reason

        valid_prices = [
            float(item['valuation_price'])
            for item in methods.values()
            if item.get('valuation_price') and float(item['valuation_price']) > 0
        ]
        raw_composite = sum(valid_prices) / len(valid_prices) if valid_prices else None
        conservative = min(valid_prices) if valid_prices else None
        dispersion = (max(valid_prices) - min(valid_prices)) / raw_composite if raw_composite and len(valid_prices) > 1 else 0.0
        optimized = raw_composite * max(0.65, 1.0 - min(0.2, dispersion * 0.25)) if raw_composite else None
        tiered_template = _tiered_template(valid_prices, optimized, price, template)

        scarcity_base_price = (methods.get('sw_history') or {}).get('valuation_price') or raw_composite
        scarcity, scarcity_reason = calculate_scarcity_overlay(
            scarcity_base_price,
            growth,
            _number(getattr(indicator, 'roe_dt', None) or getattr(indicator, 'roe', None)) if indicator else None,
            template.get('scarcity') or {},
        )
        if scarcity is not None:
            methods['scarcity_overlay'] = scarcity
        else:
            skipped_methods['scarcity_overlay'] = scarcity_reason

        candidate_summary = summarize_buy_candidate(price, methods)

        summary = {
            'composite_valuation_price_raw': raw_composite,
            'composite_valuation_price_optimized': optimized,
            'conservative_valuation_price_raw': conservative,
            'conservative_valuation_price_optimized': conservative * 0.95 if conservative else None,
            **candidate_summary,
            'method_count': len(valid_prices), 'dispersion_ratio': dispersion,
            'current_price': price, 'target_source': template['params'].get('target_source', 'template'),
            'skipped_methods': skipped_methods,
            'sw_history': history_meta,
            'traditional_tiered_template': tiered_template,
            'traditional_tiered_template_by_variant': {'default': tiered_template} if tiered_template else {},
        }
        variants = {
            'sw_l3_baseline': {
                'template': template,
                'methods': methods,
                'summary': summary,
                'compare_group': 'sw_l3_baseline',
                'match_score': None,
            },
        }
        if business_match_topn > 0:
            match_result = build_business_industry_match(
                security=security, asof_date=asof_date, level='L2', top_n=business_match_topn,
            )
            for match in match_result.get('matches') or []:
                try:
                    variant_template = self.loader.resolve_industry(
                        match['industry_code'], match['industry_level'], match['industry_name'],
                    )
                except Exception:
                    continue
                if variant_template['code'] == template['code'] and variant_template['level'] == template['level']:
                    continue
                variant_result = self._calculate_with_template(
                    template=variant_template, inputs=inputs, current_price=price,
                )
                variant_result.update({
                    'compare_group': 'business_match',
                    'match_score': match.get('score'),
                    'match_rank': match.get('rank'),
                    'match_provenance': match,
                })
                variants[f"business_match|{match['industry_level']}|{match['industry_code']}|{match['industry_name']}"[:128]] = variant_result
        return {'template': template, 'inputs': inputs, 'methods': methods, 'summary': summary, 'variants': variants, 'trigger_type': trigger_type}

    def _calculate_with_template(self, *, template, inputs, current_price):
        # Variant calculations reuse the already resolved point-in-time input.
        return self._calculate_variant_methods(template, inputs, current_price)

    def _calculate_variant_methods(self, template, inputs, current_price):
        params = template['params']
        income = inputs['express'] if inputs['express'] is not None else inputs['income']
        indicator, balance, fundamental = inputs['indicator'], inputs['balance'], inputs['fundamental']
        shares = _number(getattr(fundamental, 'total_share', None)) if fundamental else None
        net_income = _number(inputs['ttm_net_income'] if inputs['express'] is None else getattr(income, 'n_income_attr_p', None) or getattr(income, 'n_income', None))
        revenue = _number(inputs['ttm_revenue'] if inputs['express'] is None else getattr(income, 'revenue', None))
        equity = _number(getattr(balance, 'total_hldr_eqy_exc_min_int', None)) if balance else None
        methods = {}
        if net_income and shares and shares > 0:
            eps = _per_share(net_income, shares)
            methods['pe'] = {'valuation_price': _price(eps * float(params.get('pe_target', 14)))}
            growth = _number(getattr(indicator, 'netprofit_yoy', None) or getattr(indicator, 'or_yoy', None)) if indicator else None
            if growth and growth > 0:
                methods['peg'] = {'valuation_price': _price(eps * float(params.get('peg_target', 1)) * growth)}
        if revenue and shares and shares > 0:
            methods['ps'] = {'valuation_price': _price(_per_share(revenue, shares) * float(params.get('ps_target', 1.8)))}
        if equity and shares and shares > 0:
            methods['pb'] = {'valuation_price': _price(_per_share(equity, shares) * float(params.get('pb_target', 1.8)))}
        valid_prices = [float(row['valuation_price']) for row in methods.values() if row.get('valuation_price')]
        composite = sum(valid_prices) / len(valid_prices) if valid_prices else None
        conservative = min(valid_prices) if valid_prices else None
        dispersion = (max(valid_prices) - min(valid_prices)) / composite if composite and len(valid_prices) > 1 else 0.0
        optimized = composite * max(0.65, 1.0 - min(0.2, dispersion * 0.25)) if composite else None
        candidate_summary = summarize_buy_candidate(current_price, methods)
        return {
            'template': template, 'methods': methods,
            'summary': {
                'composite_valuation_price_raw': composite,
                'composite_valuation_price_optimized': optimized,
                'conservative_valuation_price_raw': conservative,
                'conservative_valuation_price_optimized': conservative * 0.95 if conservative else None,
                **candidate_summary,
                'method_count': len(valid_prices), 'dispersion_ratio': dispersion,
                'current_price': current_price,
            },
        }

    @transaction.atomic
    def persist(self, result, report_type, profit_bucket='formal', valuation_variant='default', style_profile='baseline', refresh_run_key=None):
        template = result['template']
        inputs = result['inputs']
        summary = result['summary']
        refresh_run_key = refresh_run_key or uuid4().hex[:32]
        parameter, _ = TraditionalValuationParameterVersion.objects.get_or_create(
            market='CN', sw_level=template['level'], sw_code=template['code'],
            parameter_version=template['parameter_version'],
            defaults={'sw_name': template['name'], 'parameters': template['params'], 'source_hash': template['source_hash'], 'source_trade_date': template['source_trade_date'], 'is_active': True},
        )
        snapshot = TraditionalValuationSnapshot.objects.update_or_create(
            security=inputs['security'], asof_date=inputs['asof_date'], source_trade_date=inputs['source_trade_date'],
            report_type=report_type, financial_end_date=inputs['financial_end_date'], profit_bucket=profit_bucket,
            valuation_variant=valuation_variant, parameter_version=parameter.parameter_version,
            valuation_engine_version=self.engine_version, refresh_run_key=refresh_run_key,
            defaults={
                'financial_ann_date': inputs['financial_ann_date'], 'style_profile': style_profile,
                'parameter_source_hash': template['source_hash'], 'trigger_type': result['trigger_type'],
                'refresh_run_key': refresh_run_key,
                'current_price': summary.get('current_price'),
                'composite_valuation_price_raw': summary.get('composite_valuation_price_raw'),
                'composite_valuation_price_optimized': summary.get('composite_valuation_price_optimized'),
                'conservative_valuation_price_raw': summary.get('conservative_valuation_price_raw'),
                'conservative_valuation_price_optimized': summary.get('conservative_valuation_price_optimized'),
                'methods': result['methods'], 'summary': summary,
                'provenance': {
                    'profit_source': inputs['profit_source'],
                    'sw_level': template['level'], 'sw_code': template['code'],
                    'mapping_version': template['mapping_version'],
                    'mapping_source_hash': template['mapping_source_hash'],
                    'rules_version': template['industry_regime'].rules_version,
                },
            },
        )[0]
        risk = build_risk_payload(result)
        risk_row, _ = TraditionalValuationRiskSnapshot.objects.update_or_create(snapshot=snapshot, defaults=risk)
        latest, _ = TraditionalValuationSnapshotLatest.objects.update_or_create(
            security=inputs['security'], report_type=report_type, profit_bucket=profit_bucket,
            valuation_variant=valuation_variant, style_profile=style_profile,
            defaults={'snapshot': snapshot, 'asof_date': inputs['asof_date'], 'source_trade_date': inputs['source_trade_date'], 'composite_valuation_price': summary.get('composite_valuation_price_optimized'), 'conservative_valuation_price': summary.get('conservative_valuation_price_optimized'), 'risk_snapshot': risk_row, 'parameter_version': parameter.parameter_version, 'valuation_engine_version': self.engine_version},
        )
        variants = result.get('variants') or {
            valuation_variant: {
                'summary': summary,
                'compare_group': valuation_variant,
                'match_score': None,
            },
        }
        ranked_variants = sorted(
            variants.items(),
            key=lambda item: float((item[1].get('summary') or {}).get('composite_valuation_price_optimized') or 0),
            reverse=True,
        )
        active_variant = ranked_variants[0][0] if ranked_variants else valuation_variant
        for variant_name, variant_result in variants.items():
            variant_summary = variant_result.get('summary') or {}
            variant_template = variant_result.get('template') or template
            TraditionalValuationVariantSummaryLatest.objects.update_or_create(
                security=inputs['security'], report_type=report_type, profit_bucket=profit_bucket,
                valuation_variant=variant_name[:128], style_profile=style_profile,
                defaults={
                    'snapshot': snapshot, 'asof_date': inputs['asof_date'],
                    'compare_group': variant_result.get('compare_group') or variant_name.split('|', 1)[0],
                    'industry_level': variant_template.get('level', ''),
                    'industry_code': variant_template.get('code', ''),
                    'industry_name': variant_template.get('name', ''),
                    'match_rank': variant_result.get('match_rank'),
                    'match_score': variant_result.get('match_score'),
                    'composite_valuation_price': variant_summary.get('composite_valuation_price_optimized'),
                    'conservative_valuation_price': variant_summary.get('conservative_valuation_price_optimized'),
                    'method_coverage': int(variant_summary.get('method_count') or 0),
                    'is_active_variant': variant_name == active_variant,
                    'provenance': {
                        **(variant_result.get('match_provenance') or {}),
                        'buy_candidate_summary': {
                            key: variant_summary.get(key)
                            for key in (
                                'buy_candidate',
                                'buy_candidate_reason',
                                'buy_candidate_rule_version',
                                'undervalue_score',
                                'valuation_valid_methods',
                                'valuation_under_methods',
                                'valuation_core_methods',
                            )
                        },
                    },
                },
            )
        return snapshot, latest, risk_row