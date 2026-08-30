from __future__ import annotations

import math
from collections import defaultdict

from django.db import connections

from datastore.models import StockTradingHistory
from market_sentiment.services.daily_engine import (
    SCORE_WINDOW,
    VOLATILITY_WINDOW,
    Z_WINDOW,
    _level,
    _number,
    _std,
    _weighted_score,
    _z_score,
)


ENGINE_VERSION = 'index_daily_v1_20260829'
INDEX_WEIGHTS = {
    '000001.SH': 0.25,
    '399001.SZ': 0.25,
    '000300.SH': 0.30,
    '000905.SH': 0.20,
}


def _load_rows(start_date, end_date):
    basic_by_key = {}
    placeholders = ','.join(['%s'] * len(INDEX_WEIGHTS))
    sql = f'''
        SELECT ts_code, trade_date, turnover_rate_f
        FROM earnings_mkt_index_dailybasic
        WHERE ts_code IN ({placeholders})
          AND trade_date >= %s
          AND trade_date <= %s
    '''
    params = [*INDEX_WEIGHTS.keys(), start_date, end_date]
    with connections['earnings'].cursor() as cursor:
        cursor.execute(sql, params)
        for ts_code, trade_date, turnover_rate_f in cursor.fetchall():
            basic_by_key[(ts_code, trade_date)] = _number(turnover_rate_f)

    rows_by_code = defaultdict(list)
    trading_rows = StockTradingHistory.objects.filter(
        ts_code__in=INDEX_WEIGHTS,
        trade_date__gte=start_date,
        trade_date__lte=end_date,
        freq='D',
    ).order_by('ts_code', 'trade_date').values(
        'ts_code', 'trade_date', 'open', 'high', 'low', 'pre_close', 'close', 'vol', 'amount'
    )
    for row in trading_rows:
        row['turnover_rate_f'] = basic_by_key.get((row['ts_code'], row['trade_date']))
        rows_by_code[row['ts_code']].append(row)
    return rows_by_code


def _calculate_index_dimensions(rows):
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
    output = {}

    for index, row in enumerate(rows):
        close = _number(row['close'])
        pre_close = _number(row['pre_close'])
        open_price = _number(row['open'])
        high = _number(row['high'])
        low = _number(row['low'])
        volume = _number(row['vol'])
        amount = _number(row['amount'])
        turnover = _number(row.get('turnover_rate_f'))
        previous_volumes = volumes[-5:]
        average_volume = sum(previous_volumes) / len(previous_volumes) if len(previous_volumes) == 5 else None
        volume_ratio = volume / average_volume if volume is not None and average_volume and average_volume > 0 else None

        return_1 = close / pre_close - 1 if close and pre_close and pre_close > 0 else None
        streak_up = streak_up + 1 if return_1 is not None and return_1 > 0 else 0
        prior_5 = _number(rows[index - 5]['close']) if index >= 5 else None
        prior_20 = _number(rows[index - 20]['close']) if index >= 20 else None
        return_5 = close / prior_5 - 1 if close and prior_5 else None
        return_20 = close / prior_20 - 1 if close and prior_20 else None
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

        output[row['trade_date']] = {
            'momentum': _weighted_score([(return_1_z, .40), (return_5_z, .30), (return_20_z, .20), (streak_z, .10)]),
            'activity': _weighted_score([(vol_z, .25), (amount_z, .20), (turnover_z, .40), (volume_ratio_z, .15)]),
            'fear': _weighted_score([(volatility_z, .30), (amp_z, .25), (lower_shadow_z, .15), (vol_z if return_1 is not None and return_1 < 0 else None, .20), (down_return_z, .10)]),
            'complete': None not in (close, pre_close, volume, amount, turnover),
            'volume_ratio': volume_ratio,
        }

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
    return output


def _weighted_dimension(samples, key):
    available = [(sample[key], INDEX_WEIGHTS[code]) for code, sample in samples.items() if sample.get(key) is not None]
    available_weight = sum(weight for _, weight in available)
    if available_weight < 0.70:
        return None
    return sum(value * weight for value, weight in available) / available_weight


def calculate_index_composite_snapshots(*, start_date, end_date):
    rows_by_code = _load_rows(start_date, end_date)
    dimensions_by_code = {
        code: _calculate_index_dimensions(rows_by_code.get(code, []))
        for code in INDEX_WEIGHTS
    }
    dates = sorted({trade_date for rows in dimensions_by_code.values() for trade_date in rows})
    raw_history = []
    results = []

    for trade_date in dates:
        samples = {
            code: dimensions[trade_date]
            for code, dimensions in dimensions_by_code.items()
            if trade_date in dimensions
        }
        momentum = _weighted_dimension(samples, 'momentum')
        activity = _weighted_dimension(samples, 'activity')
        fear = _weighted_dimension(samples, 'fear')
        available_codes = [code for code, sample in samples.items() if None not in (sample['momentum'], sample['activity'], sample['fear'])]
        coverage = sum(INDEX_WEIGHTS[code] for code in available_codes)
        metadata = {
            'index_weights': INDEX_WEIGHTS,
            'available_codes': available_codes,
            'volume_ratio': 'vol / mean(previous_5_vol)',
            'windows': {'z_score': Z_WINDOW, 'volatility': VOLATILITY_WINDOW, 'score': SCORE_WINDOW},
        }
        if None in (momentum, activity, fear):
            results.append({
                'trade_date': trade_date,
                'status': 'INSUFFICIENT_DATA',
                'sentiment_level': 'INSUFFICIENT_DATA',
                'universe_size': len(INDEX_WEIGHTS),
                'valid_sample_size': len(available_codes),
                'coverage': coverage,
                'metadata': metadata,
            })
            continue

        raw_score = .35 * momentum + .35 * activity - .30 * fear
        standardized = _z_score(raw_score, raw_history[-SCORE_WINDOW:]) if len(raw_history) >= SCORE_WINDOW else None
        score = round(100 / (1 + math.exp(-standardized)), 2) if standardized is not None else None
        results.append({
            'trade_date': trade_date,
            'status': 'SUCCESS' if score is not None else 'WARMING_UP',
            'sentiment_level': _level(score),
            'sentiment_score': score,
            'raw_score': raw_score,
            'standardized_score': standardized,
            'momentum_score': momentum,
            'activity_score': activity,
            'fear_score': fear,
            'universe_size': len(INDEX_WEIGHTS),
            'valid_sample_size': len(available_codes),
            'coverage': coverage,
            'metadata': metadata,
        })
        raw_history.append(raw_score)
    return results