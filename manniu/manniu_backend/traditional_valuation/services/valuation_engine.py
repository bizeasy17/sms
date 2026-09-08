from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from traditional_valuation.models import (
    TraditionalValuationParameterVersion,
    TraditionalValuationRiskSnapshot,
    TraditionalValuationSnapshot,
    TraditionalValuationSnapshotLatest,
)
from .config import ValuationTemplateLoader
from .input_resolver import ValuationInputResolver
from .risk_service import build_risk_payload
from .extended_methods import (
    calculate_ev_ebitda,
    calculate_scarcity_overlay,
    calculate_sw_history,
)


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _price(value):
    return round(float(value), 6) if value is not None and value > 0 else None


class TraditionalValuationEngine:
    engine_version = '1.0'

    def __init__(self, loader=None, resolver=None):
        self.loader = loader or ValuationTemplateLoader()
        self.resolver = resolver or ValuationInputResolver()

    def calculate(self, security, asof_date, report_type='FY', financial_end_date=None, profit_bucket='formal', trigger_type='MANUAL'):
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
        net_income = _number(getattr(income, 'n_income_attr_p', None) or getattr(income, 'n_income', None))
        revenue = _number(getattr(income, 'revenue', None))
        equity = _number(getattr(balance, 'total_hldr_eqy_exc_min_int', None)) if balance else None
        growth = _number(getattr(indicator, 'netprofit_yoy', None) or getattr(indicator, 'or_yoy', None)) if indicator else None
        price = _number(inputs['current_price'])
        methods = {}
        skipped_methods = {}
        if net_income and shares and shares > 0:
            eps = net_income / shares
            methods['pe'] = {'valuation_price': _price(eps * float(params.get('pe_target', 14))), 'input': {'eps': eps}}
            if growth and growth > 0:
                methods['peg'] = {'valuation_price': _price(eps * float(params.get('peg_target', 1)) * growth), 'input': {'eps': eps, 'growth_pct': growth}}
        if revenue and shares and shares > 0:
            methods['ps'] = {'valuation_price': _price((revenue / shares) * float(params.get('ps_target', 1.8))), 'input': {'revenue_per_share': revenue / shares}}
        if equity and shares and shares > 0:
            methods['pb'] = {'valuation_price': _price((equity / shares) * float(params.get('pb_target', 1.8))), 'input': {'book_value_per_share': equity / shares}}
        if inputs['cashflow'] and shares and shares > 0:
            ocf = _number(inputs['cashflow'].n_cashflow_act)
            rate = float((params.get('dcf_kwargs') or {}).get('discount_rate', 0.105))
            if ocf and rate > 0:
                methods['fcff_dcf'] = {'valuation_price': _price((ocf / shares) / rate), 'input': {'ocf_per_share': ocf / shares, 'discount_rate': rate}}
        if inputs['dividend'] and shares and shares > 0:
            dividend = _number(inputs['dividend'].cash_div_tax or inputs['dividend'].stk_div)
            rate = float((params.get('ddm_kwargs') or {}).get('discount_rate', 0.115))
            if dividend and rate > 0:
                methods['ddm'] = {'valuation_price': _price((dividend / rate) / shares), 'input': {'dividend_per_share': dividend / shares, 'discount_rate': rate}}

        ev_ebitda, ev_reason = calculate_ev_ebitda(
            income, balance, shares, params.get('ev_ebitda_target', 9.0)
        )
        if ev_ebitda is not None:
            methods['ev_ebitda'] = ev_ebitda
        else:
            skipped_methods['ev_ebitda'] = ev_reason

        sw_history, history_reason, history_meta = calculate_sw_history(
            template.get('metrics') or {}, shares, net_income, revenue, equity
        )
        if sw_history is not None:
            methods['sw_history'] = sw_history
        else:
            skipped_methods['sw_history'] = history_reason

        valid_prices = [float(item['valuation_price']) for item in methods.values() if item.get('valuation_price')]
        raw_composite = sum(valid_prices) / len(valid_prices) if valid_prices else None
        conservative = min(valid_prices) if valid_prices else None
        dispersion = (max(valid_prices) - min(valid_prices)) / raw_composite if raw_composite and len(valid_prices) > 1 else 0.0
        optimized = raw_composite * max(0.65, 1.0 - min(0.2, dispersion * 0.25)) if raw_composite else None

        scarcity, scarcity_reason = calculate_scarcity_overlay(
            raw_composite,
            growth,
            _number(getattr(indicator, 'roe_dt', None) or getattr(indicator, 'roe', None)) if indicator else None,
            template.get('scarcity') or {},
        )
        if scarcity is not None:
            methods['scarcity_overlay'] = scarcity
        else:
            skipped_methods['scarcity_overlay'] = scarcity_reason

        summary = {
            'composite_valuation_price_raw': raw_composite,
            'composite_valuation_price_optimized': optimized,
            'conservative_valuation_price_raw': conservative,
            'conservative_valuation_price_optimized': conservative * 0.95 if conservative else None,
            'method_count': len(valid_prices), 'dispersion_ratio': dispersion,
            'current_price': price, 'target_source': template['params'].get('target_source', 'template'),
            'skipped_methods': skipped_methods,
            'sw_history': history_meta,
        }
        return {'template': template, 'inputs': inputs, 'methods': methods, 'summary': summary, 'trigger_type': trigger_type}

    @transaction.atomic
    def persist(self, result, report_type, profit_bucket='formal', valuation_variant='default', style_profile='baseline'):
        template = result['template']
        inputs = result['inputs']
        summary = result['summary']
        parameter, _ = TraditionalValuationParameterVersion.objects.get_or_create(
            market='CN', sw_level=template['level'], sw_code=template['code'],
            parameter_version=template['parameter_version'],
            defaults={'sw_name': template['name'], 'parameters': template['params'], 'source_hash': template['source_hash'], 'source_trade_date': template['source_trade_date'], 'is_active': True},
        )
        snapshot = TraditionalValuationSnapshot.objects.update_or_create(
            security=inputs['security'], asof_date=inputs['asof_date'], source_trade_date=inputs['source_trade_date'],
            report_type=report_type, financial_end_date=inputs['financial_end_date'], profit_bucket=profit_bucket,
            valuation_variant=valuation_variant, parameter_version=parameter.parameter_version,
            valuation_engine_version=self.engine_version,
            defaults={
                'financial_ann_date': inputs['financial_ann_date'], 'style_profile': style_profile,
                'parameter_source_hash': template['source_hash'], 'trigger_type': result['trigger_type'],
                'current_price': summary.get('current_price'),
                'composite_valuation_price_raw': summary.get('composite_valuation_price_raw'),
                'composite_valuation_price_optimized': summary.get('composite_valuation_price_optimized'),
                'conservative_valuation_price_raw': summary.get('conservative_valuation_price_raw'),
                'conservative_valuation_price_optimized': summary.get('conservative_valuation_price_optimized'),
                'methods': result['methods'], 'summary': summary,
                'provenance': {'profit_source': inputs['profit_source'], 'sw_level': template['level'], 'sw_code': template['code']},
            },
        )[0]
        risk = build_risk_payload(result)
        risk_row, _ = TraditionalValuationRiskSnapshot.objects.update_or_create(snapshot=snapshot, defaults=risk)
        latest, _ = TraditionalValuationSnapshotLatest.objects.update_or_create(
            security=inputs['security'], report_type=report_type, profit_bucket=profit_bucket,
            valuation_variant=valuation_variant, style_profile=style_profile,
            defaults={'snapshot': snapshot, 'asof_date': inputs['asof_date'], 'source_trade_date': inputs['source_trade_date'], 'composite_valuation_price': summary.get('composite_valuation_price_optimized'), 'conservative_valuation_price': summary.get('conservative_valuation_price_optimized'), 'risk_snapshot': risk_row, 'parameter_version': parameter.parameter_version, 'valuation_engine_version': self.engine_version},
        )
        return snapshot, latest, risk_row