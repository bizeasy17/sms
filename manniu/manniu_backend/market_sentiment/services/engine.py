from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median, pstdev

from django.db import transaction
from django.utils import timezone

from market_data.models import (
    IngestionRun,
    IngestionWatermark,
    MarketBarDailyHistory,
    Security,
    StockDailyFundamentalHistory,
)
from market_sentiment.models import (
    MarketSentimentFactor,
    MarketSentimentSnapshot,
    StockSentimentFactor,
    StockSentimentSnapshot,
)


ENGINE_VERSION = 'sentiment_v1'
MARKET_SCOPE = ('CN', 'MARKET', 'ALL_A')


@dataclass
class StockDayFactors:
    security: Security
    trade_date: date
    momentum: float | None
    activity: float | None
    fear: float | None
    valid_history: int
    coverage: float
    industry_key: str


def _zscore(value, previous):
    if value is None or len(previous) < 2:
        return None
    deviation = pstdev(previous)
    if deviation == 0:
        return 0.0
    return max(-3.0, min(3.0, (value - sum(previous) / len(previous)) / deviation))


def _safe_float(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _median_or_none(values):
    valid = [value for value in values if value is not None and math.isfinite(value)]
    return median(valid) if valid else None


def _percentile(values, value):
    valid = sorted(item for item in values if item is not None and math.isfinite(item))
    if not valid or value is None:
        return None
    return 100.0 * sum(item <= value for item in valid) / len(valid)


class SentimentEngine:
    def __init__(self, engine_version=ENGINE_VERSION):
        self.engine_version = engine_version

    def validate_watermarks(self, trade_date):
        required = ('stock-bars', 'stock-fundamentals')
        missing = []
        for dataset in required:
            watermark = IngestionWatermark.objects.filter(
                dataset=dataset, scope_key='ALL', frequency='D', status=IngestionRun.Status.SUCCEEDED,
                last_complete_source_date__gte=trade_date,
            ).first()
            if watermark is None:
                missing.append(dataset)
        if missing:
            raise ValueError(f'market_data watermarks are not complete: {", ".join(missing)}')

    def _stock_universe(self, ts_codes=None):
        queryset = Security.objects.filter(asset_type=Security.AssetType.STOCK, list_status__in=['L', ''])
        if ts_codes:
            queryset = queryset.filter(ts_code__in=ts_codes)
        return queryset.select_related('industry')

    def _build_stock_factors(self, security, trade_date):
        bars = list(MarketBarDailyHistory.objects.filter(
            security=security, trade_date__lte=trade_date, close__gt=0, pre_close__gt=0,
        ).order_by('-trade_date')[:253])
        bars.reverse()
        if len(bars) < 20:
            return StockDayFactors(security, trade_date, None, None, None, len(bars), 0.0, self._industry_key(security))
        fundamentals = {
            row.trade_date: row for row in StockDailyFundamentalHistory.objects.filter(
                security=security, trade_date=trade_date,
            )
        }
        closes = [_safe_float(row.close) for row in bars]
        returns = [None] + [closes[index] / closes[index - 1] - 1.0 for index in range(1, len(closes))]
        volumes = [_safe_float(row.volume) for row in bars]
        amounts = [_safe_float(row.amount) for row in bars]
        turnovers = []
        volume_ratios = []
        for row in bars:
            fundamental = fundamentals.get(row.trade_date)
            turnovers.append(_safe_float(getattr(fundamental, 'turnover_rate_f', None) or getattr(fundamental, 'turnover_rate', None)))
            volume_ratios.append(_safe_float(getattr(fundamental, 'volume_ratio', None)))
        current = len(bars) - 1
        def previous(series):
            return [value for value in series[max(0, current - 20):current] if value is not None]
        r1 = returns[current]
        r5 = closes[current] / closes[current - 5] - 1.0 if current >= 5 else None
        r20 = closes[current] / closes[current - 20] - 1.0 if current >= 20 else None
        streak = sum(1 for value in reversed(returns[: current + 1]) if value is not None and value > 0)
        amplitude = (_safe_float(bars[current].high) - _safe_float(bars[current].low)) / closes[current - 1] if closes[current - 1] else None
        lower_shadow = None
        high_low = _safe_float(bars[current].high) - _safe_float(bars[current].low)
        if high_low and high_low > 0:
            lower_shadow = (min(_safe_float(bars[current].open), closes[current]) - _safe_float(bars[current].low)) / high_low
        volatility = pstdev([value for value in returns[max(0, current - 10):current] if value is not None]) if current >= 11 else None
        down_volume = _safe_float(bars[current].volume) if r1 is not None and r1 < 0 else 0.0
        down_return = r1 if r1 is not None and r1 < 0 else 0.0
        momentum_values = [_zscore(r1, previous(returns)), _zscore(r5, previous(returns)), _zscore(r20, previous(returns)), _zscore(float(streak), previous([float(sum(1 for item in returns[:i + 1] if item and item > 0)) for i in range(len(returns))]))]
        activity_values = [_zscore(volumes[current], previous(volumes)), _zscore(amounts[current], previous(amounts)), _zscore(turnovers[current], previous(turnovers)), _zscore(volume_ratios[current], previous(volume_ratios))]
        fear_values = [_zscore(volatility, previous([pstdev([v for v in returns[max(0, i - 10):i] if v is not None]) if i >= 11 else None for i in range(len(returns))])), _zscore(amplitude, previous([None if i == 0 or closes[i - 1] == 0 else (_safe_float(bars[i].high) - _safe_float(bars[i].low)) / closes[i - 1] for i in range(len(bars))])), _zscore(lower_shadow, previous([])), _zscore(down_volume, previous(volumes)), _zscore(down_return, previous(returns))]
        momentum = _weighted_mean(momentum_values, [0.40, 0.30, 0.20, 0.10])
        activity = _weighted_mean(activity_values, [0.25, 0.20, 0.40, 0.15])
        fear = _weighted_mean(fear_values, [0.30, 0.25, 0.15, 0.20, 0.10])
        available = sum(value is not None for value in momentum_values + activity_values + fear_values)
        coverage = available / float(len(momentum_values) + len(activity_values) + len(fear_values))
        return StockDayFactors(security, trade_date, momentum, activity, fear, len(bars), coverage, self._industry_key(security))

    @staticmethod
    def _industry_key(security):
        return str(security.industry_id or '')

    def calculate_market(self, trade_date, ts_codes=None, require_watermark=True):
        if require_watermark:
            self.validate_watermarks(trade_date)
        factors = [self._build_stock_factors(security, trade_date) for security in self._stock_universe(ts_codes)]
        valid = [item for item in factors if item.momentum is not None and item.activity is not None and item.fear is not None]
        momentum = _median_or_none([item.momentum for item in valid])
        activity = _median_or_none([item.activity for item in valid])
        fear = _median_or_none([item.fear for item in valid])
        raw_score = 0.35 * momentum + 0.35 * activity - 0.30 * fear if None not in (momentum, activity, fear) else None
        history = list(MarketSentimentSnapshot.objects.filter(
            market='CN', scope_type='MARKET', scope_code='ALL_A', engine_version=self.engine_version,
            trade_date__lt=trade_date, raw_score__isnull=False,
        ).order_by('-trade_date').values_list('raw_score', flat=True)[:252])
        standardized = _standardize(raw_score, history)
        score = _sigmoid_score(standardized) if standardized is not None and len(history) >= 252 else None
        status = 'VALID' if score is not None else 'WARMING_UP'
        return {'market': 'CN', 'scope_type': 'MARKET', 'scope_code': 'ALL_A', 'trade_date': trade_date, 'source_trade_date': trade_date, 'score': score, 'level': _level(score), 'status': status, 'raw_score': raw_score, 'standardized_score': standardized, 'momentum': momentum, 'activity': activity, 'fear': fear, 'universe_count': len(factors), 'valid_count': len(valid), 'coverage': len(valid) / float(len(factors)) if factors else 0.0, 'metadata': {'engine_version': self.engine_version, 'factor_count': len(valid)}}

    def calculate_stocks(self, trade_date, ts_codes=None, require_watermark=True):
        if require_watermark:
            self.validate_watermarks(trade_date)
        factors = [self._build_stock_factors(security, trade_date) for security in self._stock_universe(ts_codes)]
        valid = [item for item in factors if item.momentum is not None and item.activity is not None and item.fear is not None and item.valid_history >= 20]
        result = []
        for item in factors:
            if item.valid_history < 20 or item.momentum is None or item.activity is None or item.fear is None:
                result.append(self._stock_payload(item, None, 'INSUFFICIENT_DATA', 'ALL_A', 0))
                continue
            peers, peer_type = self._peers(item, valid)
            score = 0.35 * (_percentile([peer.momentum for peer in peers], item.momentum) or 0.0) + 0.35 * (_percentile([peer.activity for peer in peers], item.activity) or 0.0) + 0.30 * (100.0 - (_percentile([peer.fear for peer in peers], item.fear) or 0.0))
            result.append(self._stock_payload(item, score, 'VALID', peer_type, len(peers)))
        return result

    @staticmethod
    def _peers(item, factors):
        industry = [peer for peer in factors if peer.industry_key and peer.industry_key == item.industry_key]
        if len(industry) >= 10:
            return industry, 'industry'
        if len(factors) >= 500:
            return factors, 'ALL_A'
        return factors, 'ALL_ELIGIBLE'

    def _stock_payload(self, item, score, status, peer_type, peer_count):
        return {'security': item.security, 'trade_date': item.trade_date, 'source_trade_date': item.trade_date, 'score': score, 'level': _level(score), 'status': status, 'raw_score': score, 'standardized_score': score, 'momentum': item.momentum, 'activity': item.activity, 'fear': item.fear, 'universe_count': 0, 'valid_count': 1 if status == 'VALID' else 0, 'coverage': item.coverage, 'peer_type': peer_type, 'peer_code': item.industry_key if peer_type == 'industry' else '', 'peer_name': '', 'peer_count': peer_count, 'normalization_mode': 'same_day_peer_percentile', 'metadata': {'valid_history': item.valid_history, 'engine_version': self.engine_version}}

    @transaction.atomic
    def persist(self, market_payload, stock_payloads):
        market_snapshot, _ = MarketSentimentSnapshot.objects.update_or_create(
            market='CN', scope_type='MARKET', scope_code='ALL_A', trade_date=market_payload['trade_date'], engine_version=self.engine_version,
            defaults={key: value for key, value in market_payload.items() if key not in {'market', 'scope_type', 'scope_code', 'trade_date'}},
        )
        for code, payload in market_payload.get('factor_details', {}).items():
            MarketSentimentFactor.objects.update_or_create(snapshot=market_snapshot, factor_code=code, defaults=payload)
        snapshots = []
        for payload in stock_payloads:
            security = payload.pop('security')
            snapshot, _ = StockSentimentSnapshot.objects.update_or_create(
                security=security, trade_date=payload['trade_date'], engine_version=self.engine_version,
                defaults=payload,
            )
            snapshots.append(snapshot)
        return market_snapshot, snapshots


def _weighted_mean(values, weights):
    available = [(value, weight) for value, weight in zip(values, weights) if value is not None]
    if not available or sum(weight for _, weight in available) < 0.70 * sum(weights):
        return None
    total = sum(weight for _, weight in available)
    return sum(value * weight for value, weight in available) / total


def _standardize(value, history):
    if value is None or len(history) < 2:
        return None
    mean = sum(float(item) for item in history) / len(history)
    deviation = pstdev(float(item) for item in history)
    return max(-3.0, min(3.0, (value - mean) / deviation)) if deviation else 0.0


def _sigmoid_score(value):
    return 100.0 / (1.0 + math.exp(-value))


def _level(score):
    if score is None:
        return ''
    if score >= 66:
        return 'HIGH'
    if score >= 33:
        return 'MEDIUM'
    return 'LOW'