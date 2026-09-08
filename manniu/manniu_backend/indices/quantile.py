from datetime import timedelta

from .constants import WINDOWS


def linear_quantile(values, probability):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def percentile_rank(values, current):
    values = sorted(float(value) for value in values)
    if not values or current is None:
        return None
    if len(values) == 1:
        return 100.0
    below = sum(value < current for value in values)
    equal = sum(value == current for value in values)
    return ((below + max(equal - 1, 0) / 2) / (len(values) - 1)) * 100


def window_start(asof_date, window):
    days = WINDOWS[window]
    return asof_date - timedelta(days=days) if days is not None else None


def summarize_series(series, window='ALL', asof_date=None, min_samples=20):
    if window not in WINDOWS:
        raise ValueError(f'unsupported window: {window}')
    if not series:
        return {'status': 'NO_DATA', 'sample_count': 0, 'current': None, 'p10': None, 'p50': None, 'p90': None, 'percentile': None, 'start_date': None, 'end_date': None}
    ordered = dict(sorted(series.items()))
    actual_asof = asof_date or max(ordered)
    cutoff = window_start(actual_asof, window)
    selected = {day: value for day, value in ordered.items() if day <= actual_asof and (cutoff is None or day >= cutoff)}
    values = list(selected.values())
    current = selected[max(selected)] if selected else None
    result = {
        'status': 'VALID' if len(values) >= min_samples else 'INSUFFICIENT_DATA',
        'sample_count': len(values),
        'current': current,
        'p10': linear_quantile(values, 0.10),
        'p50': linear_quantile(values, 0.50),
        'p90': linear_quantile(values, 0.90),
        'percentile': percentile_rank(values, current),
        'start_date': min(selected) if selected else None,
        'end_date': max(selected) if selected else None,
    }
    if not selected:
        result['status'] = 'NO_DATA'
    return result