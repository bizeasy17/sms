from __future__ import annotations

import math
from collections import defaultdict
from statistics import median

from datastore.models import Corporation, StockFundamentalHistory, StockTradingHistory


ENGINE_VERSION = 'daily_v1_20260828'
Z_WINDOW = 20
VOLATILITY_WINDOW = 10
SCORE_WINDOW = 252


def _number(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _mean(values):
    return sum(values) / len(values) if values else None


def _std(values):
    if len(values) < 2:
        return None
    average = _mean(values)
    variance = sum((value - average) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _z_score(value, history):
    deviation = _std(history)
    if value is None or deviation is None or deviation == 0:
        return None
    return max(-3.0, min(3.0, (value - _mean(history)) / deviation))


def _weighted_score(parts):
    available = [(value, weight) for value, weight in parts if value is not None]
    total_weight = sum(weight for _, weight in available)
    required_weight = sum(weight for _, weight in parts)
    if not available or total_weight < required_weight * 0.7:
        return None
    return sum(value * weight for value, weight in available) / total_weight


def _level(score):
    if score is None:
        return 'WARMING_UP'
    if score < 30:
        return 'PANIC'
    if score < 45:
        return 'CAUTIOUS'
    if score <= 55:
        return 'NEUTRAL'
    if score < 70:
        return 'POSITIVE'
    return 'EUPHORIC'


def _scope_codes(scope_type, scope_code):
    if scope_type == 'STOCK':
        return [scope_code]
    if scope_type == 'MARKET':
        return Corporation.objects.filter(asset='E', list_status='L').values_list('ts_code', flat=True)
    raise ValueError(f'Unsupported scope type: {scope_type}')


def _load_rows(start_date, end_date, scope_type, scope_code):
    codes = _scope_codes(scope_type, scope_code)
    trading_query = StockTradingHistory.objects.filter(trade_date__gte=start_date, trade_date__lte=end_date, freq='D')
    fundamental_query = StockFundamentalHistory.objects.filter(trade_date__gte=start_date, trade_date__lte=end_date, freq='D')
    trading_query = trading_query.filter(ts_code__in=codes)
    fundamental_query = fundamental_query.filter(ts_code__in=codes)

    fundamentals = {
        (row['ts_code'], row['trade_date']): row
        for row in fundamental_query.values('ts_code', 'trade_date', 'turnover_rate_f', 'turnover_rate', 'volume_ratio', 'circ_mv')
    }
    rows_by_code = defaultdict(list)
    for row in trading_query.order_by('ts_code', 'trade_date').values(
        'ts_code', 'trade_date', 'open', 'high', 'low', 'pre_close', 'close', 'vol', 'amount'
    ):
        fundamental = fundamentals.get((row['ts_code'], row['trade_date']), {})
        row.update(fundamental)
        rows_by_code[row['ts_code']].append(row)
    return rows_by_code


def calculate_snapshots(*, start_date, end_date, scope_type='MARKET', scope_code='ALL_A'):
    rows_by_code = _load_rows(start_date, end_date, scope_type, scope_code)
    dates = sorted({row['trade_date'] for rows in rows_by_code.values() for row in rows})
    daily = defaultdict(list)

    for rows in rows_by_code.values():
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
        for index, row in enumerate(rows):
            close = _number(row['close'])
            pre_close = _number(row['pre_close'])
            open_price = _number(row['open'])
            high = _number(row['high'])
            low = _number(row['low'])
            volume = _number(row['vol'])
            amount = _number(row['amount'])
            turnover_f = _number(row.get('turnover_rate_f'))
            turnover = turnover_f if turnover_f is not None else _number(row.get('turnover_rate'))
            volume_ratio = _number(row.get('volume_ratio'))
            return_1 = close / pre_close - 1 if close and pre_close and pre_close > 0 else None
            streak_up = streak_up + 1 if return_1 is not None and return_1 > 0 else 0
            return_5 = close / _number(rows[index - 5]['close']) - 1 if index >= 5 and close and _number(rows[index - 5]['close']) else None
            return_20 = close / _number(rows[index - 20]['close']) - 1 if index >= 20 and close and _number(rows[index - 20]['close']) else None
            amplitude = (high - low) / pre_close if high is not None and low is not None and pre_close and pre_close > 0 else None
            lower_shadow = (min(open_price, close) - low) / (high - low) if None not in (open_price, close, high, low) and high > low else None
            volatility = _std(returns[-VOLATILITY_WINDOW:]) if len(returns) >= VOLATILITY_WINDOW else None
            vol_z = _z_score(volume, volumes[-Z_WINDOW:]) if len(volumes) >= Z_WINDOW else None
            amount_z = _z_score(amount, amounts[-Z_WINDOW:]) if len(amounts) >= Z_WINDOW else None
            turnover_z = _z_score(turnover, turnovers[-Z_WINDOW:]) if len(turnovers) >= Z_WINDOW else None
            volume_ratio_z = _z_score(volume_ratio, volume_ratios[-Z_WINDOW:]) if len(volume_ratios) >= Z_WINDOW else None
            return_1_z = _z_score(return_1, returns[-Z_WINDOW:]) if len(returns) >= Z_WINDOW else None
            return_5_z = _z_score(return_5, returns_5[-Z_WINDOW:]) if len(returns_5) >= Z_WINDOW else None
            return_20_z = _z_score(return_20, returns_20[-Z_WINDOW:]) if len(returns_20) >= Z_WINDOW else None
            streak_z = _z_score(streak_up, streaks[-Z_WINDOW:]) if len(streaks) >= Z_WINDOW else None
            amp_z = _z_score(amplitude, amplitudes[-Z_WINDOW:]) if len(amplitudes) >= Z_WINDOW else None
            lower_shadow_z = _z_score(lower_shadow, lower_shadows[-Z_WINDOW:]) if len(lower_shadows) >= Z_WINDOW else None
            volatility_z = _z_score(volatility, volatilities[-Z_WINDOW:]) if len(volatilities) >= Z_WINDOW else None
            down_return = max(-return_1, 0) if return_1 is not None else None
            down_return_z = _z_score(down_return, down_returns[-Z_WINDOW:]) if len(down_returns) >= Z_WINDOW else None
            momentum = _weighted_score([(return_1_z, .40), (return_5_z, .30), (return_20_z, .20), (streak_z, .10)])
            activity = _weighted_score([(vol_z, .25), (amount_z, .20), (turnover_z, .40), (volume_ratio_z, .15)])
            fear = _weighted_score([(volatility_z, .30), (amp_z, .25), (lower_shadow_z, .15), (vol_z if return_1 is not None and return_1 < 0 else None, .20), (down_return_z, .10)])
            daily[row['trade_date']].append({'momentum': momentum, 'activity': activity, 'fear': fear, 'complete': close is not None and pre_close is not None and volume is not None and amount is not None, 'turnover_source': 'turnover_rate_f' if turnover_f is not None else 'turnover_rate' if turnover is not None else None})
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

    raw_history = []
    results = []
    for trade_date in dates:
        samples = daily[trade_date]
        valid = [sample for sample in samples if None not in (sample['momentum'], sample['activity'], sample['fear'])]
        coverage = sum(sample['complete'] for sample in samples) / len(samples) if samples else 0.0
        if not valid:
            results.append({'trade_date': trade_date, 'status': 'INSUFFICIENT_DATA', 'sentiment_level': 'INSUFFICIENT_DATA', 'universe_size': len(samples), 'valid_sample_size': 0, 'coverage': coverage, 'metadata': {'turnover_sources': {}}})
            continue
        momentum = median(sample['momentum'] for sample in valid)
        activity = median(sample['activity'] for sample in valid)
        fear = median(sample['fear'] for sample in valid)
        raw_score = .35 * momentum + .35 * activity - .30 * fear
        standardized = _z_score(raw_score, raw_history[-SCORE_WINDOW:]) if len(raw_history) >= SCORE_WINDOW else None
        score = round(100 / (1 + math.exp(-standardized)), 2) if standardized is not None else None
        sources = defaultdict(int)
        for sample in samples:
            if sample['turnover_source']:
                sources[sample['turnover_source']] += 1
        results.append({'trade_date': trade_date, 'status': 'SUCCESS' if score is not None else 'WARMING_UP', 'sentiment_level': _level(score), 'sentiment_score': score, 'raw_score': raw_score, 'standardized_score': standardized, 'momentum_score': momentum, 'activity_score': activity, 'fear_score': fear, 'universe_size': len(samples), 'valid_sample_size': len(valid), 'coverage': coverage, 'metadata': {'turnover_sources': dict(sources), 'windows': {'z_score': Z_WINDOW, 'volatility': VOLATILITY_WINDOW, 'score': SCORE_WINDOW}}})
        raw_history.append(raw_score)
    return results
