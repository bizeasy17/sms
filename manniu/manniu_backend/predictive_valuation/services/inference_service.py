from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml
from django.conf import settings
from django.utils import timezone

from market_data.models import MarketBarDailyHistory, Security, StockDailyFundamentalHistory
from market_data.services.regime import get_market_regime
from predictive_valuation.models import (
    PredictiveFinancialFeaturePanel,
    PredictiveValuationCurrent,
    PredictiveValuationSnapshot,
)
from predictive_valuation.services.artifact_registry import PredictiveArtifactRegistry
from predictive_valuation.services.tier_template import PredictiveTierTemplateService


class PredictiveInferenceService:
    """Run a report-type-specific bundle against persisted feature and market records."""

    def __init__(self, registry: PredictiveArtifactRegistry | None = None):
        self.registry = registry or PredictiveArtifactRegistry()
        self._bundles: dict[str, dict[str, Any]] = {}
        self._impute_stats: dict[str, dict[str, float | None]] = {}
        self._config: dict[str, Any] | None = None

    def predict_panel(
        self,
        panel: PredictiveFinancialFeaturePanel,
        horizon: str = '1M',
        trigger_type: str = 'MANUAL',
        *,
        batch_key: str = '',
        refresh_reason: str = '',
        run_key: str = '',
        is_backfill: bool = False,
        anchor_mode: str = 'latest',
    ) -> PredictiveValuationSnapshot:
        try:
            return self._predict_panel(
                panel,
                horizon=horizon,
                trigger_type=trigger_type,
                batch_key=batch_key,
                refresh_reason=refresh_reason,
                run_key=run_key,
                is_backfill=is_backfill,
                anchor_mode=anchor_mode,
            )
        except Exception as exc:
            self._persist_failure(
                panel,
                horizon=horizon,
                trigger_type=trigger_type,
                batch_key=batch_key,
                refresh_reason=refresh_reason,
                run_key=run_key,
                is_backfill=is_backfill,
                anchor_mode=anchor_mode,
                error=str(exc),
            )
            raise

    def predict_fusion(
        self,
        panels: list[PredictiveFinancialFeaturePanel],
        horizon: str = '1M',
        trigger_type: str = 'MANUAL',
        *,
        batch_key: str = '',
        refresh_reason: str = '',
        run_key: str = '',
        is_backfill: bool = False,
        anchor_mode: str = 'latest',
    ) -> PredictiveValuationSnapshot:
        """Predict quarter components independently and persist their weighted fusion."""
        if not panels:
            raise ValueError('Fusion requires at least one quarter panel')
        security = panels[0].security
        if any(panel.security_id != security.id for panel in panels):
            raise ValueError('Fusion panels must belong to one security')

        config = (self._load_config().get('valuation_mapping', {}) or {}).get('fusion', {}) or {}
        base_weights = {str(key).upper(): float(value) for key, value in (config.get('base_weights') or {}).items()}
        confidence_weights = {str(key).upper(): float(value) for key, value in (config.get('confidence_weights') or {}).items()}
        half_life = max(1.0, float(config.get('freshness_half_life_days', 365)))
        component_rows: list[tuple[PredictiveValuationSnapshot, str]] = []
        failures: dict[str, str] = {}
        for panel in sorted(panels, key=lambda item: item.report_type):
            report_type = panel.report_type.upper()
            try:
                snapshot = self.predict_panel(
                    panel, horizon=horizon, trigger_type=trigger_type,
                    batch_key=batch_key, refresh_reason=refresh_reason,
                    run_key=run_key, is_backfill=is_backfill,
                    anchor_mode=anchor_mode,
                )
                if snapshot.last_error:
                    raise RuntimeError(snapshot.last_error)
                component_rows.append((snapshot, report_type))
            except Exception as exc:
                failures[report_type] = f'{type(exc).__name__}: {exc}'

        if not component_rows:
            raise ValueError(f'Fusion failed: no quarter component succeeded ({failures})')

        fusion_asof = max(snapshot.asof_date for snapshot, _ in component_rows)
        component: dict[str, dict[str, Any]] = {}
        weights: dict[str, float] = {}
        for snapshot, report_type in component_rows:
            age_days = max(0, (fusion_asof - snapshot.asof_date).days)
            freshness = float(np.exp(-age_days / half_life))
            confidence = self._fusion_confidence(snapshot.signal_score)
            base = base_weights.get(report_type, 1.0)
            confidence_factor = confidence_weights.get(confidence, 1.0)
            weights[report_type] = base * freshness * confidence_factor
            component[report_type] = {
                'status': 'SUCCEEDED', 'report_type': report_type,
                'asof_date': snapshot.asof_date.isoformat(),
                'financial_end_date': snapshot.financial_end_date.isoformat() if snapshot.financial_end_date else None,
                'model_version': snapshot.model_version,
                'signal_score': float(snapshot.signal_score) if snapshot.signal_score is not None else None,
                'up_probability': float(snapshot.up_probability) if snapshot.up_probability is not None else None,
                'earnings_growth': (snapshot.explain or {}).get('pred_earnings_growth'),
                'target_return_pct': float(snapshot.target_return_pct) if snapshot.target_return_pct is not None else None,
                'target_return_low_pct': float(snapshot.target_return_low_pct) if snapshot.target_return_low_pct is not None else None,
                'target_return_high_pct': float(snapshot.target_return_high_pct) if snapshot.target_return_high_pct is not None else None,
                'target_price': float(snapshot.target_price) if snapshot.target_price is not None else None,
                'target_price_low': float(snapshot.target_price_low) if snapshot.target_price_low is not None else None,
                'target_price_high': float(snapshot.target_price_high) if snapshot.target_price_high is not None else None,
                'base_weight': base, 'freshness_factor': freshness,
                'confidence': confidence, 'confidence_factor': confidence_factor,
            }
        for report_type, error in failures.items():
            component[report_type] = {'status': 'FAILED', 'report_type': report_type, 'error': error}

        total_weight = sum(weights.values())
        if total_weight <= 0:
            raise ValueError('Fusion failed: component weights are zero')
        normalized = {report_type: weight / total_weight for report_type, weight in weights.items()}

        def weighted(field: str) -> float | None:
            values = [
                (component[report_type].get(field), normalized[report_type])
                for report_type in normalized if component[report_type].get(field) is not None
            ]
            return None if not values else sum(float(value) * weight for value, weight in values) / sum(weight for _, weight in values)

        center_score = weighted('signal_score')
        probability = weighted('up_probability')
        latest = max((snapshot for snapshot, _ in component_rows), key=lambda snapshot: snapshot.asof_date)
        fusion_trace = {
            'components': component, 'normalized_weights': normalized,
            'failed_components': failures,
            'data_status': 'PARTIAL_SUCCESS' if failures else 'COMPLETE',
            'strict_live_eligible': not failures,
        }
        snapshot_defaults = {
            'horizon': horizon, 'report_type': 'FUSION', 'model_version': 'fusion',
            'feature_contract_version': latest.feature_contract_version, 'artifact_hash': '',
            'source_market_date': latest.source_market_date,
            'financial_end_date': latest.financial_end_date,
            'financial_ann_date': latest.financial_ann_date,
            'financial_source_as_of_date': latest.financial_source_as_of_date,
            'financial_report_type': 'FUSION', 'financial_fiscal_year': latest.financial_fiscal_year,
            'feature_data_source': latest.feature_data_source, 'trigger_type': trigger_type,
            'signal_score': self._decimal(center_score), 'up_probability': self._decimal(probability),
            'target_return_pct': self._decimal(weighted('target_return_pct')),
            'target_return_low_pct': self._decimal(weighted('target_return_low_pct')),
            'target_return_high_pct': self._decimal(weighted('target_return_high_pct')),
            'target_price': self._decimal(weighted('target_price')),
            'target_price_low': self._decimal(weighted('target_price_low')),
            'target_price_high': self._decimal(weighted('target_price_high')),
            'target_market_cap': None, 'risk_level': self._fusion_risk(center_score),
            'action': self._action(center_score or 50.0), 'batch_key': batch_key,
            'refresh_reason': refresh_reason or trigger_type,
            'refresh_detail': {'trigger_type': trigger_type, 'component_count': len(component_rows)},
            'triggered_at': timezone.now(), 'last_error': '',
            'snapshot_source': 'historical_backfill' if is_backfill else 'event_refresh',
            'anchor_mode': latest.anchor_mode, 'run_key': run_key, 'is_backfill': is_backfill,
            'backfill_run_id': run_key if is_backfill else '', 'market_regime': latest.market_regime,
            'security_regime': latest.security_regime, 'predictive_tiered_template': {},
            'explain': {'fusion': fusion_trace},
            'raw_result': {'report_type': 'FUSION', 'model_version': 'fusion', 'fusion': fusion_trace},
        }
        snapshot, _ = PredictiveValuationSnapshot.objects.update_or_create(
            security=security, report_type='FUSION', asof_date=fusion_asof, defaults=snapshot_defaults,
        )
        PredictiveValuationCurrent.objects.update_or_create(
            security=security, report_type='FUSION',
            defaults={
                'snapshot': snapshot, 'horizon': horizon, 'report_type': 'FUSION',
                'model_version': 'fusion', 'feature_contract_version': snapshot.feature_contract_version,
                'artifact_hash': '', 'asof_date': snapshot.asof_date,
                'signal_score': snapshot.signal_score, 'up_probability': snapshot.up_probability,
                'target_return_pct': snapshot.target_return_pct,
                'target_return_low_pct': snapshot.target_return_low_pct,
                'target_return_high_pct': snapshot.target_return_high_pct,
                'target_price': snapshot.target_price, 'target_price_low': snapshot.target_price_low,
                'target_price_high': snapshot.target_price_high, 'target_market_cap': None,
                'risk_level': snapshot.risk_level, 'action': snapshot.action,
                'feature_data_source': snapshot.feature_data_source, 'batch_key': snapshot.batch_key,
                'refresh_reason': snapshot.refresh_reason, 'refresh_detail': snapshot.refresh_detail,
                'triggered_at': snapshot.triggered_at, 'last_error': '', 'explain': snapshot.explain,
                'raw_result': snapshot.raw_result, 'market_regime': snapshot.market_regime,
                'security_regime': snapshot.security_regime, 'predictive_tiered_template': {},
            },
        )
        return snapshot

    @staticmethod
    def _fusion_confidence(score: Decimal | None) -> str:
        value = float(score) if score is not None else 50.0
        return 'HIGH' if value >= 65 else ('MEDIUM' if value >= 50 else 'LOW')

    @staticmethod
    def _fusion_risk(score: float | None) -> str:
        value = float(score) if score is not None else 50.0
        return 'LOW' if value >= 65 else ('MEDIUM' if value >= 50 else 'HIGH')

    @staticmethod
    def _decimal(value: float | None) -> Decimal | None:
        return None if value is None else Decimal(str(round(value, 8)))

    def _predict_panel(
        self,
        panel: PredictiveFinancialFeaturePanel,
        horizon: str = '1M',
        trigger_type: str = 'MANUAL',
        *,
        batch_key: str = '',
        refresh_reason: str = '',
        run_key: str = '',
        is_backfill: bool = False,
        anchor_mode: str = 'latest',
    ) -> PredictiveValuationSnapshot:
        artifact = self.registry.load_production(panel.report_type)
        bundle = self._load_bundle(artifact.report_type, artifact.model_path)
        feature_row, market_date, missing_features, unresolved_features = self._feature_row(panel, bundle['feature_cols'])
        probability = float(bundle['classifier'].predict_proba(feature_row)[0][1])
        earnings_growth = float(bundle['regressor'].predict(feature_row)[0])
        score = self._score(probability, earnings_growth)
        base_risk_level = self._risk_level(score)
        quality_guard = self._quality_risk_guard(panel, feature_row, score, base_risk_level)
        score = quality_guard['score']
        risk_level = quality_guard['risk_level']
        target = self._target_mapping(
            panel=panel,
            feature_row=feature_row,
            missing_features=missing_features,
            score=score,
            probability=probability,
            earnings_growth=earnings_growth,
            risk_level=risk_level,
            asof_date=market_date,
        )
        target_return_pct = target['target_return_pct']
        target_low_pct = target['target_return_low_pct']
        target_high_pct = target['target_return_high_pct']
        close = self._number(feature_row, 'close')
        market_cap = self._number(feature_row, 'total_mv')
        target['trace']['raw_targets'] = self._target_values(close, market_cap, target['target_return_pct_raw'], target['target_return_low_pct_raw'], target['target_return_high_pct_raw'])
        target['trace']['adjusted_targets'] = self._target_values(close, market_cap, target_return_pct, target_low_pct, target_high_pct)
        tier_template = PredictiveTierTemplateService().build(
            security=panel.security,
            asof_date=market_date,
            close=close,
            target_return_pct=target_return_pct,
            target_low_pct=target_low_pct,
            target_high_pct=target_high_pct,
            target_price=None if close is None else close * (1 + target_return_pct / 100),
            target_price_low=None if close is None else close * (1 + target_low_pct / 100),
            target_price_high=None if close is None else close * (1 + target_high_pct / 100),
            risk_level=risk_level,
            signal_score=score,
            feature_quality={'degraded': bool(unresolved_features)},
        )
        defaults = {
            'report_type': panel.report_type,
            'model_version': artifact.model_version,
            'feature_contract_version': str(self._load_config().get('feature_contract_version') or '').strip(),
            'artifact_hash': artifact.artifact_hash,
            'source_market_date': market_date,
            'financial_end_date': panel.end_date,
            'financial_ann_date': panel.ann_date,
            'financial_source_as_of_date': panel.source_as_of_date,
            'financial_report_type': panel.report_type,
            'feature_data_source': 'persisted_panel_market_history',
            'trigger_type': trigger_type,
            'signal_score': Decimal(str(round(score, 4))),
            'up_probability': Decimal(str(round(probability, 8))),
            'target_return_pct': Decimal(str(round(target_return_pct, 6))),
            'target_return_low_pct': Decimal(str(round(target_low_pct, 6))),
            'target_return_high_pct': Decimal(str(round(target_high_pct, 6))),
            'target_price': None if close is None else Decimal(str(round(close * (1 + target_return_pct / 100), 6))),
            'target_price_low': None if close is None else Decimal(str(round(close * (1 + target_low_pct / 100), 6))),
            'target_price_high': None if close is None else Decimal(str(round(close * (1 + target_high_pct / 100), 6))),
            'target_market_cap': None if market_cap is None else Decimal(str(round(market_cap * (1 + target_return_pct / 100), 4))),
            'risk_level': risk_level,
            'action': self._action(score),
            'batch_key': batch_key,
            'refresh_reason': refresh_reason or trigger_type,
            'refresh_detail': {'trigger_type': trigger_type},
            'triggered_at': timezone.now(),
            'last_error': '',
            'snapshot_source': 'historical_backfill' if is_backfill else 'event_refresh',
            'anchor_mode': anchor_mode,
            'run_key': run_key,
            'is_backfill': is_backfill,
            'backfill_run_id': run_key if is_backfill else '',
            'financial_fiscal_year': panel.fiscal_year,
            'market_regime': tier_template['market_regime'],
            'security_regime': tier_template['security_regime'],
            'predictive_tiered_template': tier_template,
            'explain': {
                'imputed_features': missing_features,
                'unresolved_features': unresolved_features,
                'pred_earnings_growth': earnings_growth,
                'quality_risk_guard': quality_guard,
                'target_mapping': target['trace'],
            },
            'raw_result': {
                'model_file': artifact.model_path.name,
                'report_type': artifact.report_type,
                'target_mapping': target,
            },
        }
        snapshot, _ = PredictiveValuationSnapshot.objects.update_or_create(
            security=panel.security,
            report_type=panel.report_type,
            asof_date=panel.source_as_of_date,
            defaults=defaults,
        )
        current = PredictiveValuationCurrent.objects.filter(
            security=panel.security, report_type=panel.report_type
        ).first()
        if current is None or snapshot.asof_date >= current.asof_date:
            PredictiveValuationCurrent.objects.update_or_create(
                security=panel.security,
                report_type=panel.report_type,
                defaults={
                    'snapshot': snapshot, 'horizon': snapshot.horizon, 'report_type': snapshot.report_type,
                    'model_version': snapshot.model_version, 'feature_contract_version': snapshot.feature_contract_version,
                    'artifact_hash': snapshot.artifact_hash, 'asof_date': snapshot.asof_date,
                    'signal_score': snapshot.signal_score, 'up_probability': snapshot.up_probability,
                    'target_return_pct': snapshot.target_return_pct,
                    'target_return_low_pct': snapshot.target_return_low_pct,
                    'target_return_high_pct': snapshot.target_return_high_pct,
                    'target_price': snapshot.target_price, 'target_price_low': snapshot.target_price_low,
                    'target_price_high': snapshot.target_price_high, 'target_market_cap': snapshot.target_market_cap,
                    'risk_level': snapshot.risk_level, 'action': snapshot.action,
                    'feature_data_source': snapshot.feature_data_source, 'batch_key': snapshot.batch_key,
                    'refresh_reason': snapshot.refresh_reason, 'refresh_detail': snapshot.refresh_detail,
                    'triggered_at': snapshot.triggered_at, 'last_error': snapshot.last_error,
                    'explain': snapshot.explain, 'raw_result': snapshot.raw_result,
                    'market_regime': snapshot.market_regime, 'security_regime': snapshot.security_regime,
                    'predictive_tiered_template': snapshot.predictive_tiered_template,
                },
            )
        return snapshot

    def _persist_failure(
        self,
        panel: PredictiveFinancialFeaturePanel,
        *,
        horizon: str,
        trigger_type: str,
        batch_key: str,
        refresh_reason: str,
        run_key: str,
        is_backfill: bool,
        anchor_mode: str,
        error: str,
    ) -> PredictiveValuationSnapshot:
        now = timezone.now()
        snapshot, _ = PredictiveValuationSnapshot.objects.update_or_create(
            security=panel.security,
            report_type=panel.report_type,
            asof_date=panel.source_as_of_date,
            defaults={
                'horizon': horizon,
                'feature_contract_version': str(self._load_config().get('feature_contract_version') or '').strip(),
                'financial_end_date': panel.end_date,
                'financial_ann_date': panel.ann_date,
                'financial_source_as_of_date': panel.source_as_of_date,
                'financial_report_type': panel.report_type,
                'financial_fiscal_year': panel.fiscal_year,
                'feature_data_source': 'persisted_panel_market_history',
                'trigger_type': trigger_type,
                'signal_score': None,
                'up_probability': None,
                'target_return_pct': None,
                'target_return_low_pct': None,
                'target_return_high_pct': None,
                'target_price': None,
                'target_price_low': None,
                'target_price_high': None,
                'target_market_cap': None,
                'risk_level': 'MEDIUM',
                'action': 'HOLD',
                'batch_key': batch_key,
                'refresh_reason': refresh_reason or trigger_type,
                'refresh_detail': {'trigger_type': trigger_type},
                'triggered_at': now,
                'last_error': error[:2000],
                'snapshot_source': 'historical_backfill' if is_backfill else 'event_refresh',
                'anchor_mode': anchor_mode,
                'run_key': run_key,
                'is_backfill': is_backfill,
                'backfill_run_id': run_key if is_backfill else '',
                'predictive_tiered_template': {},
                'explain': {},
                'raw_result': {},
            },
        )
        PredictiveValuationCurrent.objects.update_or_create(
            security=panel.security,
            report_type=panel.report_type,
            defaults={
                'snapshot': snapshot,
                'horizon': snapshot.horizon,
                'model_version': snapshot.model_version,
                'feature_contract_version': snapshot.feature_contract_version,
                'artifact_hash': snapshot.artifact_hash,
                'asof_date': snapshot.asof_date,
                'signal_score': None,
                'up_probability': None,
                'target_return_pct': None,
                'target_return_low_pct': None,
                'target_return_high_pct': None,
                'target_price': None,
                'target_price_low': None,
                'target_price_high': None,
                'target_market_cap': None,
                'risk_level': 'MEDIUM',
                'action': 'HOLD',
                'feature_data_source': snapshot.feature_data_source,
                'batch_key': snapshot.batch_key,
                'refresh_reason': snapshot.refresh_reason,
                'refresh_detail': snapshot.refresh_detail,
                'triggered_at': snapshot.triggered_at,
                'last_error': snapshot.last_error,
                'explain': {},
                'raw_result': {},
                'market_regime': '',
                'security_regime': '',
                'predictive_tiered_template': {},
            },
        )
        return snapshot

    def _feature_row(self, panel: PredictiveFinancialFeaturePanel, feature_columns: list[str]) -> tuple[pd.DataFrame, date, list[str], list[str]]:
        start = panel.source_as_of_date - timedelta(days=200)
        bar_columns = ['trade_date', 'close', 'pct_change', 'volume']
        fundamental_columns = ['trade_date', 'pe', 'pb', 'ps', 'total_mv', 'circ_mv', 'turnover_rate']
        bars = pd.DataFrame(
            list(MarketBarDailyHistory.objects.filter(
                security=panel.security, trade_date__gte=start, trade_date__lte=panel.source_as_of_date
            ).order_by('trade_date').values(*bar_columns)),
            columns=bar_columns,
        )
        fundamentals = pd.DataFrame(
            list(StockDailyFundamentalHistory.objects.filter(
                security=panel.security, trade_date__gte=start, trade_date__lte=panel.source_as_of_date
            ).order_by('trade_date').values(*fundamental_columns)),
            columns=fundamental_columns,
        )
        if bars.empty:
            raise ValueError(f'Market bars unavailable for {panel.security.ts_code} at {panel.source_as_of_date}')
        market = bars.merge(fundamentals, on='trade_date', how='left').sort_values('trade_date').reset_index(drop=True)
        for column in market.columns:
            if column != 'trade_date':
                market[column] = pd.to_numeric(market[column], errors='coerce')
        market['ret_5d'] = market['close'].replace(0, np.nan).pct_change(5)
        market['ret_lb'] = market['close'].replace(0, np.nan).pct_change(20)
        market['vol_lb_std'] = market['pct_change'].rolling(20).std()
        market['turnover_lb_mean'] = market['turnover_rate'].rolling(20).mean()
        market['pe_rank_120d'] = market['pe'].rolling(120).apply(lambda values: pd.Series(values).rank(pct=True).iloc[-1], raw=False)
        anchor = market.iloc[-1]
        values = {field.name: getattr(panel, field.name) for field in panel._meta.fields}
        values.update(anchor.to_dict())
        values['vol'] = values.pop('volume', None)
        values['report_type_code'] = {'FY': 0.0, 'H1': 1.0, 'Q1': 2.0, 'Q3': 3.0}[panel.report_type]
        values['ann_date_lag_days'] = (
            pd.Timestamp(anchor['trade_date']) - pd.Timestamp(panel.ann_date)
        ).days if panel.ann_date else None
        for column in ('industry_code', 'pe_ind_rank', 'pb_ind_rank', 'ps_ind_rank', 'ret_5d_ind_rank', 'ret_lb_ind_rank', 'turnover_rate_ind_rank'):
            values[column] = None
        frame = pd.DataFrame([{column: values.get(column) for column in feature_columns}], columns=feature_columns)
        frame = frame.replace([np.inf, -np.inf], np.nan).apply(pd.to_numeric, errors='coerce')
        missing = [column for column in feature_columns if pd.isna(frame[column].iloc[0])]
        stats = self._stats(panel.report_type)
        for column in feature_columns:
            frame[column] = frame[column].fillna(stats.get(column))
        unresolved = [column for column in feature_columns if pd.isna(frame[column].iloc[0])]
        return frame, anchor['trade_date'], missing, unresolved

    def _load_bundle(self, report_type: str, path: Path) -> dict[str, Any]:
        if report_type not in self._bundles:
            self._bundles[report_type] = joblib.load(path)
        return self._bundles[report_type]

    def _stats(self, report_type: str) -> dict[str, float | None]:
        if report_type not in self._impute_stats:
            artifact = self.registry.load_production(report_type)
            path = artifact.model_path.parent / 'impute_stats.json'
            payload = json.loads(path.read_text(encoding='utf-8'))
            self._impute_stats[report_type] = payload.get('global_median') or {}
        return self._impute_stats[report_type]

    def _load_config(self) -> dict[str, Any]:
        if self._config is None:
            path = Path(settings.PREDICTIVE_VALUATION_CONFIG)
            if not path.is_absolute():
                path = Path(settings.BASE_DIR) / path
            payload = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
            self._config = payload if isinstance(payload, dict) else {}
        return self._config

    def _score(self, probability: float, earnings_growth: float | None) -> float:
        cfg = self._load_config().get('valuation_mapping', {}) or {}
        lower = float(cfg.get('earnings_growth_min', -0.3))
        upper = float(cfg.get('earnings_growth_max', 0.3))
        if upper <= lower:
            upper = lower + 1e-6
        if earnings_growth is None or pd.isna(earnings_growth):
            normalized = 0.5
        else:
            normalized = (max(lower, min(upper, float(earnings_growth))) - lower) / (upper - lower)
        probability_weight = float(cfg.get('weight_prob', 0.7))
        earnings_weight = float(cfg.get('weight_earnings', 0.3))
        total = probability_weight + earnings_weight
        if total <= 0:
            probability_weight, earnings_weight, total = 0.7, 0.3, 1.0
        return round(100.0 * (probability_weight * probability + earnings_weight * normalized) / total, 4)

    @staticmethod
    def _risk_level(score: float) -> str:
        return 'LOW' if score >= 65 else ('MEDIUM' if score >= 50 else 'HIGH')

    def _quality_risk_guard(self, panel, feature_row: pd.DataFrame, base_score: float, base_risk_level: str) -> dict[str, Any]:
        cfg = (self._load_config().get('valuation_mapping', {}) or {}).get('quality_risk_guard', {}) or {}
        result = {'applied': False, 'score': round(float(base_score), 4), 'risk_level': base_risk_level, 'penalty_total': 0.0, 'risk_upgrade_total': 0, 'reasons': []}
        if not bool(cfg.get('enabled', False)):
            return result

        thresholds = cfg.get('thresholds') or {}
        rules = cfg.get('rules') or {}
        revenue = self._panel_number(panel, 'revenue')
        netprofit = self._panel_number(panel, 'n_income_attr_p') or self._panel_number(panel, 'n_income')
        ocf_to_or = self._panel_number(panel, 'ocf_to_or')
        operating_cashflow = self._panel_number(panel, 'n_cashflow_act')
        receivables = self._panel_number(panel, 'accounts_receiv')
        inventories = self._panel_number(panel, 'inventories')
        reasons: list[dict[str, Any]] = []

        def hit(rule_name: str, metric_value: float | None, threshold: float | None = None) -> None:
            rule = rules.get(rule_name) or {}
            reasons.append({
                'rule': rule_name,
                'metric_value': metric_value,
                'threshold': threshold,
                'score_penalty': max(0.0, float(rule.get('score_penalty', 0.0))),
                'risk_upgrade': max(0, int(rule.get('risk_upgrade', 0))),
            })

        min_ocf_to_or = float(thresholds.get('min_ocf_to_or', 0.0))
        if ocf_to_or is not None and ocf_to_or < min_ocf_to_or:
            hit('ocf_to_or_low', ocf_to_or, min_ocf_to_or)
        min_profit = float(thresholds.get('min_positive_profit', 0.0))
        max_cashflow = float(thresholds.get('max_negative_operating_cashflow', 0.0))
        if netprofit is not None and netprofit > min_profit and operating_cashflow is not None and operating_cashflow <= max_cashflow:
            hit('profit_cashflow_mismatch', operating_cashflow, max_cashflow)
        min_revenue = float(cfg.get('min_revenue_base', 1_000_000.0))
        if revenue is not None and revenue >= min_revenue:
            receivables_ratio = None if receivables is None else receivables / revenue
            inventories_ratio = None if inventories is None else inventories / revenue
            max_receivables = float(thresholds.get('max_receiv_to_revenue', 0.45))
            max_inventories = float(thresholds.get('max_inventory_to_revenue', 0.60))
            if receivables_ratio is not None and receivables_ratio > max_receivables:
                hit('receivables_ratio_high', receivables_ratio, max_receivables)
            if inventories_ratio is not None and inventories_ratio > max_inventories:
                hit('inventory_ratio_high', inventories_ratio, max_inventories)

        penalty = min(max(0.0, float(cfg.get('max_score_penalty', 30.0))), sum(item['score_penalty'] for item in reasons))
        upgrades = min(max(0, int(cfg.get('max_risk_upgrade', 2))), sum(item['risk_upgrade'] for item in reasons))
        risk_code = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}.get(base_risk_level, 1)
        risk_level = {0: 'LOW', 1: 'MEDIUM', 2: 'HIGH'}[min(2, risk_code + upgrades)]
        result.update({
            'applied': bool(reasons),
            'score': round(max(0.0, base_score - penalty), 4),
            'risk_level': risk_level,
            'penalty_total': round(penalty, 4),
            'risk_upgrade_total': upgrades,
            'reasons': reasons,
        })
        return result

    def _target_mapping(self, *, panel, feature_row: pd.DataFrame, missing_features: list[str], score: float, probability: float, earnings_growth: float, risk_level: str, asof_date: date) -> dict[str, Any]:
        cfg = self._load_config().get('valuation_mapping', {}) or {}
        regime_cfg = cfg.get('market_regime') or {}
        market_regime = 'BALANCE'
        regime_trace: dict[str, Any] = {'source': 'fallback', 'degraded': True}
        if bool(regime_cfg.get('enabled', True)):
            try:
                regime = get_market_regime(asof_date=asof_date, benchmark_ts_code=regime_cfg.get('benchmark_ts_code', '000001.SH'))
                market_regime = str(regime.regime or 'BALANCE').upper()
                regime_trace = {'source': regime.source, 'status': regime.status, 'source_trade_date': str(regime.source_trade_date) if regime.source_trade_date else None, 'degraded': regime.status != 'VALID'}
            except Exception as exc:
                regime_trace['reason'] = f'{type(exc).__name__}: {exc}'
        else:
            regime_trace = {'source': 'disabled', 'status': 'DISABLED', 'degraded': True}
        profiles = regime_cfg.get('profiles') or {}
        profile = profiles.get(market_regime.lower()) or profiles.get(market_regime) or {}
        max_abs_return = max(0.0, float(cfg.get('quant_target_max_abs_return', 0.30))) * float(profile.get('return_scale', 1.0))

        tail = cfg.get('bull_tail') or {}
        tail_applied = False
        tail_reason = 'disabled'
        if bool(tail.get('enabled', False)):
            checks = {
                'regime': market_regime in {str(value).upper() for value in tail.get('allowed_regimes', ['BULL', 'BALANCE'])},
                'score': score >= float(tail.get('min_score', 95.0)),
                'probability': probability >= float(tail.get('min_prob', 0.90)),
                'earnings_growth': earnings_growth >= float(tail.get('min_earnings_growth', 0.80)),
                'risk': risk_level in {str(value).upper() for value in tail.get('max_risk_levels', ['LOW', 'MEDIUM'])},
            }
            tail_applied = all(checks.values())
            tail_reason = 'high_confidence_growth' if tail_applied else ','.join(key for key, value in checks.items() if not value)
            if tail_applied:
                max_abs_return = max(max_abs_return, float(tail.get('max_abs_return', max_abs_return)))

        probability_return = ((probability - 0.5) * 2.0) * float(cfg.get('quant_target_prob_coef', 0.10))
        earnings_clip = max(1e-9, float(cfg.get('quant_target_earnings_clip', 0.40)))
        earnings_return = (max(-earnings_clip, min(earnings_clip, earnings_growth)) / earnings_clip) * float(cfg.get('quant_target_earnings_coef', 0.10))
        industry_rank = self._number(feature_row, 'pe_ind_rank') if 'pe_ind_rank' not in missing_features else None
        industry_degraded = industry_rank is None
        industry_rank = 0.5 if industry_rank is None else max(0.0, min(1.0, industry_rank))
        industry_return = ((0.5 - industry_rank) * 2.0) * float(cfg.get('quant_target_industry_coef', 0.05))
        risk_scales = dict(cfg.get('quant_target_risk_scales') or {'LOW': 1.15, 'MEDIUM': 1.05, 'HIGH': 0.90})
        risk_scales.update(profile.get('risk_scales') or {})
        risk_scale = float(risk_scales.get(risk_level, 1.0))
        base_return = ((score - 50.0) / 50.0) * max_abs_return
        implied_return = max(-max_abs_return, min(max_abs_return, (base_return + probability_return + earnings_return + industry_return) * risk_scale))
        volatility = max(0.0, min(0.25, self._number(feature_row, 'vol_lb_std') or 0.0))
        band = float(cfg.get('quant_target_base_band', 0.04)) * float(profile.get('band_scale', 1.0)) + volatility * float(cfg.get('quant_target_volatility_mult', 1.50)) + {'LOW': 0.0, 'MEDIUM': 0.015, 'HIGH': 0.03}.get(risk_level, 0.015)
        band = max(0.02, min(max_abs_return * 0.80 if max_abs_return else 0.02, band))
        raw_low = max(-max_abs_return, min(max_abs_return, implied_return - band))
        raw_high = max(-max_abs_return, min(max_abs_return, implied_return + band))
        market_adjustment = self._market_overall_adjustment(asof_date, cfg.get('market_overall_adjustment') or {})
        multiplier = float(market_adjustment.get('multiplier', 1.0))
        adjusted = tuple(max(-max_abs_return, min(max_abs_return, (1.0 + value) * multiplier - 1.0)) for value in (implied_return, raw_low, raw_high))
        trace = {
            'rules_version': str(cfg.get('rules_version', 'v1')),
            'market_regime': market_regime,
            'market_regime_profile': profile,
            'regime_trace': regime_trace,
            'industry_rank': industry_rank,
            'industry_rank_degraded': industry_degraded,
            'volatility': volatility,
            'risk_scale': risk_scale,
            'bull_tail_applied': tail_applied,
            'bull_tail_reason': tail_reason,
            'max_abs_return': max_abs_return,
            'components': {'base_return': base_return, 'probability_return': probability_return, 'earnings_return': earnings_return, 'industry_return': industry_return},
            'market_overall_adjustment': market_adjustment,
        }
        return {
            'target_return_pct': 100.0 * adjusted[0],
            'target_return_low_pct': 100.0 * adjusted[1],
            'target_return_high_pct': 100.0 * adjusted[2],
            'target_return_pct_raw': 100.0 * implied_return,
            'target_return_low_pct_raw': 100.0 * raw_low,
            'target_return_high_pct_raw': 100.0 * raw_high,
            'trace': trace,
        }

    def _market_overall_adjustment(self, asof_date: date, cfg: dict[str, Any]) -> dict[str, Any]:
        if not bool(cfg.get('enabled', False)):
            return {'enabled': False, 'state': 'neutral', 'multiplier': 1.0, 'degraded': False}
        index_weights = cfg.get('index_weights') or {}
        metric_weights = cfg.get('metric_weights') or {'pe_ttm': 0.45, 'pb': 0.40, 'turnover_rate_f': 0.15}
        lookback = asof_date - timedelta(days=365 * int(cfg.get('lookback_years', 5)))
        scores: list[tuple[float, float]] = []
        for code, index_weight in index_weights.items():
            security = Security.objects.filter(ts_code=str(code).upper()).first()
            if security is None:
                continue
            rows = list(StockDailyFundamentalHistory.objects.filter(security=security, trade_date__gte=lookback, trade_date__lte=asof_date).values('trade_date', *metric_weights.keys()).order_by('trade_date'))
            if not rows:
                continue
            metric_score = 0.0
            metric_total = 0.0
            for metric, weight in metric_weights.items():
                values = [float(row[metric]) for row in rows if row.get(metric) is not None and float(row[metric]) >= 0]
                if not values:
                    continue
                metric_score += (sum(value <= values[-1] for value in values) / len(values)) * float(weight)
                metric_total += float(weight)
            if metric_total > 0:
                scores.append((metric_score / metric_total, float(index_weight)))
        if not scores:
            return {'enabled': True, 'state': 'neutral', 'multiplier': float(cfg.get('multiplier_neutral', 1.0)), 'degraded': True, 'reason': 'index_valuation_data_unavailable'}
        percentile = sum(score * weight for score, weight in scores) / sum(weight for _, weight in scores)
        state = 'overvalued' if percentile >= float(cfg.get('overvalued_threshold', 0.8)) else ('undervalued' if percentile <= float(cfg.get('undervalued_threshold', 0.2)) else 'neutral')
        return {'enabled': True, 'state': state, 'percentile': round(percentile, 6), 'multiplier': float(cfg.get(f'multiplier_{state}', 1.0)), 'degraded': False}

    @staticmethod
    def _panel_number(panel, field: str) -> float | None:
        value = getattr(panel, field, None)
        try:
            return None if value is None else float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _target_values(close: float | None, market_cap: float | None, center_pct: float, low_pct: float, high_pct: float) -> dict[str, float | None]:
        def values(base: float | None, scale: float) -> float | None:
            return None if base is None or base <= 0 else round(base * (1.0 + scale / 100.0), 6)

        return {
            'target_price': values(close, center_pct),
            'target_price_low': values(close, low_pct),
            'target_price_high': values(close, high_pct),
            'target_market_cap': values(market_cap, center_pct),
            'target_market_cap_low': values(market_cap, low_pct),
            'target_market_cap_high': values(market_cap, high_pct),
        }

    @staticmethod
    def _number(frame: pd.DataFrame, column: str) -> float | None:
        value = frame[column].iloc[0] if column in frame else None
        return None if value is None or pd.isna(value) else float(value)

    def _action(self, score: float) -> str:
        cfg = self._load_config().get('valuation_mapping', {}) or {}
        bands = cfg.get('score_bands') or [
            {'min': 70, 'stance': 'STRONG_BUY'},
            {'min': 60, 'stance': 'BUY'},
            {'min': 45, 'stance': 'HOLD'},
            {'min': 30, 'stance': 'REDUCE'},
            {'min': 0, 'stance': 'SELL'},
        ]
        selected = sorted(bands, key=lambda item: float(item.get('min', 0)), reverse=True)[-1]
        for band in sorted(bands, key=lambda item: float(item.get('min', 0)), reverse=True):
            if float(score) >= float(band.get('min', 0)):
                selected = band
                break
        return {
            'STRONG_BUY': 'BUY',
            'BUY': 'BUY',
            'HOLD': 'HOLD',
            'REDUCE': 'SELL_PART',
            'SELL': 'SELL',
        }.get(str(selected.get('stance') or 'HOLD').upper(), 'HOLD')