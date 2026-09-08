from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from market_data.models import MarketBarDailyHistory, StockDailyFundamentalHistory
from predictive_valuation.models import (
    PredictiveFinancialFeaturePanel,
    PredictiveValuationCurrent,
    PredictiveValuationSnapshot,
)
from predictive_valuation.services.artifact_registry import PredictiveArtifactRegistry


class PredictiveInferenceService:
    """Run a report-type-specific bundle against persisted feature and market records."""

    def __init__(self, registry: PredictiveArtifactRegistry | None = None):
        self.registry = registry or PredictiveArtifactRegistry()
        self._bundles: dict[str, dict[str, Any]] = {}
        self._impute_stats: dict[str, dict[str, float | None]] = {}

    def predict_panel(self, panel: PredictiveFinancialFeaturePanel, horizon: str = '1M', trigger_type: str = 'MANUAL') -> PredictiveValuationSnapshot:
        artifact = self.registry.load_production(panel.report_type)
        bundle = self._load_bundle(artifact.report_type, artifact.model_path)
        feature_row, market_date, missing_features, unresolved_features = self._feature_row(panel, bundle['feature_cols'])
        probability = float(bundle['classifier'].predict_proba(feature_row)[0][1])
        earnings_growth = float(bundle['regressor'].predict(feature_row)[0])
        score = self._score(probability, earnings_growth)
        risk_level = 'LOW' if score >= 65 else ('MEDIUM' if score >= 50 else 'HIGH')
        target_return_pct, target_low_pct, target_high_pct = self._target_range(
            score=score,
            probability=probability,
            earnings_growth=earnings_growth,
            risk_level=risk_level,
            volatility=self._number(feature_row, 'vol_lb_std') or 0.0,
        )
        close = self._number(feature_row, 'close')
        market_cap = self._number(feature_row, 'total_mv')
        defaults = {
            'artifact_hash': artifact.artifact_hash,
            'source_market_date': market_date,
            'financial_end_date': panel.end_date,
            'financial_ann_date': panel.ann_date,
            'financial_source_as_of_date': panel.source_as_of_date,
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
            'explain': {
                'imputed_features': missing_features,
                'unresolved_features': unresolved_features,
                'pred_earnings_growth': earnings_growth,
            },
            'raw_result': {'model_file': artifact.model_path.name, 'report_type': artifact.report_type},
        }
        snapshot, _ = PredictiveValuationSnapshot.objects.update_or_create(
            security=panel.security,
            asof_date=panel.source_as_of_date,
            financial_report_type=panel.report_type,
            horizon=horizon,
            model_version=artifact.model_version,
            feature_contract_version='1',
            defaults=defaults,
        )
        current = PredictiveValuationCurrent.objects.filter(
            security=panel.security, horizon=horizon, model_version=artifact.model_version
        ).first()
        if current is None or snapshot.asof_date >= current.asof_date:
            PredictiveValuationCurrent.objects.update_or_create(
                security=panel.security,
                horizon=horizon,
                model_version=artifact.model_version,
                defaults={
                    'snapshot': snapshot, 'asof_date': snapshot.asof_date, 'signal_score': snapshot.signal_score,
                    'target_return_pct': snapshot.target_return_pct, 'target_price': snapshot.target_price,
                    'risk_level': snapshot.risk_level,
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

    @staticmethod
    def _score(probability: float, earnings_growth: float) -> float:
        earnings_normalized = max(0.0, min(1.0, (max(-0.3, min(0.3, earnings_growth)) + 0.3) / 0.6))
        return 100.0 * (0.7 * probability + 0.3 * earnings_normalized)

    @staticmethod
    def _target_range(score: float, probability: float, earnings_growth: float, risk_level: str, volatility: float) -> tuple[float, float, float]:
        risk_scale = {'LOW': 1.15, 'MEDIUM': 1.05, 'HIGH': 0.90}[risk_level]
        target = (((score - 50) / 50) * 0.30 + ((probability - 0.5) * 2) * 0.10 + (max(-0.4, min(0.4, earnings_growth)) / 0.4) * 0.10) * risk_scale
        target = max(-0.30, min(0.30, target))
        band = max(0.02, min(0.24, 0.04 + max(0.0, min(0.25, volatility)) * 1.5 + {'LOW': 0, 'MEDIUM': .015, 'HIGH': .03}[risk_level]))
        return target * 100, max(-0.30, target - band) * 100, min(0.30, target + band) * 100

    @staticmethod
    def _number(frame: pd.DataFrame, column: str) -> float | None:
        value = frame[column].iloc[0] if column in frame else None
        return None if value is None or pd.isna(value) else float(value)