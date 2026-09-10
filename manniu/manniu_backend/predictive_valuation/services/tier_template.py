from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from django.conf import settings

from market_data.services.industry import IndustryMappingError, resolve_industry_regime
from market_data.services.regime import get_market_regime, get_security_regime


class PredictiveTierTemplateService:
    """Build and audit the persisted three-tier display result."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config if config is not None else self._load_config()

    @staticmethod
    def _load_config() -> dict[str, Any]:
        path = Path(settings.PREDICTIVE_VALUATION_CONFIG)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        payload = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        return payload if isinstance(payload, dict) else {}

    def build(self, *, security, asof_date, close: float | None, target_return_pct: float, target_low_pct: float, target_high_pct: float, target_price: float | None, target_price_low: float | None, target_price_high: float | None, risk_level: str, signal_score: float, feature_quality: dict[str, Any]) -> dict[str, Any]:
        industry = self._industry_regime(security)
        regime_config = self.config.get('valuation_mapping', {}).get('market_regime', {}) or {}
        market = get_market_regime(asof_date=asof_date, benchmark_ts_code=regime_config.get('benchmark_ts_code', '000001.SH'))
        security_regime = get_security_regime(security=security, asof_date=asof_date)
        tier_config = (self.config.get('tier_template') or {}).get('regimes', {})
        pack = tier_config.get(industry['selected_regime']) or tier_config.get('balanced') or {}
        lower = float(pack.get('lower_multiplier', 0.80))
        upper = float(pack.get('upper_multiplier', 1.20))
        min_gap = float(pack.get('minimum_gap_pct', 0.03))
        downgrade_reasons: list[str] = []
        if market.regime == 'BEAR' or security_regime.regime == 'RISK_OFF':
            lower = max(lower, float(pack.get('risk_off_lower_multiplier', 0.90)))
            upper = min(upper, float(pack.get('risk_off_upper_multiplier', 1.10)))
            downgrade_reasons.append('market_or_security_risk_off')
        if industry['regime_confidence'] < float((self.config.get('tier_template') or {}).get('minimum_regime_confidence', 0.5)):
            downgrade_reasons.append('low_regime_confidence')
        if feature_quality.get('degraded'):
            downgrade_reasons.append('degraded_features')
        if risk_level == 'HIGH':
            downgrade_reasons.append('high_inference_risk')

        balanced_return = float(target_return_pct)
        conservative_return = min(float(target_low_pct), balanced_return - min_gap * 100)
        aggressive_return = max(float(target_high_pct), balanced_return + min_gap * 100)
        conservative_return = balanced_return - (balanced_return - conservative_return) * lower
        aggressive_return = balanced_return + (aggressive_return - balanced_return) * upper
        if downgrade_reasons:
            upper = min(upper, float(pack.get('downgrade_upper_multiplier', 1.08)))
            aggressive_return = min(aggressive_return, balanced_return + abs(balanced_return - conservative_return) * 0.8)
        conservative_return = min(conservative_return, balanced_return - min_gap * 100)
        aggressive_return = max(aggressive_return, balanced_return + min_gap * 100)

        def price_for(return_pct: float, fallback: float | None = None) -> float | None:
            return round(close * (1 + return_pct / 100), 6) if close is not None else fallback

        positions = (self.config.get('tier_template') or {}).get('position_guidance', {})
        return {
            'conservative': {'target_price': price_for(conservative_return, target_price_low), 'target_price_low': price_for(conservative_return, target_price_low), 'target_price_high': price_for(balanced_return, target_price), 'expected_return_pct': round(conservative_return, 6), 'expected_return_low_pct': round(float(target_low_pct), 6), 'expected_return_high_pct': round(balanced_return, 6), 'risk_level': 'HIGH' if risk_level == 'HIGH' else 'MEDIUM', 'position_guidance': positions.get('conservative', 'LOW')},
            'balanced': {'target_price': price_for(balanced_return, target_price), 'target_price_low': price_for(float(target_low_pct), target_price_low), 'target_price_high': price_for(float(target_high_pct), target_price_high), 'expected_return_pct': round(balanced_return, 6), 'expected_return_low_pct': round(float(target_low_pct), 6), 'expected_return_high_pct': round(float(target_high_pct), 6), 'risk_level': risk_level, 'position_guidance': positions.get('balanced', 'MEDIUM')},
            'aggressive': {'target_price': price_for(aggressive_return, target_price_high), 'target_price_low': price_for(balanced_return, target_price), 'target_price_high': price_for(aggressive_return, target_price_high), 'expected_return_pct': round(aggressive_return, 6), 'expected_return_low_pct': round(balanced_return, 6), 'expected_return_high_pct': round(float(target_high_pct), 6), 'risk_level': risk_level, 'position_guidance': positions.get('aggressive', 'HIGH')},
            'selected_regime': industry['selected_regime'], 'regime_confidence': industry['regime_confidence'], 'regime_source': industry['regime_source'], 'regime_reasons': industry['regime_reasons'], 'fallback_reason': industry['fallback_reason'], 'industry_code': industry['industry_code'], 'mapping_version': industry['mapping_version'], 'rules_version': industry['rules_version'],
            'market_regime': market.regime, 'security_regime': security_regime.regime, 'market_regime_source': market.source, 'security_regime_source': security_regime.source,
            'tier_spacing': {'configured_min_gap_pct': min_gap * 100, 'before': {'conservative': target_price_low, 'balanced': target_price, 'aggressive': target_price_high}, 'after': {'conservative': price_for(conservative_return, target_price_low), 'balanced': price_for(balanced_return, target_price), 'aggressive': price_for(aggressive_return, target_price_high)}},
            'range_multiplier': {'lower': lower, 'upper': upper}, 'downgrade_applied': bool(downgrade_reasons), 'downgrade_reason': ','.join(downgrade_reasons), 'model_risk_level': risk_level, 'signal_score': round(float(signal_score), 4),
            'market_source_trade_date': market.source_trade_date.isoformat() if market.source_trade_date else None, 'security_source_trade_date': security_regime.source_trade_date.isoformat() if security_regime.source_trade_date else None,
        }

    @staticmethod
    def _industry_regime(security) -> dict[str, Any]:
        try:
            result = resolve_industry_regime(security=security)
            return {'selected_regime': result.selected_regime, 'regime_confidence': result.regime_confidence, 'regime_source': result.regime_source, 'regime_reasons': list(result.regime_reasons), 'fallback_reason': result.fallback_reason, 'industry_code': result.industry_code, 'mapping_version': result.mapping_version, 'rules_version': result.rules_version}
        except (IndustryMappingError, ValueError):
            return {'selected_regime': 'balanced', 'regime_confidence': 0.0, 'regime_source': 'fallback', 'regime_reasons': ['industry_mapping_unavailable'], 'fallback_reason': 'industry_mapping_unavailable', 'industry_code': '', 'mapping_version': '', 'rules_version': ''}