from datetime import date
from dataclasses import asdict, is_dataclass

from indices.constants import INDEX_BY_KEY, METRIC_FIELDS, WINDOWS
from indices.repositories import MarketDataIndexRepository
from indices.services import IndexService

from .market_data import (
    MAX_HISTORY_ROWS,
    VALID_BAR_ADJUSTMENTS,
    MarketDataRequestError,
    Page,
    parse_date,
)


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


def overall_composite_fundamentals(*, metric, window, start_date, end_date):
    result = _service().composite_quantile(
        metric=metric,
        style='overall',
        window=window,
        start_date=start_date,
        end_date=end_date,
    )
    payload = _serialize(result.data)
    payload['coverage'] = _serialize(result.coverage)
    return payload, result.status, result.warnings, result.coverage


def overall_composite_close(*, window, start_date, end_date):
    result = _service().composite_quantile(
        metric='CLOSE',
        style='overall',
        window=window,
        start_date=start_date,
        end_date=end_date,
    )
    payload = _serialize(result.data)
    payload['coverage'] = _serialize(result.coverage)
    return payload, result.status, result.warnings, result.coverage


def _number(value):
    return float(value) if value is not None else None


def _date(value):
    return value.isoformat() if value is not None else None


def _datetime(value):
    return value.isoformat() if value is not None else None


def _resolve_history(index_key):
    security, requested_code = MarketDataIndexRepository().resolve_security(index_key)
    if security is None:
        raise IndexGatewayRequestError('RESULT_NOT_FOUND', f'指数不存在: {requested_code}')
    return security


def _page(queryset, page, page_size):
    total = queryset.count()
    if total > MAX_HISTORY_ROWS:
        raise IndexGatewayRequestError('RANGE_TOO_LARGE', '单次历史查询最多返回 2000 条记录')
    return queryset[(page - 1) * page_size:page * page_size], Page([], page, page_size, total)


def index_bars(*, index_key, start_date, end_date, adjust, page, page_size):
    if adjust not in VALID_BAR_ADJUSTMENTS:
        raise IndexGatewayRequestError('INVALID_REQUEST', 'adjust 仅支持 raw、qfq、hfq')
    security = _resolve_history(index_key)
    rows, result_page = _page(
        MarketDataIndexRepository().index_bar_history(security, start_date, end_date),
        page, page_size,
    )
    suffix = '' if adjust == 'raw' else f'_{adjust}'
    items = []
    for row in rows:
        items.append({
            'ts_code': INDEX_BY_KEY[index_key].ts_code,
            'source_ts_code': security.ts_code,
            'trade_date': _date(row.trade_date),
            'frequency': 'D',
            'open': _number(getattr(row, f'open{suffix}')),
            'high': _number(getattr(row, f'high{suffix}')),
            'low': _number(getattr(row, f'low{suffix}')),
            'close': _number(getattr(row, f'close{suffix}')),
            'pre_close': _number(getattr(row, f'pre_close{suffix}')),
            'change': _number(getattr(row, f'change{suffix}')),
            'pct_change': _number(getattr(row, f'pct_change{suffix}')),
            'volume': row.volume,
            'amount': _number(row.amount),
            'adjust': adjust,
            'source_updated_at': _datetime(row.source_updated_at),
            'synced_at': _datetime(row.synced_at),
        })
    return Page(items, result_page.page, result_page.page_size, result_page.total)


def index_fundamentals(*, index_key, start_date, end_date, page, page_size):
    security = _resolve_history(index_key)
    rows, result_page = _page(
        MarketDataIndexRepository().index_fundamental_history(security, start_date, end_date),
        page, page_size,
    )
    fields = ('pe', 'pe_ttm', 'pb', 'turnover_rate', 'turnover_rate_f', 'total_mv', 'float_mv')
    items = []
    for row in rows:
        items.append({
            'ts_code': INDEX_BY_KEY[index_key].ts_code,
            'source_ts_code': security.ts_code,
            'trade_date': _date(row.trade_date),
            **{field: _number(getattr(row, field)) for field in fields},
            'source_updated_at': _datetime(row.source_updated_at),
            'synced_at': _datetime(row.synced_at),
            'units': {'market_cap': '10k_CNY', 'rates': 'percentage_points'},
        })
    return Page(items, result_page.page, result_page.page_size, result_page.total)


def unavailable(capability):
    raise IndexGatewayRequestError(
        'UPSTREAM_DEPENDENCY_UNAVAILABLE',
        f'{capability} 领域服务尚未提供可读取结果',
        details={'capability': capability},
    )
