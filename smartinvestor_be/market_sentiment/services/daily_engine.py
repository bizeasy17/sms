from __future__ import annotations

import math
from collections import defaultdict
from statistics import median

from datastore.models import Corporation, StockFundamentalHistory, StockTradingHistory


ENGINE_VERSION = 'daily_v1_20260828'
STOCK_ENGINE_VERSION = 'stock_daily_v2_20260830'
Z_WINDOW = 20
VOLATILITY_WINDOW = 10
SCORE_WINDOW = 252
MIN_STOCK_HISTORY = 20


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


def _percentile_rank(value, values):
    if value is None or not values:
        return None
    below = sum(candidate < value for candidate in values)
    equal = sum(candidate == value for candidate in values)
    return 100.0 * (below + equal / 2.0) / len(values)


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


def _scope_context(scope_type, scope_code):
    if scope_type == 'MARKET':
        codes = Corporation.objects.filter(asset='E', list_status='L').values_list('ts_code', flat=True)
        return codes, {'benchmark_type': 'MARKET', 'benchmark_code': 'ALL_A', 'benchmark_name': '全A'}
    if scope_type == 'STOCK':
        corporation = Corporation.objects.filter(ts_code=scope_code).values(
            'industry_id', 'industry__name', 'sw_l3_code', 'sw_l3_name'
        ).first()
        if corporation is None:
            raise ValueError(f'Unknown stock scope code: {scope_code}')
        candidates = []
        if corporation['sw_l3_code']:
            candidates.append((
                'SW_L3', corporation['sw_l3_code'], corporation['sw_l3_name'], 10,
                Corporation.objects.filter(asset='E', list_status='L', sw_l3_code=corporation['sw_l3_code']),
            ))
        if corporation['industry_id']:
            candidates.append((
                'INDUSTRY', str(corporation['industry_id']), corporation['industry__name'], 20,
                Corporation.objects.filter(asset='E', list_status='L', industry_id=corporation['industry_id']),
            ))
        candidates.append((
            'MARKET', 'ALL_A', '全A', 500,
            Corporation.objects.filter(asset='E', list_status='L'),
        ))
        for benchmark_type, benchmark_code, benchmark_name, minimum_size, queryset in candidates:
            codes = list(queryset.values_list('ts_code', flat=True))
            if len(codes) >= minimum_size or benchmark_type == 'MARKET':
                return codes, {
                    'benchmark_type': benchmark_type,
                    'benchmark_code': benchmark_code,
                    'benchmark_name': benchmark_name,
                    'benchmark_minimum_size': minimum_size,
                }
    raise ValueError(f'Unsupported scope type: {scope_type}')


def _load_rows(start_date, end_date, scope_type, scope_code):
    codes, scope_context = _scope_context(scope_type, scope_code)
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
    return rows_by_code, scope_context


def _calculate_dimension_samples(rows):
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
        samples.append({'ts_code': row['ts_code'], 'trade_date': row['trade_date'], 'momentum': momentum, 'activity': activity, 'fear': fear, 'complete': close is not None and pre_close is not None and volume is not None and amount is not None, 'turnover_source': 'turnover_rate_f' if turnover_f is not None else 'turnover_rate' if turnover is not None else None})
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


def calculate_all_stock_snapshots_latest(*, start_date, end_date, limit=None):
    rows_by_code, _scope_context_data = _load_rows(start_date, end_date, 'MARKET', 'ALL_A')
    corporations = list(Corporation.objects.filter(asset='E', list_status='L').order_by('ts_code').values(
        'ts_code', 'industry_id', 'industry__name', 'sw_l3_code', 'sw_l3_name'
    ))
    sw_counts = defaultdict(int)
    industry_counts = defaultdict(int)
    for corporation in corporations:
        if corporation['sw_l3_code']:
            sw_counts[corporation['sw_l3_code']] += 1
        if corporation['industry_id']:
            industry_counts[corporation['industry_id']] += 1

    latest_by_code = {}
    for ts_code, rows in rows_by_code.items():
        raw_history = []
        latest_sample = None
        latest_raw_score = None
        latest_standardized = None
        for sample in _calculate_dimension_samples(rows):
            if None not in (sample['momentum'], sample['activity'], sample['fear']):
                raw_score = .35 * sample['momentum'] + .35 * sample['activity'] - .30 * sample['fear']
                standardized = _z_score(raw_score, raw_history[-SCORE_WINDOW:]) if len(raw_history) >= SCORE_WINDOW else None
                raw_history.append(raw_score)
            else:
                raw_score = None
                standardized = None
            if sample['trade_date'] == end_date:
                latest_sample = sample
                latest_raw_score = raw_score
                latest_standardized = standardized
        if latest_sample is not None:
            latest_by_code[ts_code] = {
                'sample': latest_sample,
                'raw_score': latest_raw_score,
                'standardized_score': latest_standardized,
                'history_days': len(rows),
            }

    benchmark_by_code = {}
    for corporation in corporations:
        ts_code = corporation['ts_code']
        if corporation['sw_l3_code'] and sw_counts[corporation['sw_l3_code']] >= 10:
            benchmark_by_code[ts_code] = (
                ('SW_L3', corporation['sw_l3_code']),
                {'benchmark_type': 'SW_L3', 'benchmark_code': corporation['sw_l3_code'], 'benchmark_name': corporation['sw_l3_name'], 'benchmark_minimum_size': 10},
            )
        elif corporation['industry_id'] and industry_counts[corporation['industry_id']] >= 20:
            benchmark_by_code[ts_code] = (
                ('INDUSTRY', corporation['industry_id']),
                {'benchmark_type': 'INDUSTRY', 'benchmark_code': str(corporation['industry_id']), 'benchmark_name': corporation['industry__name'], 'benchmark_minimum_size': 20},
            )
        else:
            benchmark_by_code[ts_code] = (
                ('MARKET', 'ALL_A'),
                {'benchmark_type': 'MARKET', 'benchmark_code': 'ALL_A', 'benchmark_name': '全A', 'benchmark_minimum_size': 500},
            )

    all_samples_by_benchmark = defaultdict(list)
    for ts_code, state in latest_by_code.items():
        benchmark = benchmark_by_code.get(ts_code)
        sample = state['sample']
        if benchmark:
            all_samples_by_benchmark[benchmark[0]].append(sample)

    target_codes = [corporation['ts_code'] for corporation in corporations]
    if limit:
        target_codes = target_codes[:limit]
    results = []
    for ts_code in target_codes:
        state = latest_by_code.get(ts_code)
        benchmark = benchmark_by_code.get(ts_code)
        if state is None or benchmark is None:
            continue
        sample = state['sample']
        all_samples = all_samples_by_benchmark[benchmark[0]]
        valid = [item for item in all_samples if None not in (item['momentum'], item['activity'], item['fear'])]
        coverage = sum(item['complete'] for item in all_samples) / len(all_samples) if all_samples else 0.0
        context = benchmark[1]
        score = None
        standardized = state['standardized_score']
        if state['raw_score'] is None:
            status = 'INSUFFICIENT_DATA'
            normalization_mode = 'INSUFFICIENT_DATA'
        elif standardized is not None:
            score = round(100 / (1 + math.exp(-standardized)), 2)
            status = 'SUCCESS'
            normalization_mode = 'ROLLING_Z_SCORE'
        elif state['history_days'] >= MIN_STOCK_HISTORY and len(valid) >= context['benchmark_minimum_size']:
            momentum_percentile = _percentile_rank(sample['momentum'], [item['momentum'] for item in valid])
            activity_percentile = _percentile_rank(sample['activity'], [item['activity'] for item in valid])
            fear_percentile = _percentile_rank(sample['fear'], [item['fear'] for item in valid])
            score = round(.35 * momentum_percentile + .35 * activity_percentile + .30 * (100 - fear_percentile), 2)
            status = 'CROSS_SECTIONAL_PROVISIONAL'
            normalization_mode = 'CROSS_SECTIONAL_PERCENTILE'
        else:
            status = 'WARMING_UP'
            normalization_mode = 'WARMING_UP'
        sources = defaultdict(int)
        for item in valid:
            if item['turnover_source']:
                sources[item['turnover_source']] += 1
        results.append({
            'scope_code': ts_code,
            'trade_date': end_date,
            'status': status,
            'sentiment_level': _level(score),
            'sentiment_score': score,
            'raw_score': state['raw_score'],
            'standardized_score': standardized,
            'momentum_score': sample['momentum'],
            'activity_score': sample['activity'],
            'fear_score': sample['fear'],
            'universe_size': len(all_samples),
            'valid_sample_size': len(valid),
            'coverage': coverage,
            'metadata': {**context, 'normalization_mode': normalization_mode, 'benchmark_sample_size': len(valid), 'stock_history_days': state['history_days'], 'minimum_history_days': MIN_STOCK_HISTORY, 'turnover_sources': dict(sources), 'windows': {'z_score': Z_WINDOW, 'volatility': VOLATILITY_WINDOW, 'score': SCORE_WINDOW}},
        })
    return results


def calculate_snapshots(*, start_date, end_date, scope_type='MARKET', scope_code='ALL_A'):
    rows_by_code, scope_context = _load_rows(start_date, end_date, scope_type, scope_code)
    if scope_type == 'STOCK':
        dates = [row['trade_date'] for row in rows_by_code.get(scope_code, [])]
    else:
        dates = sorted({row['trade_date'] for rows in rows_by_code.values() for row in rows})
    daily = defaultdict(list)

    for rows in rows_by_code.values():
        for sample in _calculate_dimension_samples(rows):
            daily[sample['trade_date']].append(sample)

    raw_history = []
    results = []
    for history_days, trade_date in enumerate(dates, start=1):
        samples = daily[trade_date]
        valid = [sample for sample in samples if None not in (sample['momentum'], sample['activity'], sample['fear'])]
        coverage = sum(sample['complete'] for sample in samples) / len(samples) if samples else 0.0
        target = next((sample for sample in valid if sample['ts_code'] == scope_code), None) if scope_type == 'STOCK' else None
        if not valid or (scope_type == 'STOCK' and target is None):
            results.append({'trade_date': trade_date, 'status': 'INSUFFICIENT_DATA', 'sentiment_level': 'INSUFFICIENT_DATA', 'universe_size': len(samples), 'valid_sample_size': len(valid), 'coverage': coverage, 'metadata': {**scope_context, 'stock_history_days': history_days, 'turnover_sources': {}}})
            continue
        aggregation_samples = [target] if target is not None else valid
        momentum = median(sample['momentum'] for sample in aggregation_samples)
        activity = median(sample['activity'] for sample in aggregation_samples)
        fear = median(sample['fear'] for sample in aggregation_samples)
        raw_score = .35 * momentum + .35 * activity - .30 * fear
        standardized = _z_score(raw_score, raw_history[-SCORE_WINDOW:]) if len(raw_history) >= SCORE_WINDOW else None
        if standardized is not None:
            score = round(100 / (1 + math.exp(-standardized)), 2)
            status = 'SUCCESS'
            normalization_mode = 'ROLLING_Z_SCORE'
        elif scope_type == 'STOCK' and history_days >= MIN_STOCK_HISTORY and len(valid) >= scope_context['benchmark_minimum_size']:
            momentum_percentile = _percentile_rank(momentum, [sample['momentum'] for sample in valid])
            activity_percentile = _percentile_rank(activity, [sample['activity'] for sample in valid])
            fear_percentile = _percentile_rank(fear, [sample['fear'] for sample in valid])
            score = round(.35 * momentum_percentile + .35 * activity_percentile + .30 * (100 - fear_percentile), 2)
            status = 'CROSS_SECTIONAL_PROVISIONAL'
            normalization_mode = 'CROSS_SECTIONAL_PERCENTILE'
        else:
            score = None
            status = 'WARMING_UP'
            normalization_mode = 'WARMING_UP'
        sources = defaultdict(int)
        for sample in samples:
            if sample['turnover_source']:
                sources[sample['turnover_source']] += 1
        results.append({'trade_date': trade_date, 'status': status, 'sentiment_level': _level(score), 'sentiment_score': score, 'raw_score': raw_score, 'standardized_score': standardized, 'momentum_score': momentum, 'activity_score': activity, 'fear_score': fear, 'universe_size': len(samples), 'valid_sample_size': len(valid), 'coverage': coverage, 'metadata': {**scope_context, 'normalization_mode': normalization_mode, 'benchmark_sample_size': len(valid), 'stock_history_days': history_days if scope_type == 'STOCK' else None, 'minimum_history_days': MIN_STOCK_HISTORY if scope_type == 'STOCK' else None, 'turnover_sources': dict(sources), 'windows': {'z_score': Z_WINDOW, 'volatility': VOLATILITY_WINDOW, 'score': SCORE_WINDOW}}})
        raw_history.append(raw_score)
    return results
