from datetime import date

from market_data.models import Security
from market_data.services.regime import get_market_regime, get_security_regime

from .errors import api_error, api_response
from .catalog import public_api_catalog
from .permissions import require_scopes
from .services.market_data import (
    MarketDataRequestError,
    get_bars,
    get_fundamentals,
    get_security,
    list_securities,
    parse_date,
    parse_history_range,
    parse_pagination,
    normalize_ts_code,
    security_payload,
)


def _meta(page=None, *, data_status='COMPLETE', asof_date=None, source_trade_date=None, warnings=None):
    result = {
        'data_status': data_status,
        'warnings': warnings or [],
    }
    if page is not None:
        result.update({
            'page': page.page,
            'page_size': page.page_size,
            'total': page.total,
            'has_next': page.has_next,
            'next_cursor': None,
        })
    if asof_date is not None:
        result['asof_date'] = asof_date.isoformat()
    if source_trade_date is not None:
        result['source_trade_date'] = source_trade_date.isoformat()
    return result


def _handle_request_error(request, error):
    status_map = {
        'INVALID_REQUEST': 400,
        'INVALID_DATE': 400,
        'INVALID_SYMBOL': 400,
        'RANGE_TOO_LARGE': 400,
        'UNSUPPORTED_FREQUENCY': 422,
        'UNSUPPORTED_REQUEST': 422,
        'INSUFFICIENT_DATA': 503,
        'SECURITY_NOT_FOUND': 404,
    }
    return api_error(request, error.code, str(error), status=status_map.get(error.code, 400), details=error.details)


def _require_get(request):
    if request.method != 'GET':
        return api_error(request, 'INVALID_REQUEST', '仅支持 GET', status=405)
    return None


@require_scopes('market_analysis:read')
def public_api_catalog_view(request):
    if (response := _require_get(request)) is not None:
        return response
    return api_response(request, data=public_api_catalog())


@require_scopes('market_analysis:read')
def securities(request):
    if (response := _require_get(request)) is not None:
        return response
    try:
        page, page_size = parse_pagination(request.GET)
        result = list_securities(filters=request.GET, page=page, page_size=page_size)
    except MarketDataRequestError as error:
        return _handle_request_error(request, error)
    return api_response(request, data=result.items, meta=_meta(result))


@require_scopes('market_analysis:read')
def security_detail(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    try:
        security = get_security(ts_code=ts_code)
    except MarketDataRequestError as error:
        return _handle_request_error(request, error)
    return api_response(request, data=security_payload(security, include_profile=True), meta=_meta())


@require_scopes('market_analysis:read', 'market_analysis:history')
def security_bars(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    try:
        start_date, end_date = parse_history_range(request.GET)
        page, page_size = parse_pagination(request.GET)
        result = get_bars(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            adjust=request.GET.get('adjust', 'qfq').lower(),
            frequency=request.GET.get('frequency', 'D').upper(),
            page=page,
            page_size=page_size,
        )
    except MarketDataRequestError as error:
        return _handle_request_error(request, error)
    status = 'NO_DATA' if result.total == 0 else 'COMPLETE'
    return api_response(request, data=result.items, meta=_meta(result, data_status=status, asof_date=end_date))


@require_scopes('market_analysis:read', 'market_analysis:history')
def security_fundamentals(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    try:
        start_date, end_date = parse_history_range(request.GET)
        page, page_size = parse_pagination(request.GET)
        result = get_fundamentals(
            ts_code=ts_code, start_date=start_date, end_date=end_date,
            page=page, page_size=page_size,
        )
    except MarketDataRequestError as error:
        return _handle_request_error(request, error)
    status = 'NO_DATA' if result.total == 0 else 'COMPLETE'
    return api_response(request, data=result.items, meta=_meta(result, data_status=status, asof_date=end_date))


@require_scopes('market_analysis:read')
def market_regime(request):
    if (response := _require_get(request)) is not None:
        return response
    try:
        asof_date = parse_date(request.GET.get('asof_date'), 'asof_date') or date.today()
        benchmark = normalize_ts_code(request.GET.get('benchmark_ts_code', '000001.SH'))
        result = get_market_regime(asof_date=asof_date, benchmark_ts_code=benchmark)
    except MarketDataRequestError as error:
        return _handle_request_error(request, error)
    except Security.DoesNotExist:
        return api_error(request, 'SECURITY_NOT_FOUND', 'benchmark 证券不存在', status=404)
    return api_response(
        request, data={**result.__dict__, 'asof_trade_date': result.asof_trade_date.isoformat(), 'source_trade_date': result.source_trade_date.isoformat() if result.source_trade_date else None},
        meta=_meta(data_status=result.status, asof_date=asof_date, source_trade_date=result.source_trade_date),
    )


@require_scopes('market_analysis:read')
def security_regime(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    try:
        asof_date = parse_date(request.GET.get('asof_date'), 'asof_date') or date.today()
        security = get_security(ts_code=ts_code)
        if security.asset_type != Security.AssetType.STOCK:
            raise MarketDataRequestError('UNSUPPORTED_REQUEST', '个股 regime 仅支持股票')
        result = get_security_regime(security=security, asof_date=asof_date)
    except MarketDataRequestError as error:
        return _handle_request_error(request, error)
    return api_response(
        request, data={**result.__dict__, 'asof_trade_date': result.asof_trade_date.isoformat(), 'source_trade_date': result.source_trade_date.isoformat() if result.source_trade_date else None},
        meta=_meta(data_status=result.status, asof_date=asof_date, source_trade_date=result.source_trade_date),
    )
from django.db import connection
from django.http import HttpRequest
from django.views.decorators.http import require_GET

from .errors import api_error, api_response


@require_GET
def live(request: HttpRequest):
    return api_response(request, data={'status': 'LIVE'})


@require_GET
def ready(request: HttpRequest):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        return api_error(
            request,
            'UPSTREAM_DEPENDENCY_UNAVAILABLE',
            '必需依赖当前不可用',
            status=503,
            retryable=True,
            details={'dependency': 'postgresql'},
        )
    return api_response(request, data={'status': 'READY'})
