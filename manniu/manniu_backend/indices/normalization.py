from collections.abc import Mapping
from datetime import date, datetime
import math


def get_value(row, field, default=None):
    if isinstance(row, Mapping):
        return row.get(field, default)
    return getattr(row, field, default)


def normalize_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, '%Y%m%d').date()
        return datetime.strptime(text[:10], '%Y-%m-%d').date()
    return None


def positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def normalize_series(rows, value_field, start_date=None, end_date=None):
    """Return a date-keyed positive series, with later rows replacing duplicates."""
    series = {}
    for row in rows:
        trade_date = normalize_date(get_value(row, 'trade_date'))
        value = positive_number(get_value(row, value_field))
        if trade_date is None or value is None:
            continue
        if start_date and trade_date < start_date:
            continue
        if end_date and trade_date > end_date:
            continue
        series[trade_date] = value
    return dict(sorted(series.items()))


def common_date_values(series_by_key, required_keys):
    required_keys = tuple(required_keys)
    if not required_keys:
        return {}
    dates = set(series_by_key.get(required_keys[0], {}))
    for key in required_keys[1:]:
        dates &= set(series_by_key.get(key, {}))
    return {
        trade_date: {key: series_by_key[key][trade_date] for key in required_keys}
        for trade_date in sorted(dates)
    }