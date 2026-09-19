from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from math import isfinite

from market_data.models import MarketBarDailyHistory, SWIndustryDailyHistory, Security
from market_data.services.industry import IndustryMappingError, resolve_sw_industry_mapping
from market_sentiment.services.query import SentimentQueryError, get_stock_snapshot


TECHNICAL_RULE_VERSION = 'technical_rule_v1'
MAX_PERIOD = 250
MAX_HISTORY_DAYS = 366
MIN_HISTORY_ROWS = 26


class TechnicalTrendRequestError(ValueError):
    def __init__(self, code, message, *, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class TechnicalRow:
    trade_date: date
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None


def _number(value):
    return float(value) if value is not None else None


def _date(value):
    return value.isoformat() if value is not None else None


def _sma(values, index, period):
    window = values[max(0, index - period + 1):index + 1]
    if len(window) < period or any(value is None for value in window):
        return None
    return sum(window) / period


def _ema(values, period):
    result = [None] * len(values)
    usable = [index for index, value in enumerate(values) if value is not None]
    if len(usable) < period:
        return result
    seed_index = usable[period - 1]
    seed_values = values[usable[0]:seed_index + 1]
    if any(value is None for value in seed_values):
        return result
    result[seed_index] = sum(seed_values) / period
    multiplier = 2 / (period + 1)
    for index in range(seed_index + 1, len(values)):
        if values[index] is None or result[index - 1] is None:
            continue
        result[index] = (values[index] - result[index - 1]) * multiplier + result[index - 1]
    return result


def _rsi(closes, period=14):
    result = [None] * len(closes)
    changes = [None] + [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    gains = [None if change is None else max(change, 0) for change in changes]
    losses = [None if change is None else max(-change, 0) for change in changes]
    if len(closes) <= period or any(value is None for value in gains[1:period + 1] + losses[1:period + 1]):
        return result
    average_gain = sum(gains[1:period + 1]) / period
    average_loss = sum(losses[1:period + 1]) / period
    result[period] = 100 if average_loss == 0 else 100 - (100 / (1 + average_gain / average_loss))
    for index in range(period + 1, len(closes)):
        average_gain = (average_gain * (period - 1) + gains[index]) / period
        average_loss = (average_loss * (period - 1) + losses[index]) / period
        result[index] = 100 if average_loss == 0 else 100 - (100 / (1 + average_gain / average_loss))
    return result


def _atr(rows, period=14):
    true_ranges = [None] * len(rows)
    for index, row in enumerate(rows):
        if row.high is None or row.low is None:
            continue
        values = [row.high - row.low]
        if index and rows[index - 1].close is not None:
            values.extend((abs(row.high - rows[index - 1].close), abs(row.low - rows[index - 1].close)))
        true_ranges[index] = max(values)
    return [_sma(true_ranges, index, period) for index in range(len(rows))]


def _kdj(rows, period=9):
    k_values = [None] * len(rows)
    d_values = [None] * len(rows)
    j_values = [None] * len(rows)
    previous_k = 50.0
    previous_d = 50.0
    for index, row in enumerate(rows):
        window = rows[max(0, index - period + 1):index + 1]
        if len(window) < period or any(item.high is None or item.low is None or item.close is None for item in window):
            continue
        highest = max(item.high for item in window)
        lowest = min(item.low for item in window)
        rsv = 50.0 if highest == lowest else (row.close - lowest) / (highest - lowest) * 100
        previous_k = previous_k * 2 / 3 + rsv / 3
        previous_d = previous_d * 2 / 3 + previous_k / 3
        k_values[index] = previous_k
        d_values[index] = previous_d
        j_values[index] = 3 * previous_k - 2 * previous_d
    return k_values, d_values, j_values


def _value(value, digits=6):
    if value is None or not isfinite(value):
        return None
    return round(float(value), digits)


def _trend(current, previous, tolerance=0.001):
    if current is None or previous is None:
        return None
    if abs(current - previous) <= abs(current) * tolerance:
        return 'FLAT'
    return 'UP' if current > previous else 'DOWN'


def _signal(trade_date, signal_type, direction, evidence):
    return {
        'trade_date': _date(trade_date),
        'type': signal_type,
        'direction': direction,
        'evidence': evidence,
        'status': 'CONFIRMED',
    }


def _industry_security(identity):
    code = str(identity.get('index_code') or identity.get('industry_code') or '').strip().upper()
    if not code:
        return None
    exact = Security.objects.filter(ts_code=code, asset_type=Security.AssetType.INDEX).first()
    if exact is not None:
        return exact
    root = code.split('.')[0]
    return Security.objects.filter(ts_code__startswith=f'{root}.', asset_type=Security.AssetType.INDEX, market='SW').first()


def _row_payload(row, indicators):
    return {
        'trade_date': _date(row.trade_date),
        'open': _value(row.open),
        'high': _value(row.high),
        'low': _value(row.low),
        'close': _value(row.close),
        'volume': row.volume,
        **{key: _value(value) for key, value in indicators.items()},
    }


def _sentiment_payload(ts_code, asof_date, latest_trade_date, warnings):
    try:
        snapshot = get_stock_snapshot(ts_code=ts_code, asof_date=asof_date)
    except SentimentQueryError as error:
        warning_code = 'SENTIMENT_NOT_AVAILABLE' if error.code in {'RESULT_NOT_FOUND', 'VERSION_CONFLICT'} else f'SENTIMENT_{error.code}'
        warnings.append(warning_code)
        return {
            'status': 'NOT_AVAILABLE',
            'score': None,
            'level': None,
            'source_trade_date': None,
        }

    status = snapshot.get('status') or 'NOT_AVAILABLE'
    if status not in {'VALID', 'COMPLETE'}:
        warnings.append(f'SENTIMENT_{status}')
    source_trade_date = snapshot.get('source_trade_date')
    if source_trade_date and source_trade_date != _date(latest_trade_date):
        warnings.append('SENTIMENT_ASOF_MISMATCH')
    return {
        'status': status,
        'score': snapshot.get('score'),
        'level': snapshot.get('level'),
        'source_trade_date': source_trade_date,
        'engine_version': snapshot.get('engine_version'),
        'coverage': snapshot.get('coverage'),
    }


def get_technical_trend(*, ts_code, start_date, end_date, adjust='qfq', frequency='D', period=120):
    if adjust not in {'raw', 'qfq', 'hfq'}:
        raise TechnicalTrendRequestError('INVALID_REQUEST', 'adjust 仅支持 raw、qfq、hfq')
    if frequency != 'D':
        raise TechnicalTrendRequestError('UNSUPPORTED_FREQUENCY', '当前仅支持日线 frequency=D')
    try:
        period = int(period)
    except (TypeError, ValueError) as exc:
        raise TechnicalTrendRequestError('INVALID_REQUEST', 'period 必须为整数') from exc
    if period not in {60, 120, 250}:
        raise TechnicalTrendRequestError('INVALID_REQUEST', 'period 仅支持 60、120、250')
    if end_date > date.today():
        raise TechnicalTrendRequestError('INVALID_DATE', 'end_date 不能晚于当前日期')
    if start_date > end_date or end_date - start_date > timedelta(days=MAX_HISTORY_DAYS):
        raise TechnicalTrendRequestError('RANGE_TOO_LARGE', '历史查询范围不能超过 366 个自然日')

    try:
        security = Security.objects.get(ts_code=str(ts_code).upper())
    except Security.DoesNotExist as exc:
        raise TechnicalTrendRequestError('SECURITY_NOT_FOUND', '证券不存在') from exc
    if security.asset_type != Security.AssetType.STOCK:
        raise TechnicalTrendRequestError('UNSUPPORTED_REQUEST', '技术趋势仅支持股票')

    suffix = '' if adjust == 'raw' else f'_{adjust}'
    source_rows = list(MarketBarDailyHistory.objects.filter(
        security=security, trade_date__lte=end_date,
    ).order_by('-trade_date')[:max(period, 205)])
    source_rows.reverse()
    rows = [
        TechnicalRow(
            trade_date=row.trade_date,
            open=_number(getattr(row, f'open{suffix}')),
            high=_number(getattr(row, f'high{suffix}')),
            low=_number(getattr(row, f'low{suffix}')),
            close=_number(getattr(row, f'close{suffix}')),
            volume=row.volume,
        )
        for row in source_rows
        if start_date <= row.trade_date <= end_date
    ]
    if len(rows) < MIN_HISTORY_ROWS:
        raise TechnicalTrendRequestError('INSUFFICIENT_DATA', '股票日线数据不足')
    if not any(row.close is not None for row in rows):
        raise TechnicalTrendRequestError('INSUFFICIENT_DATA', f'{adjust} 调整数据不可用')

    calculation_rows = [
        TechnicalRow(
            trade_date=row.trade_date,
            open=_number(getattr(source, f'open{suffix}')),
            high=_number(getattr(source, f'high{suffix}')),
            low=_number(getattr(source, f'low{suffix}')),
            close=_number(getattr(source, f'close{suffix}')),
            volume=source.volume,
        )
        for source in source_rows
        for row in [source]
    ]
    closes = [row.close for row in calculation_rows]
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = [None if ema12[index] is None or ema26[index] is None else ema12[index] - ema26[index] for index in range(len(closes))]
    signal_line = _ema(macd_line, 9)
    histogram = [None if macd_line[index] is None or signal_line[index] is None else macd_line[index] - signal_line[index] for index in range(len(closes))]
    rsi_values = _rsi(closes)
    atr_values = _atr(calculation_rows)
    k_values, d_values, j_values = _kdj(calculation_rows)
    ma_periods = (6, 10, 25, 43, 60, 120, 200)

    series = []
    index_by_date = {row.trade_date: index for index, row in enumerate(calculation_rows)}
    for row in rows:
        index = index_by_date[row.trade_date]
        indicators = {f'ma{ma_period}': _sma(closes, index, ma_period) for ma_period in ma_periods}
        indicators.update({
            'rsi14': rsi_values[index],
            'macd_dif': macd_line[index],
            'macd_dea': signal_line[index],
            'macd_histogram': histogram[index],
            'atr14': atr_values[index],
            'kdj_k': k_values[index],
            'kdj_d': d_values[index],
            'kdj_j': j_values[index],
        })
        series.append(_row_payload(row, indicators))

    latest = series[-1]
    previous = series[-2] if len(series) > 1 else {}
    score_parts = [
        None if latest['close'] is None or latest['ma25'] is None else latest['close'] >= latest['ma25'],
        None if latest['close'] is None or latest['ma60'] is None else latest['close'] >= latest['ma60'],
        None if latest['ma25'] is None or latest['ma60'] is None else latest['ma25'] >= latest['ma60'],
        None if latest['macd_histogram'] is None else latest['macd_histogram'] >= 0,
        None if latest['rsi14'] is None else latest['rsi14'] >= 50,
    ]
    valid_score_parts = [part for part in score_parts if part is not None]
    score = round(sum(valid_score_parts) / len(valid_score_parts) * 100) if len(valid_score_parts) >= 3 else None
    trend = 'UP' if score is not None and score >= 60 else 'DOWN' if score is not None and score <= 40 else 'FLAT'
    signals = []
    if latest['ma6'] is not None and previous.get('ma6') is not None and latest['ma25'] is not None and previous.get('ma25') is not None:
        if previous['ma6'] <= previous['ma25'] < latest['ma6']:
            signals.append(_signal(rows[-1].trade_date, 'MA_CROSS', 'UP', 'MA6 上穿 MA25'))
        elif previous['ma6'] >= previous['ma25'] > latest['ma6']:
            signals.append(_signal(rows[-1].trade_date, 'MA_CROSS', 'DOWN', 'MA6 下穿 MA25'))
    if latest['macd_histogram'] is not None and previous.get('macd_histogram') is not None:
        if previous['macd_histogram'] <= 0 < latest['macd_histogram']:
            signals.append(_signal(rows[-1].trade_date, 'MACD_CROSS', 'UP', 'MACD 柱体由负转正'))
        elif previous['macd_histogram'] >= 0 > latest['macd_histogram']:
            signals.append(_signal(rows[-1].trade_date, 'MACD_CROSS', 'DOWN', 'MACD 柱体由正转负'))
    if latest['rsi14'] is not None and latest['rsi14'] >= 70:
        signals.append(_signal(rows[-1].trade_date, 'RSI_OVERBOUGHT', 'DOWN', 'RSI14 >= 70'))
    elif latest['rsi14'] is not None and latest['rsi14'] <= 30:
        signals.append(_signal(rows[-1].trade_date, 'RSI_OVERSOLD', 'UP', 'RSI14 <= 30'))

    warnings = []
    industry = {'name': None, 'index_code': None, 'series': [], 'relative_strength': None, 'direction': None, 'status': 'NOT_AVAILABLE'}
    try:
        identity = resolve_sw_industry_mapping(security=security)
        industry_security = _industry_security(identity)
        if industry_security is not None:
            industry_rows = dict(SWIndustryDailyHistory.objects.filter(
                security=industry_security, trade_date__range=(rows[0].trade_date, rows[-1].trade_date), close__isnull=False,
            ).values_list('trade_date', 'close'))
            industry['name'] = identity.get('industry_name') or identity.get('name') or industry_security.name
            industry['index_code'] = industry_security.ts_code
            industry['series'] = [{'trade_date': _date(item), 'close': _value(value)} for item, value in sorted(industry_rows.items())]
            stock_closes = {row.trade_date: row.close for row in rows if row.close is not None}
            common_dates = sorted(set(stock_closes).intersection(industry_rows))
            if len(common_dates) >= 2:
                stock_start = stock_closes[common_dates[0]]
                stock_end = stock_closes[common_dates[-1]]
                industry_start = float(industry_rows[common_dates[0]])
                industry_end = float(industry_rows[common_dates[-1]])
                industry['relative_strength'] = _value((stock_end / stock_start - 1) - (industry_end / industry_start - 1))
                industry['direction'] = 'UP' if industry['relative_strength'] > 0 else 'DOWN' if industry['relative_strength'] < 0 else 'FLAT'
                industry['status'] = 'COMPLETE'
            else:
                warnings.append('INDUSTRY_SERIES_INSUFFICIENT')
        else:
            warnings.append('SW_INDUSTRY_DATA_UNAVAILABLE')
    except IndustryMappingError:
        warnings.append('SW_INDUSTRY_MAPPING_UNAVAILABLE')

    return {
        'security': {'ts_code': security.ts_code, 'name': security.name},
        'series': series,
        'momentum': {
            'latest': {key: latest.get(key) for key in ('rsi14', 'macd_dif', 'macd_dea', 'macd_histogram', 'atr14', 'kdj_k', 'kdj_d', 'kdj_j')},
            'history': [
                {'trade_date': item['trade_date'], **{key: item.get(key) for key in ('rsi14', 'macd_dif', 'macd_dea', 'macd_histogram', 'atr14', 'kdj_k', 'kdj_d', 'kdj_j')}}
                for item in series
            ],
        },
        'market_sentiment': _sentiment_payload(security.ts_code, end_date, rows[-1].trade_date, warnings),
        'relative_strength': industry,
        'summary': {
            'trend': trend,
            'trend_score': score,
            'trend_level': 'STRONG' if score is not None and score >= 75 else 'MODERATE' if score is not None and score >= 60 else 'WEAK' if score is not None and score <= 40 else 'NEUTRAL' if score is not None else None,
            'volatility_status': 'HIGH' if latest.get('atr14') is not None and latest.get('close') and latest['atr14'] / latest['close'] >= 0.04 else 'NORMAL' if latest.get('atr14') is not None else None,
            'ma_relation': {'ma25_vs_ma60': _trend(latest.get('ma25'), latest.get('ma60')), 'price_vs_ma25': 'ABOVE' if latest.get('close') is not None and latest.get('ma25') is not None and latest['close'] >= latest['ma25'] else 'BELOW' if latest.get('close') is not None and latest.get('ma25') is not None else None},
            'data_status': 'COMPLETE' if not warnings else 'PARTIAL',
        },
        'signals': signals,
        'warnings': warnings,
        'rule_version': TECHNICAL_RULE_VERSION,
        'adjust': adjust,
        'frequency': frequency,
        'period': period,
    }
