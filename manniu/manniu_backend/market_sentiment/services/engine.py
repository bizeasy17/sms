from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median, pstdev, stdev

from django.db import transaction
from django.db.models import F, Window
from django.db.models.functions import RowNumber
from django.utils import timezone

from market_data.models import (
    IngestionRun,
    IngestionWatermark,
    MarketBarDailyHistory,
    Security,
    SWIndustryMappingVersion,
    StockDailyFundamentalHistory,
)
from market_sentiment.models import (
    MarketSentimentFactor,
    MarketSentimentSnapshot,
    StockSentimentFactor,
    StockSentimentSnapshot,
)


ENGINE_VERSION = 'sentiment_v1'
STOCK_ENGINE_VERSION = 'stock_daily_v2_20260830'
SCORE_WINDOW = 252
Z_WINDOW = 20
MIN_STOCK_HISTORY = 20
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


def _rolling_zscores(values, window=20):
    count_prefix = [0]
    sum_prefix = [0.0]
    square_prefix = [0.0]
    for value in values:
        valid = value is not None and math.isfinite(value)
        count_prefix.append(count_prefix[-1] + int(valid))
        sum_prefix.append(sum_prefix[-1] + (value if valid else 0.0))
        square_prefix.append(square_prefix[-1] + (value * value if valid else 0.0))

    result = []
    for index, value in enumerate(values):
        if value is None or not math.isfinite(value):
            result.append(None)
            continue
        start = max(0, index - window)
        count = count_prefix[index] - count_prefix[start]
        if count < 2:
            result.append(None)
            continue
        total = sum_prefix[index] - sum_prefix[start]
        total_square = square_prefix[index] - square_prefix[start]
        mean = total / count
        deviation = math.sqrt(max(0.0, total_square / count - mean * mean))
        result.append(0.0 if deviation == 0 else max(-3.0, min(3.0, (value - mean) / deviation)))
    return result


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


def _smart_zscore(value, history, window=Z_WINDOW):
    history = history[-window:]
    if value is None or len(history) < window:
        return None
    deviation = stdev(history)
    if deviation == 0:
        return None
    return max(-3.0, min(3.0, (value - sum(history) / len(history)) / deviation))


def _smart_percentile_rank(value, values):
    if value is None or not values:
        return None
    below = sum(candidate < value for candidate in values)
    equal = sum(candidate == value for candidate in values)
    return 100.0 * (below + equal / 2.0) / len(values)


def _stock_dimension_samples(rows):
    returns = []
    returns_5 = []
    returns_20 = []
    volumes = []
    amounts = []
    turnovers = []
    volume_ratios = []
    amplitudes = []
    lower_shadows = []
    volatilities = []
    down_returns = []
    streaks = []
    streak_up = 0
    samples = []

    for index, row in enumerate(rows):
        close = _safe_float(row.get('close'))
        pre_close = _safe_float(row.get('pre_close'))
        open_price = _safe_float(row.get('open'))
        high = _safe_float(row.get('high'))
        low = _safe_float(row.get('low'))
        volume = _safe_float(row.get('volume'))
        amount = _safe_float(row.get('amount'))
        turnover_f = _safe_float(row.get('turnover_rate_f'))
        turnover = turnover_f if turnover_f is not None else _safe_float(row.get('turnover_rate'))
        volume_ratio = _safe_float(row.get('volume_ratio'))

        return_1 = close / pre_close - 1 if close is not None and pre_close and pre_close > 0 else None
        streak_up = streak_up + 1 if return_1 is not None and return_1 > 0 else 0
        previous_close_5 = _safe_float(rows[index - 5].get('close')) if index >= 5 else None
        previous_close_20 = _safe_float(rows[index - 20].get('close')) if index >= 20 else None
        return_5 = close / previous_close_5 - 1 if close and previous_close_5 else None
        return_20 = close / previous_close_20 - 1 if close and previous_close_20 else None
        amplitude = (high - low) / pre_close if high is not None and low is not None and pre_close and pre_close > 0 else None
        lower_shadow = (
            (min(open_price, close) - low) / (high - low)
            if None not in (open_price, close, high, low) and high > low else None
        )
        volatility = stdev(returns[-10:]) if len(returns) >= 10 else None

        return_1_z = _smart_zscore(return_1, returns)
        return_5_z = _smart_zscore(return_5, returns_5)
        return_20_z = _smart_zscore(return_20, returns_20)
        streak_z = _smart_zscore(streak_up, streaks)
        volume_z = _smart_zscore(volume, volumes)
        amount_z = _smart_zscore(amount, amounts)
        turnover_z = _smart_zscore(turnover, turnovers)
        volume_ratio_z = _smart_zscore(volume_ratio, volume_ratios)
        volatility_z = _smart_zscore(volatility, volatilities)
        amplitude_z = _smart_zscore(amplitude, amplitudes)
        lower_shadow_z = _smart_zscore(lower_shadow, lower_shadows)
        down_volume_z = _smart_zscore(volume, volumes) if return_1 is not None and return_1 < 0 else None
        down_return = max(-return_1, 0) if return_1 is not None else None
        down_return_z = _smart_zscore(down_return, down_returns)

        momentum = _weighted_mean(
            [return_1_z, return_5_z, return_20_z, streak_z],
            [0.40, 0.30, 0.20, 0.10],
        )
        activity = _weighted_mean(
            [volume_z, amount_z, turnover_z, volume_ratio_z],
            [0.25, 0.20, 0.40, 0.15],
        )
        fear = _weighted_mean(
            [volatility_z, amplitude_z, lower_shadow_z, down_volume_z, down_return_z],
            [0.30, 0.25, 0.15, 0.20, 0.10],
        )
        samples.append({
            'trade_date': row['trade_date'],
            'momentum': momentum,
            'activity': activity,
            'fear': fear,
            'complete': all(value is not None for value in (close, pre_close, volume, amount)),
            'turnover_source': 'turnover_rate_f' if turnover_f is not None else 'turnover_rate' if turnover is not None else None,
        })

        if return_1 is not None:
            returns.append(return_1)
            down_returns.append(max(-return_1, 0))
            streaks.append(streak_up)
        if return_5 is not None:
            returns_5.append(return_5)
        if return_20 is not None:
            returns_20.append(return_20)
        if volume is not None:
            volumes.append(volume)
        if amount is not None:
            amounts.append(amount)
        if turnover is not None:
            turnovers.append(turnover)
        if volume_ratio is not None:
            volume_ratios.append(volume_ratio)
        if amplitude is not None:
            amplitudes.append(amplitude)
        if lower_shadow is not None:
            lower_shadows.append(lower_shadow)
        if volatility is not None:
            volatilities.append(volatility)
    return samples


def _stock_level(score, status):
    if score is None:
        return 'INSUFFICIENT_DATA' if status == 'INSUFFICIENT_DATA' else 'WARMING_UP'
    if score < 30:
        return 'PANIC'
    if score < 45:
        return 'CAUTIOUS'
    if score <= 55:
        return 'NEUTRAL'
    if score < 70:
        return 'POSITIVE'
    return 'EUPHORIC'


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

    def _build_stock_factors(self, security, trade_date, bars=None, fundamental_rows=None):
        if bars is None:
            bars = list(MarketBarDailyHistory.objects.filter(
                security=security, trade_date__lte=trade_date, close__gt=0, pre_close__gt=0,
            ).order_by('-trade_date')[:253])
        else:
            bars = list(bars)
        bars.reverse()
        if len(bars) < 20:
            return StockDayFactors(security, trade_date, None, None, None, len(bars), 0.0, self._industry_key(security))
        if fundamental_rows is None:
            fundamental_dates = [row.trade_date for row in bars]
            fundamental_rows = StockDailyFundamentalHistory.objects.filter(
                security=security, trade_date__in=fundamental_dates,
            )
        fundamentals = fundamental_rows if isinstance(fundamental_rows, dict) else {
            row.trade_date: row for row in fundamental_rows
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
        window_start = max(0, current - 20)

        def previous(series):
            return [value for value in series[window_start:current] if value is not None]

        positive_counts = []
        positive_prefix = [0]
        for value in returns:
            positive_prefix.append(positive_prefix[-1] + int(value is not None and value > 0))
        for index in range(len(returns)):
            positive_counts.append(float(
                positive_prefix[index + 1] - positive_prefix[max(0, index - 252)]
            ))

        volatility_history = [
            value for value in (
                pstdev([value for value in returns[max(0, index - 10):index] if value is not None])
                if index >= 11 else None
                for index in range(window_start, current)
            )
            if value is not None
        ]
        amplitude_history = [
            value for value in (
                None if index == 0 or closes[index - 1] == 0 else (
                    _safe_float(bars[index].high) - _safe_float(bars[index].low)
                ) / closes[index - 1]
                for index in range(window_start, current)
            )
            if value is not None
        ]
        r1 = returns[current]
        r5 = closes[current] / closes[current - 5] - 1.0 if current >= 5 else None
        r20 = closes[current] / closes[current - 20] - 1.0 if current >= 20 else None
        streak = positive_counts[current]
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
        fear_values = [_zscore(volatility, volatility_history), _zscore(amplitude, amplitude_history), _zscore(lower_shadow, []), _zscore(down_volume, previous(volumes)), _zscore(down_return, previous(returns))]
        momentum = _weighted_mean(momentum_values, [0.40, 0.30, 0.20, 0.10])
        activity = _weighted_mean(activity_values, [0.25, 0.20, 0.40, 0.15])
        fear = _weighted_mean(fear_values, [0.30, 0.25, 0.15, 0.20, 0.10])
        available = sum(value is not None for value in momentum_values + activity_values + fear_values)
        coverage = available / float(len(momentum_values) + len(activity_values) + len(fear_values))
        return StockDayFactors(security, trade_date, momentum, activity, fear, len(bars), coverage, self._industry_key(security))

    @staticmethod
    def _industry_key(security):
        return str(security.industry_id or '')

    def _build_stock_factor_series(self, security, bars, fundamental_rows, target_dates=None):
        bars = list(bars)
        fundamentals = fundamental_rows if isinstance(fundamental_rows, dict) else {
            row.trade_date: row for row in fundamental_rows
        }
        if not bars:
            return []

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

        positive_counts = []
        positive_count = 0
        for value in returns:
            if value is not None and value > 0:
                positive_count += 1
            positive_counts.append(float(positive_count))

        amplitudes = [
            None if index == 0 or closes[index - 1] == 0 else (
                _safe_float(bars[index].high) - _safe_float(bars[index].low)
            ) / closes[index - 1]
            for index in range(len(bars))
        ]
        volatilities = [
            pstdev([value for value in returns[max(0, index - 10):index] if value is not None])
            if index >= 11 else None
            for index in range(len(bars))
        ]
        r5_values = [
            closes[index] / closes[index - 5] - 1.0 if index >= 5 else None
            for index in range(len(bars))
        ]
        r20_values = [
            closes[index] / closes[index - 20] - 1.0 if index >= 20 else None
            for index in range(len(bars))
        ]
        down_volumes = [
            volumes[index] if returns[index] is not None and returns[index] < 0 else 0.0
            for index in range(len(bars))
        ]
        down_returns = [
            returns[index] if returns[index] is not None and returns[index] < 0 else 0.0
            for index in range(len(bars))
        ]
        return_zscores = _rolling_zscores(returns)
        r5_zscores = _rolling_zscores(r5_values)
        r20_zscores = _rolling_zscores(r20_values)
        positive_zscores = _rolling_zscores(positive_counts)
        volume_zscores = _rolling_zscores(volumes)
        amount_zscores = _rolling_zscores(amounts)
        turnover_zscores = _rolling_zscores(turnovers)
        volume_ratio_zscores = _rolling_zscores(volume_ratios)
        volatility_zscores = _rolling_zscores(volatilities)
        amplitude_zscores = _rolling_zscores(amplitudes)
        down_volume_zscores = _rolling_zscores(down_volumes)
        down_return_zscores = _rolling_zscores(down_returns)
        target_dates = set(target_dates) if target_dates is not None else None
        factors = {}
        for current in range(len(bars)):
            valid_history = min(current + 1, 253)
            if target_dates is not None and bars[current].trade_date not in target_dates:
                continue
            if valid_history < 20:
                factors[bars[current].trade_date] = StockDayFactors(
                    security, bars[current].trade_date, None, None, None,
                    valid_history, 0.0, self._industry_key(security),
                )
                continue

            r1 = returns[current]
            high_low = _safe_float(bars[current].high) - _safe_float(bars[current].low)
            lower_shadow = None
            if high_low and high_low > 0:
                lower_shadow = (min(_safe_float(bars[current].open), closes[current]) - _safe_float(bars[current].low)) / high_low
            momentum_values = [
                return_zscores[current],
                r5_zscores[current],
                r20_zscores[current],
                positive_zscores[current],
            ]
            activity_values = [
                volume_zscores[current],
                amount_zscores[current],
                turnover_zscores[current],
                volume_ratio_zscores[current],
            ]
            fear_values = [
                volatility_zscores[current],
                amplitude_zscores[current],
                _zscore(lower_shadow, []),
                down_volume_zscores[current],
                down_return_zscores[current],
            ]
            momentum = _weighted_mean(momentum_values, [0.40, 0.30, 0.20, 0.10])
            activity = _weighted_mean(activity_values, [0.25, 0.20, 0.40, 0.15])
            fear = _weighted_mean(fear_values, [0.30, 0.25, 0.15, 0.20, 0.10])
            available = sum(value is not None for value in momentum_values + activity_values + fear_values)
            factors[bars[current].trade_date] = StockDayFactors(
                security, bars[current].trade_date, momentum, activity, fear,
                valid_history, available / float(len(momentum_values) + len(activity_values) + len(fear_values)),
                self._industry_key(security),
            )
        return factors

    def calculate_market(self, trade_date, ts_codes=None, require_watermark=True):
        if require_watermark:
            self.validate_watermarks(trade_date)
        securities = list(self._stock_universe(ts_codes))
        security_ids = [security.id for security in securities]
        history_start = trade_date - timedelta(days=500)
        bars_by_security = defaultdict(list)
        bars = MarketBarDailyHistory.objects.filter(
            security_id__in=security_ids,
            trade_date__gte=history_start,
            trade_date__lte=trade_date,
            close__gt=0,
            pre_close__gt=0,
        ).only(
            'security_id', 'trade_date', 'open', 'high', 'low', 'close',
            'pre_close', 'volume', 'amount',
        ).annotate(
            row_number=Window(
                expression=RowNumber(),
                partition_by=[F('security_id')],
                order_by=F('trade_date').desc(),
            ),
        ).filter(row_number__lte=253).order_by('security_id', '-trade_date')
        for bar in bars:
            bars_by_security[bar.security_id].append(bar)
        for security in securities:
            if len(bars_by_security[security.id]) < 253:
                bars_by_security[security.id] = list(MarketBarDailyHistory.objects.filter(
                    security=security, trade_date__lte=trade_date, close__gt=0, pre_close__gt=0,
                ).only(
                    'security_id', 'trade_date', 'open', 'high', 'low', 'close',
                    'pre_close', 'volume', 'amount',
                ).order_by('-trade_date')[:253])

        fundamental_dates = {bar.trade_date for rows in bars_by_security.values() for bar in rows}
        fundamentals_by_security = defaultdict(list)
        fundamentals = StockDailyFundamentalHistory.objects.filter(
            security_id__in=security_ids,
            trade_date__in=fundamental_dates,
        ).only('security_id', 'trade_date', 'turnover_rate', 'turnover_rate_f', 'volume_ratio')
        for fundamental in fundamentals:
            fundamentals_by_security[fundamental.security_id].append(fundamental)

        factors = [
            self._build_stock_factors(
                security,
                trade_date,
                bars=bars_by_security.get(security.id, []),
                fundamental_rows=fundamentals_by_security.get(security.id, []),
            )
            for security in securities
        ]
        return self._market_payload(trade_date, factors)

    def calculate_market_range(self, trade_dates, ts_codes=None, require_watermark=True, progress_callback=None):
        dates = sorted(set(trade_dates))
        if not dates:
            return []
        if require_watermark:
            self.validate_watermarks(dates[-1])

        securities = list(self._stock_universe(ts_codes))
        security_ids = [security.id for security in securities]
        history_start = dates[0] - timedelta(days=500)
        bars_by_security = defaultdict(list)
        bars = MarketBarDailyHistory.objects.filter(
            security_id__in=security_ids,
            trade_date__gte=history_start,
            trade_date__lte=dates[-1],
            close__gt=0,
            pre_close__gt=0,
        ).only(
            'security_id', 'trade_date', 'open', 'high', 'low', 'close',
            'pre_close', 'volume', 'amount',
        ).order_by('security_id', 'trade_date')
        for bar in bars.iterator(chunk_size=50000):
            bars_by_security[bar.security_id].append(bar)

        for security in securities:
            if len(bars_by_security[security.id]) < 253:
                bars_by_security[security.id] = list(MarketBarDailyHistory.objects.filter(
                    security=security, trade_date__lte=dates[-1], close__gt=0, pre_close__gt=0,
                ).only(
                    'security_id', 'trade_date', 'open', 'high', 'low', 'close',
                    'pre_close', 'volume', 'amount',
                ).order_by('trade_date'))

        fundamental_dates = {
            bar.trade_date for rows in bars_by_security.values() for bar in rows
        }
        fundamentals_by_security = defaultdict(dict)
        fundamentals = StockDailyFundamentalHistory.objects.filter(
            security_id__in=security_ids,
            trade_date__in=fundamental_dates,
        ).only(
            'security_id', 'trade_date', 'turnover_rate', 'turnover_rate_f', 'volume_ratio',
        )
        for fundamental in fundamentals.iterator(chunk_size=50000):
            fundamentals_by_security[fundamental.security_id][fundamental.trade_date] = fundamental

        history = list(MarketSentimentSnapshot.objects.filter(
            market='CN', scope_type='MARKET', scope_code='ALL_A',
            engine_version=self.engine_version, trade_date__lt=dates[0], raw_score__isnull=False,
        ).order_by('-trade_date').values_list('raw_score', flat=True)[:252])
        factor_series = {}
        date_series = {}
        for security in securities:
            rows = bars_by_security.get(security.id, [])
            row_dates = [row.trade_date for row in rows]
            target_dates = {
                row_dates[bisect_right(row_dates, trade_date) - 1]
                for trade_date in dates
                if bisect_right(row_dates, trade_date)
            }
            factor_series[security.id] = self._build_stock_factor_series(
                security, rows, fundamentals_by_security.get(security.id, {}), target_dates,
            )
            date_series[security.id] = row_dates
        results = []
        for trade_date in dates:
            factors = []
            for security in securities:
                row_dates = date_series[security.id]
                end = bisect_right(row_dates, trade_date)
                series = factor_series[security.id]
                if end:
                    factors.append(series[row_dates[end - 1]])
                else:
                    factors.append(StockDayFactors(
                        security, trade_date, None, None, None, 0, 0.0,
                        self._industry_key(security),
                    ))
            payload = self._market_payload(trade_date, factors, history)
            results.append(payload)
            if payload['raw_score'] is not None:
                history.insert(0, payload['raw_score'])
                del history[252:]
            if progress_callback is not None:
                progress_callback(len(results), len(dates), trade_date)
        return results

    def _market_payload(self, trade_date, factors, history=None):
        if history is None:
            history = list(MarketSentimentSnapshot.objects.filter(
                market='CN', scope_type='MARKET', scope_code='ALL_A',
                engine_version=self.engine_version, trade_date__lt=trade_date,
                raw_score__isnull=False,
            ).order_by('-trade_date').values_list('raw_score', flat=True)[:252])
        valid = [item for item in factors if item.momentum is not None and item.activity is not None and item.fear is not None]
        momentum = _median_or_none([item.momentum for item in valid])
        activity = _median_or_none([item.activity for item in valid])
        fear = _median_or_none([item.fear for item in valid])
        raw_score = 0.35 * momentum + 0.35 * activity - 0.30 * fear if None not in (momentum, activity, fear) else None
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

    @staticmethod
    def _load_stock_rows(securities, start_date, end_date):
        if not securities:
            return {}
        security_by_id = {security.id: security.ts_code for security in securities}
        security_ids = list(security_by_id)
        fundamentals = {
            (row['security_id'], row['trade_date']): row
            for row in StockDailyFundamentalHistory.objects.filter(
                security_id__in=security_ids,
                trade_date__gte=start_date,
                trade_date__lte=end_date,
            ).values('security_id', 'trade_date', 'turnover_rate_f', 'turnover_rate', 'volume_ratio')
        }
        rows_by_code = defaultdict(list)
        rows = MarketBarDailyHistory.objects.filter(
            security_id__in=security_ids,
            trade_date__gte=start_date,
            trade_date__lte=end_date,
            close__gt=0,
            pre_close__gt=0,
        ).order_by('security_id', 'trade_date').values(
            'security_id', 'trade_date', 'open', 'high', 'low', 'close',
            'pre_close', 'volume', 'amount',
        )
        for row in rows.iterator(chunk_size=50000):
            row.update(fundamentals.get((row['security_id'], row['trade_date']), {}))
            rows_by_code[security_by_id[row['security_id']]].append(row)
        return rows_by_code

    def calculate_stocks_v2(self, trade_dates, ts_codes=None, require_watermark=True):
        dates = sorted(set(trade_dates))
        results_by_date = {trade_date: [] for trade_date in dates}
        if not dates:
            return results_by_date

        securities = list(Security.objects.filter(
            asset_type=Security.AssetType.STOCK,
            list_status='L',
        ).select_related('industry').order_by('ts_code'))
        target_codes = set(ts_codes or (security.ts_code for security in securities))
        targets = [security for security in securities if security.ts_code in target_codes]
        if not targets:
            return results_by_date

        if require_watermark:
            latest_source_date = MarketBarDailyHistory.objects.filter(
                trade_date__lte=dates[-1],
            ).order_by('-trade_date').values_list('trade_date', flat=True).first()
            if latest_source_date is None:
                raise ValueError('No daily market bars are available for the requested period')
            self.validate_watermarks(latest_source_date)

        mapping_row = SWIndustryMappingVersion.objects.filter(
            market='CN', taxonomy='SW2021', is_active=True,
        ).order_by('-published_at').first()
        mapping = mapping_row.artifact if mapping_row and isinstance(mapping_row.artifact, dict) else {}
        memberships = mapping.get('ts_code_to_levels') or mapping.get('membership') or {}
        sw_counts = defaultdict(int)
        industry_counts = defaultdict(int)
        for security in securities:
            membership = memberships.get(security.ts_code.upper(), {})
            if membership.get('l3_code'):
                sw_counts[str(membership['l3_code'])] += 1
            if security.industry_id:
                industry_counts[security.industry_id] += 1

        contexts = {}
        group_members = defaultdict(list)
        for security in securities:
            membership = memberships.get(security.ts_code.upper(), {})
            sw_code = str(membership.get('l3_code') or '')
            if sw_code and sw_counts[sw_code] >= 10:
                group_key = ('SW_L3', sw_code)
                context = {
                    'benchmark_type': 'SW_L3', 'benchmark_code': sw_code,
                    'benchmark_name': str(membership.get('l3_name') or ''),
                    'benchmark_minimum_size': 10,
                }
            elif security.industry_id and industry_counts[security.industry_id] >= 20:
                group_key = ('INDUSTRY', security.industry_id)
                context = {
                    'benchmark_type': 'INDUSTRY', 'benchmark_code': str(security.industry_id),
                    'benchmark_name': security.industry.name, 'benchmark_minimum_size': 20,
                }
            else:
                group_key = ('MARKET', 'ALL_A')
                context = {
                    'benchmark_type': 'MARKET', 'benchmark_code': 'ALL_A',
                    'benchmark_name': '全A', 'benchmark_minimum_size': 500,
                }
            group_members[group_key].append(security)
            if security in targets:
                contexts[security.ts_code] = (group_key, context)

        target_start = dates[0] - timedelta(days=(SCORE_WINDOW + Z_WINDOW + 30) * 2)
        target_rows = self._load_stock_rows(targets, target_start, dates[-1])
        target_samples = {
            code: _stock_dimension_samples(rows)
            for code, rows in target_rows.items()
        }

        used_groups = {group_key for group_key, _context in contexts.values()}
        peer_securities = {
            security.ts_code: security
            for group_key in used_groups
            for security in group_members[group_key]
        }
        peer_start = dates[0] - timedelta(days=120)
        peer_rows = self._load_stock_rows(list(peer_securities.values()), peer_start, dates[-1])
        peer_samples = {
            code: target_samples[code] if code in target_samples else _stock_dimension_samples(rows)
            for code, rows in peer_rows.items()
        }
        peer_samples_by_group_date = defaultdict(list)
        requested_dates = set(dates)
        for group_key in used_groups:
            for security in group_members[group_key]:
                for sample in peer_samples.get(security.ts_code, []):
                    if sample['trade_date'] in requested_dates:
                        peer_samples_by_group_date[(group_key, sample['trade_date'])].append(sample)

        for security in targets:
            samples = target_samples.get(security.ts_code, [])
            if not samples:
                continue
            group_key, context = contexts[security.ts_code]
            raw_history = []
            for history_days, sample in enumerate(samples, start=1):
                dimensions = (sample['momentum'], sample['activity'], sample['fear'])
                raw_score = (
                    0.35 * sample['momentum'] + 0.35 * sample['activity'] - 0.30 * sample['fear']
                    if all(value is not None for value in dimensions) else None
                )
                standardized = _smart_zscore(
                    raw_score, raw_history, window=SCORE_WINDOW,
                ) if len(raw_history) >= SCORE_WINDOW else None
                if raw_score is not None:
                    raw_history.append(raw_score)
                trade_date = sample['trade_date']
                if trade_date not in requested_dates:
                    continue

                peer_samples_for_date = peer_samples_by_group_date[(group_key, trade_date)]
                valid_peers = [
                    peer for peer in peer_samples_for_date
                    if None not in (peer['momentum'], peer['activity'], peer['fear'])
                ]
                score = None
                normalization_mode = 'INSUFFICIENT_DATA'
                if raw_score is None:
                    status = 'INSUFFICIENT_DATA'
                elif standardized is not None:
                    score = round(100.0 / (1.0 + math.exp(-standardized)), 2)
                    status = 'SUCCESS'
                    normalization_mode = 'ROLLING_Z_SCORE'
                elif history_days >= MIN_STOCK_HISTORY and len(valid_peers) >= context['benchmark_minimum_size']:
                    momentum_percentile = _smart_percentile_rank(
                        sample['momentum'], [peer['momentum'] for peer in valid_peers],
                    )
                    activity_percentile = _smart_percentile_rank(
                        sample['activity'], [peer['activity'] for peer in valid_peers],
                    )
                    fear_percentile = _smart_percentile_rank(
                        sample['fear'], [peer['fear'] for peer in valid_peers],
                    )
                    score = round(
                        0.35 * momentum_percentile + 0.35 * activity_percentile
                        + 0.30 * (100.0 - fear_percentile),
                        2,
                    )
                    status = 'CROSS_SECTIONAL_PROVISIONAL'
                    normalization_mode = 'CROSS_SECTIONAL_PERCENTILE'
                else:
                    status = 'WARMING_UP'
                    normalization_mode = 'WARMING_UP'

                turnover_sources = defaultdict(int)
                for peer in peer_samples_for_date:
                    if peer['turnover_source']:
                        turnover_sources[peer['turnover_source']] += 1
                metadata = {
                    **context,
                    'normalization_mode': normalization_mode,
                    'benchmark_sample_size': len(valid_peers),
                    'stock_history_days': history_days,
                    'minimum_history_days': MIN_STOCK_HISTORY,
                    'turnover_sources': dict(turnover_sources),
                    'windows': {'z_score': Z_WINDOW, 'volatility': 10, 'score': SCORE_WINDOW},
                }
                if mapping_row:
                    metadata['sw_mapping_version'] = mapping_row.mapping_version
                    metadata['sw_mapping_source_hash'] = mapping_row.source_hash
                results_by_date[trade_date].append({
                    'security': security,
                    'trade_date': trade_date,
                    'source_trade_date': trade_date,
                    'score': score,
                    'level': _stock_level(score, status),
                    'status': status,
                    'raw_score': raw_score,
                    'standardized_score': standardized,
                    'momentum': sample['momentum'],
                    'activity': sample['activity'],
                    'fear': sample['fear'],
                    'universe_count': len(peer_samples_for_date),
                    'valid_count': len(valid_peers),
                    'coverage': (
                        sum(peer['complete'] for peer in peer_samples_for_date) / len(peer_samples_for_date)
                        if peer_samples_for_date else 0.0
                    ),
                    'peer_type': context['benchmark_type'],
                    'peer_code': context['benchmark_code'],
                    'peer_name': context['benchmark_name'],
                    'peer_count': len(valid_peers),
                    'normalization_mode': normalization_mode,
                    'metadata': metadata,
                })
        return results_by_date

    @transaction.atomic
    def persist(self, market_payload, stock_payloads):
        market_snapshot = None
        if market_payload is not None:
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
