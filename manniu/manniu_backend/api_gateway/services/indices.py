from datetime import date
from dataclasses import asdict, is_dataclass

from indices.constants import INDEX_BY_KEY, METRIC_FIELDS, WINDOWS
from indices.repositories import MarketDataIndexRepository
from indices.services import IndexService

from .market_data import MarketDataRequestError, parse_date


VALID_STYLES = {'overall', 'defensive', 'balanced', 'aggressive'}
VALID_EVENT_TYPES = {
    'valuation_opportunity',
    'valuation_risk',
    'health_below_threshold',
    'health_above_threshold',
}
MAX_INDEX_KEYS = 7


class IndexGatewayRequestError(MarketDataRequestError):
    pass


def _serialize(value):
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {str(_serialize(key)): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _service():
    return IndexService(MarketDataIndexRepository())


def parse_index_keys(raw_value):
    if raw_value in (None, ''):
        return list(INDEX_BY_KEY)
    keys = [item.strip().lower() for item in str(raw_value).split(',') if item.strip()]
    if not keys or len(keys) > MAX_INDEX_KEYS or len(keys) != len(set(keys)):
        raise IndexGatewayRequestError('INVALID_INDEX_KEY', 'index_keys 必须为不重复的指数业务键')
    unknown = [key for key in keys if key not in INDEX_BY_KEY]
    if unknown:
        raise IndexGatewayRequestError('INVALID_INDEX_KEY', f'未知指数业务键: {unknown[0]}')
    return keys


def parse_index_key(raw_value):
    key = str(raw_value or '').strip().lower()
    if key not in INDEX_BY_KEY:
        raise IndexGatewayRequestError('INVALID_INDEX_KEY', '未知指数业务键')
    return key


def parse_metric(raw_value):
    metric = str(raw_value or '').strip().upper()
    if metric not in METRIC_FIELDS:
        raise IndexGatewayRequestError('INVALID_METRIC', 'metric 仅支持 PE、PETTM、PB')
    return metric


def parse_window(raw_value):
    window = str(raw_value or '').strip().upper()
    if window not in WINDOWS:
        raise IndexGatewayRequestError('INVALID_WINDOW', 'window 不受支持')
    return window


def parse_style(raw_value):
    style = str(raw_value or 'overall').strip().lower()
    if style not in VALID_STYLES:
        raise IndexGatewayRequestError('INVALID_STYLE', 'style 不受支持')
    return style


def parse_index_dates(params, *, allow_window=True):
    start_date = parse_date(params.get('start_date'), 'start_date')
    end_date = parse_date(params.get('end_date'), 'end_date')
    if start_date and end_date and start_date > end_date:
        raise IndexGatewayRequestError('INVALID_DATE', 'start_date 不能晚于 end_date')
    if end_date and end_date > date.today():
        raise IndexGatewayRequestError('INVALID_DATE', 'end_date 不能晚于当前日期')
    if start_date and start_date > date.today():
        raise IndexGatewayRequestError('INVALID_DATE', 'start_date 不能晚于当前日期')
    if allow_window and params.get('window') and (start_date or end_date):
        raise IndexGatewayRequestError('INVALID_REQUEST', 'window 不能与明确日期范围同时使用')
    if start_date and end_date and (end_date - start_date).days > 366:
        raise IndexGatewayRequestError('RANGE_TOO_LARGE', '历史查询范围不能超过 366 个自然日')
    return start_date, end_date


def parse_band_pct(raw_value):
    if raw_value in (None, ''):
        return 0.1
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise IndexGatewayRequestError('INVALID_REQUEST', 'band_pct 必须为非负数字') from exc
    if value < 0:
        raise IndexGatewayRequestError('INVALID_REQUEST', 'band_pct 必须为非负数字')
    return value


def catalog(index_keys):
    repository = MarketDataIndexRepository()
    items = []
    for key in index_keys:
        definition = INDEX_BY_KEY[key]
        security, requested_code = repository.resolve_security(key)
        latest_bar = repository.latest_bar(security) if security else None
        latest_fundamental = repository.latest_fundamental(security) if security else None
        items.append({
            'index_key': key,
            'ts_code': requested_code,
            'source_ts_code': security.ts_code if security else None,
            'name': definition.name,
            'short_name': definition.name,
            'supported_metrics': list(METRIC_FIELDS),
            'supported_windows': list(WINDOWS),
            'latest_trade_date': _serialize(getattr(latest_bar, 'trade_date', None)),
            'latest_fundamental_date': _serialize(getattr(latest_fundamental, 'trade_date', None)),
            'data_status': 'VALID' if security else 'NO_DATA',
            'warnings': [] if security else ['index security data unavailable'],
        })
    status = 'COMPLETE' if all(item['data_status'] == 'VALID' for item in items) else 'PARTIAL'
    return items, status


def valuation(*, index_key, metric, window, start_date, end_date, band_pct):
    result = _service().simple_valuation(
        index_key,
        start_date=start_date,
        end_date=end_date,
        band_pct=band_pct,
    )
    payload = _serialize(result.data)
    selected_method = payload.get('methods', {}).get(metric.lower())
    payload['metric'] = metric
    payload['window'] = window
    payload['method'] = selected_method
    payload.pop('methods', None)
    payload['coverage'] = _serialize(result.coverage)
    return payload, result.status, result.warnings, result.coverage


def unavailable(capability):
    raise IndexGatewayRequestError(
        'UPSTREAM_DEPENDENCY_UNAVAILABLE',
        f'{capability} 领域服务尚未提供可读取结果',
        details={'capability': capability},
    )
