from datetime import date, timedelta

from market_data.models import Security
from market_data.services.regime import get_market_regime, get_security_regime

from .errors import api_error, api_response
from .catalog import public_api_catalog
from .permissions import require_scopes
from .permissions import authenticate_request
from financials.services.query import DATASET_MODELS, query_disclosures, query_records
from .services.market_data import Page
from traditional_valuation.services.query import (
    TraditionalValuationRequestError,
    get_compare,
    get_current,
    get_history,
)
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
from .services.indices import (
    IndexGatewayRequestError,
    catalog as index_catalog,
    parse_band_pct,
    parse_index_dates,
    parse_index_key,
    parse_index_keys,
    parse_metric,
    parse_window,
    index_bars as index_bars_result,
    index_fundamentals as index_fundamentals_result,
    overall_composite_fundamentals as overall_composite_fundamentals_result,
    overall_composite_close as overall_composite_close_result,
    unavailable as index_unavailable,
    valuation as index_valuation_result,
)
from market_sentiment.services.query import (
    SentimentQueryError,
    get_market_history,
    get_market_snapshot,
    get_stock_history,
    get_stock_ranking,
    get_stock_snapshot,
)
from .services.predictive_valuation import (
    PredictiveValuationRequestError,
    get_current as get_predictive_current,
    get_fusion as get_predictive_fusion,
    get_history as get_predictive_history,
    get_status as get_predictive_status,
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
        'RESULT_NOT_FOUND': 404,
        'UNSUPPORTED_REPORT_TYPE': 422,
        'UNSUPPORTED_VARIANT': 422,
        'INVALID_INDEX_KEY': 400,
        'INVALID_METRIC': 400,
        'INVALID_WINDOW': 400,
        'INVALID_STYLE': 400,
        'UPSTREAM_DEPENDENCY_UNAVAILABLE': 503,
        'VERSION_CONFLICT': 409,
    }
    return api_error(
        request,
        error.code,
        str(error),
        status=status_map.get(error.code, 400),
        retryable=error.code == 'UPSTREAM_DEPENDENCY_UNAVAILABLE',
        details=error.details,
    )


def _require_get(request):
    if request.method != 'GET':
        return api_error(request, 'INVALID_REQUEST', '仅支持 GET', status=405)
    return None


def _query_bool(params, name, default=False):
    value = params.get(name)
    if value in (None, ''):
        return default
    normalized = str(value).strip().lower()
    if normalized not in {'true', 'false', '1', '0'}:
        raise MarketDataRequestError('INVALID_REQUEST', f'{name} 必须为 true 或 false')
    return normalized in {'true', '1'}


def _query_int(params, name, default, maximum=None):
    try:
        value = int(params.get(name, default))
    except (TypeError, ValueError) as error:
        raise MarketDataRequestError('INVALID_REQUEST', f'{name} 必须为整数') from error
    if value < 1 or (maximum is not None and value > maximum):
        raise MarketDataRequestError('INVALID_REQUEST', f'{name} 参数超出允许范围')
    return value


def _sentiment_date(params, name, *, required=False):
    value = parse_date(params.get(name), name)
    if required and value is None:
        raise MarketDataRequestError('INVALID_DATE', f'{name} 为必填项')
    if value and value > date.today():
        raise MarketDataRequestError('INVALID_DATE', f'{name} 不能晚于当前日期')
    return value


def _sentiment_engine_version(params):
    value = str(params.get('engine_version', '')).strip()
    return value or None


def _sentiment_history_params(request):
    start_date = _sentiment_date(request.GET, 'start_date', required=True)
    end_date = _sentiment_date(request.GET, 'end_date', required=True)
    if start_date > end_date:
        raise MarketDataRequestError('INVALID_DATE', 'start_date 不能晚于 end_date')
    if end_date - start_date > timedelta(days=366):
        raise MarketDataRequestError('RANGE_TOO_LARGE', '历史查询范围不能超过 366 个自然日')
    page, page_size = parse_pagination(request.GET)
    return start_date, end_date, page, page_size, _sentiment_engine_version(request.GET)


def _sentiment_meta(result, *, asof_date=None):
    if isinstance(result, Page):
        return _meta(
            result,
            data_status='NOT_AVAILABLE' if result.total == 0 else 'COMPLETE',
            asof_date=asof_date,
        )
    source_trade_date = result.get('source_trade_date')
    return _meta(
        data_status=result.get('status', 'COMPLETE'),
        asof_date=asof_date,
        source_trade_date=date.fromisoformat(source_trade_date) if source_trade_date else None,
    )


def _traditional_auth(request, *, history=False, diagnostics=False):
    scopes = ['market_analysis:read']
    if history:
        scopes.append('market_analysis:history')
    if diagnostics:
        scopes.append('valuation:diagnostics_read')
    return authenticate_request(request, *scopes)


def _traditional_params(request):
    params = request.GET
    include_methods = _query_bool(params, 'include_methods')
    include_variants = _query_bool(params, 'include_variants')
    include_risk = _query_bool(params, 'include_risk', default=True)
    diagnostics = include_methods or include_variants
    return include_methods, include_variants, include_risk, diagnostics


def _traditional_error(request, error):
    return _handle_request_error(request, error)


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


@require_scopes('market_sentiment:read')
def sentiment_market(request):
    if (response := _require_get(request)) is not None:
        return response
    try:
        asof_date = _sentiment_date(request.GET, 'asof_date') or date.today()
        result = get_market_snapshot(
            asof_date=asof_date,
            engine_version=_sentiment_engine_version(request.GET),
        )
    except (MarketDataRequestError, SentimentQueryError) as error:
        return _handle_request_error(request, error)
    return api_response(request, data=result, meta=_sentiment_meta(result, asof_date=asof_date))


@require_scopes('market_sentiment:read', 'market_sentiment:history_read')
def sentiment_market_history(request):
    if (response := _require_get(request)) is not None:
        return response
    try:
        start_date, end_date, page, page_size, engine_version = _sentiment_history_params(request)
        result = get_market_history(
            start_date=start_date, end_date=end_date, page=page, page_size=page_size,
            engine_version=engine_version,
        )
    except (MarketDataRequestError, SentimentQueryError) as error:
        return _handle_request_error(request, error)
    return api_response(request, data=result.items, meta=_sentiment_meta(result, asof_date=end_date))


@require_scopes('market_sentiment:read')
def sentiment_stock(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    try:
        asof_date = _sentiment_date(request.GET, 'asof_date') or date.today()
        result = get_stock_snapshot(
            ts_code=ts_code,
            asof_date=asof_date,
            engine_version=_sentiment_engine_version(request.GET),
        )
    except (MarketDataRequestError, SentimentQueryError) as error:
        return _handle_request_error(request, error)
    return api_response(request, data=result, meta=_sentiment_meta(result, asof_date=asof_date))


@require_scopes('market_sentiment:read', 'market_sentiment:history_read')
def sentiment_stock_history(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    try:
        start_date, end_date, page, page_size, engine_version = _sentiment_history_params(request)
        result = get_stock_history(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
            engine_version=engine_version,
        )
    except (MarketDataRequestError, SentimentQueryError) as error:
        return _handle_request_error(request, error)
    return api_response(request, data=result.items, meta=_sentiment_meta(result, asof_date=end_date))


@require_scopes('market_sentiment:read')
def sentiment_stock_ranking(request):
    if (response := _require_get(request)) is not None:
        return response
    try:
        asof_date = _sentiment_date(request.GET, 'asof_date') or date.today()
        page, page_size = parse_pagination(request.GET)
        status = str(request.GET.get('status', '')).strip().upper() or None
        if status and status not in {'VALID', 'WARMING_UP', 'INSUFFICIENT_DATA', 'STALE', 'FAILED'}:
            raise MarketDataRequestError('INVALID_REQUEST', 'status 无效')
        result = get_stock_ranking(
            asof_date=asof_date,
            page=page,
            page_size=page_size,
            engine_version=_sentiment_engine_version(request.GET),
            status=status,
        )
    except (MarketDataRequestError, SentimentQueryError) as error:
        return _handle_request_error(request, error)
    return api_response(request, data=result.items, meta=_sentiment_meta(result, asof_date=asof_date))


def _index_error(request, error):
    return _handle_request_error(request, error)


@require_scopes('market_analysis:read')
def indices_catalog(request):
    if (response := _require_get(request)) is not None:
        return response
    try:
        items, status = index_catalog(parse_index_keys(request.GET.get('index_keys')))
    except IndexGatewayRequestError as error:
        return _index_error(request, error)
    return api_response(request, data=items, meta=_meta(data_status=status))


def _index_history_params(request):
    allowed = {'start_date', 'end_date', 'adjust', 'page', 'page_size'}
    unknown = sorted(set(request.GET.keys()) - allowed)
    if unknown:
        raise IndexGatewayRequestError(
            'INVALID_REQUEST', '包含不支持的查询参数', details={'unknown_parameters': unknown},
        )
    start_date, end_date = parse_history_range(request.GET)
    if end_date > date.today():
        raise IndexGatewayRequestError('INVALID_DATE', 'end_date 不能晚于当前日期')
    page, page_size = parse_pagination(request.GET)
    return start_date, end_date, page, page_size


def _index_history_auth(request):
    return authenticate_request(request, 'market_analysis:read', 'market_analysis:history')


def index_bars(request, index_key):
    if (response := _require_get(request)) is not None:
        return response
    if (response := _index_history_auth(request)) is not None:
        return response
    try:
        start_date, end_date, page, page_size = _index_history_params(request)
        result = index_bars_result(
            index_key=parse_index_key(index_key),
            start_date=start_date,
            end_date=end_date,
            adjust=request.GET.get('adjust', 'raw'),
            page=page,
            page_size=page_size,
        )
    except (IndexGatewayRequestError, MarketDataRequestError) as error:
        return _index_error(request, error)
    status = 'NO_DATA' if result.total == 0 else 'COMPLETE'
    return api_response(request, data=result.items, meta=_meta(result, data_status=status, asof_date=end_date))


def index_fundamentals(request, index_key):
    if (response := _require_get(request)) is not None:
        return response
    if (response := _index_history_auth(request)) is not None:
        return response
    try:
        start_date, end_date, page, page_size = _index_history_params(request)
        result = index_fundamentals_result(
            index_key=parse_index_key(index_key),
            start_date=start_date,
            end_date=end_date,
            page=page,
            page_size=page_size,
        )
    except (IndexGatewayRequestError, MarketDataRequestError) as error:
        return _index_error(request, error)
    status = 'NO_DATA' if result.total == 0 else 'COMPLETE'
    return api_response(request, data=result.items, meta=_meta(result, data_status=status, asof_date=end_date))


@require_scopes('market_analysis:read')
def indices_composite_fundamentals(request):
    if (response := _require_get(request)) is not None:
        return response
    try:
        allowed = {'metric', 'window', 'start_date', 'end_date'}
        unknown = sorted(set(request.GET.keys()) - allowed)
        if unknown:
            raise IndexGatewayRequestError(
                'INVALID_REQUEST', '包含不支持的查询参数',
                details={'unknown_parameters': unknown},
            )
        metric = parse_metric(request.GET.get('metric'))
        window = parse_window(request.GET.get('window', 'ALL'))
        start_date, end_date = parse_index_dates(request.GET, allow_window=True)
        payload, status, warnings, coverage = overall_composite_fundamentals_result(
            metric=metric,
            window=window,
            start_date=start_date,
            end_date=end_date,
        )
    except (IndexGatewayRequestError, ValueError) as error:
        if not isinstance(error, IndexGatewayRequestError):
            error = IndexGatewayRequestError('INVALID_REQUEST', str(error))
        return _index_error(request, error)
    source_trade_date = coverage.end_date
    return api_response(
        request,
        data=payload,
        meta=_meta(
            data_status='COMPLETE' if status == 'VALID' else status,
            asof_date=source_trade_date,
            source_trade_date=source_trade_date,
            warnings=warnings,
        ),
    )


@require_scopes('market_analysis:read')
def indices_composite_close(request):
    if (response := _require_get(request)) is not None:
        return response
    try:
        allowed = {'window', 'start_date', 'end_date'}
        unknown = sorted(set(request.GET.keys()) - allowed)
        if unknown:
            raise IndexGatewayRequestError(
                'INVALID_REQUEST', '包含不支持的查询参数',
                details={'unknown_parameters': unknown},
            )
        window = parse_window(request.GET.get('window', 'ALL'))
        start_date, end_date = parse_index_dates(request.GET, allow_window=True)
        payload, status, warnings, coverage = overall_composite_close_result(
            window=window,
            start_date=start_date,
            end_date=end_date,
        )
    except (IndexGatewayRequestError, ValueError) as error:
        if not isinstance(error, IndexGatewayRequestError):
            error = IndexGatewayRequestError('INVALID_REQUEST', str(error))
        return _index_error(request, error)
    source_trade_date = coverage.end_date
    return api_response(
        request,
        data=payload,
        meta=_meta(
            data_status='COMPLETE' if status == 'VALID' else status,
            asof_date=source_trade_date,
            source_trade_date=source_trade_date,
            warnings=warnings,
        ),
    )


@require_scopes('market_analysis:read')
def index_valuation(request, index_key):
    if (response := _require_get(request)) is not None:
        return response
    try:
        metric = parse_metric(request.GET.get('metric'))
        window = parse_window(request.GET.get('window', 'ALL'))
        start_date, end_date = parse_index_dates(request.GET, allow_window=True)
        payload, status, warnings, coverage = index_valuation_result(
            index_key=parse_index_key(index_key),
            metric=metric,
            window=window,
            start_date=start_date,
            end_date=end_date,
            band_pct=parse_band_pct(request.GET.get('band_pct')),
        )
    except (IndexGatewayRequestError, ValueError) as error:
        if not isinstance(error, IndexGatewayRequestError):
            error = IndexGatewayRequestError('INVALID_REQUEST', str(error))
        return _index_error(request, error)
    source_trade_date = coverage.end_date
    return api_response(
        request,
        data=payload,
        meta=_meta(
            data_status='COMPLETE' if status == 'VALID' else status,
            asof_date=source_trade_date,
            source_trade_date=source_trade_date,
            warnings=warnings,
        ),
    )


def _unavailable_index_endpoint(request, capability, *, history=False):
    if (response := _require_get(request)) is not None:
        return response
    if history:
        auth_response = authenticate_request(request, 'market_analysis:read', 'market_analysis:history')
    else:
        auth_response = authenticate_request(request, 'market_analysis:read')
    if auth_response is not None:
        return auth_response
    try:
        index_unavailable(capability)
    except IndexGatewayRequestError as error:
        return _index_error(request, error)


def indices_health(request):
    return _unavailable_index_endpoint(request, 'market health')


def indices_equity_bond(request):
    return _unavailable_index_endpoint(request, 'equity-bond spread')


def indices_health_history(request):
    return _unavailable_index_endpoint(request, 'health history', history=True)


def indices_health_events(request):
    return _unavailable_index_endpoint(request, 'health events', history=True)


def _financial_auth(request):
    historical = any(request.GET.get(name) for name in ('asof_date', 'start_date', 'end_date'))
    scopes = ('market_analysis:read', 'market_analysis:history') if historical else ('market_analysis:read',)
    return authenticate_request(request, *scopes)


def _financial_range(params):
    start_date = parse_date(params.get('start_date'), 'start_date')
    end_date = parse_date(params.get('end_date'), 'end_date')
    if start_date is None:
        return None
    if start_date is not None:
        if start_date > end_date:
            raise MarketDataRequestError('INVALID_DATE', 'start_date 不能晚于 end_date')
        if end_date - start_date > timedelta(days=366):
            raise MarketDataRequestError('RANGE_TOO_LARGE', '历史查询范围不能超过 366 个自然日')
    return (start_date, end_date) if start_date is not None else None


def security_financials(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    if (response := _financial_auth(request)) is not None:
        return response
    try:
        dataset = request.GET.get('dataset', '').strip().lower()
        asof_date = parse_date(request.GET.get('asof_date'), 'asof_date') or date.today()
        if asof_date > date.today():
            raise MarketDataRequestError('INVALID_DATE', 'asof_date 不能晚于当前日期')
        if dataset not in DATASET_MODELS:
            raise MarketDataRequestError('INVALID_REQUEST', 'dataset 无效')
        _financial_range(request.GET)
        page, page_size = parse_pagination(request.GET)
        canonical = normalize_ts_code(ts_code)
        result = query_records(
            ts_code=canonical, dataset=dataset, asof_date=asof_date,
            end_date=parse_date(request.GET.get('end_date'), 'end_date'),
            page=page, page_size=page_size,
        )
    except (MarketDataRequestError, KeyError) as error:
        if isinstance(error, KeyError):
            error = MarketDataRequestError('INVALID_REQUEST', 'dataset 无效')
        return _handle_request_error(request, error)
    status = 'NOT_AVAILABLE' if result.total == 0 else 'COMPLETE'
    return api_response(request, data=result.items, meta=_meta(result, data_status=status, asof_date=asof_date))


def security_disclosures(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    if (response := _financial_auth(request)) is not None:
        return response
    try:
        asof_date = parse_date(request.GET.get('asof_date'), 'asof_date') or date.today()
        if asof_date > date.today():
            raise MarketDataRequestError('INVALID_DATE', 'asof_date 不能晚于当前日期')
        date_range = _financial_range(request.GET)
        page, page_size = parse_pagination(request.GET)
        canonical = normalize_ts_code(ts_code)
        result = query_disclosures(
            ts_code=canonical, asof_date=asof_date, date_range=date_range,
            page=page, page_size=page_size,
        )
    except MarketDataRequestError as error:
        return _handle_request_error(request, error)
    status = 'NOT_AVAILABLE' if result.total == 0 else 'COMPLETE'
    return api_response(request, data=result.items, meta=_meta(result, data_status=status, asof_date=asof_date))


def security_traditional_valuation(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    try:
        include_methods, include_variants, include_risk, diagnostics = _traditional_params(request)
        if (response := _traditional_auth(request, diagnostics=diagnostics)) is not None:
            return response
        asof_date = parse_date(request.GET.get('asof_date'), 'asof_date') or date.today()
        financial_end_date = parse_date(request.GET.get('financial_end_date'), 'financial_end_date')
        canonical = normalize_ts_code(ts_code)
        data = get_current(
            ts_code=canonical,
            asof_date=asof_date,
            report_type=request.GET.get('report_type') or None,
            financial_end_date=financial_end_date,
            profit_bucket=request.GET.get('profit_bucket', 'formal'),
            variant=request.GET.get('variant') or None,
            style_profile=request.GET.get('style_profile', 'baseline'),
            include_methods=include_methods,
            include_risk=include_risk,
            include_variants=include_variants,
            include_diagnostics=diagnostics,
        )
    except (MarketDataRequestError, TraditionalValuationRequestError) as error:
        return _traditional_error(request, error)
    return api_response(
        request,
        data=data,
        meta=_meta(data_status=data.get('source_data_status'), asof_date=asof_date, source_trade_date=_date_from_string(data.get('source_trade_date'))),
    )


def security_traditional_valuation_history(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    try:
        diagnostics = _query_bool(request.GET, 'include_diagnostics')
        if (response := _traditional_auth(request, history=True, diagnostics=diagnostics)) is not None:
            return response
        start_date = parse_date(request.GET.get('start_date'), 'start_date')
        end_date = parse_date(request.GET.get('end_date'), 'end_date')
        financial_end_date = parse_date(request.GET.get('financial_end_date'), 'financial_end_date')
        page, page_size = parse_pagination(request.GET)
        canonical = normalize_ts_code(ts_code)
        result = get_history(
            ts_code=canonical,
            start_date=start_date,
            end_date=end_date,
            financial_end_date=financial_end_date,
            report_type=request.GET.get('report_type') or None,
            profit_bucket=request.GET.get('profit_bucket') or None,
            variant=request.GET.get('variant') or None,
            style_profile=request.GET.get('style_profile') or None,
            page=page,
            page_size=page_size,
            include_diagnostics=diagnostics,
        )
    except (MarketDataRequestError, TraditionalValuationRequestError) as error:
        return _traditional_error(request, error)
    return api_response(
        request,
        data=result['items'],
        meta=_meta(
            page=Page(result['items'], result['page'], result['page_size'], result['total']),
            data_status='COMPLETE' if result['total'] else 'NOT_AVAILABLE',
            asof_date=end_date,
        ),
    )


def security_traditional_valuation_compare(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    try:
        include_methods = _query_bool(request.GET, 'include_methods')
        diagnostics = include_methods or _query_bool(request.GET, 'include_diagnostics')
        if (response := _traditional_auth(request, diagnostics=diagnostics)) is not None:
            return response
        asof_date = parse_date(request.GET.get('asof_date'), 'asof_date') or date.today()
        financial_end_date = parse_date(request.GET.get('financial_end_date'), 'financial_end_date')
        limit = _query_int(request.GET, 'limit', 10, maximum=20)
        canonical = normalize_ts_code(ts_code)
        data = get_compare(
            ts_code=canonical,
            asof_date=asof_date,
            report_type=request.GET.get('report_type') or None,
            financial_end_date=financial_end_date,
            profit_bucket=request.GET.get('profit_bucket', 'formal'),
            variant=request.GET.get('variant') or None,
            style_profile=request.GET.get('style_profile', 'baseline'),
            limit=limit,
            include_methods=include_methods,
            include_diagnostics=diagnostics,
        )
    except (MarketDataRequestError, TraditionalValuationRequestError) as error:
        return _traditional_error(request, error)
    return api_response(
        request,
        data=data,
        meta=_meta(data_status='COMPLETE', asof_date=asof_date, source_trade_date=_date_from_string(data.get('source_trade_date'))),
    )


def _predictive_auth(request, *, history=False, diagnostics=False):
    scopes = ['predictive_valuation:read']
    if history:
        scopes.append('predictive_valuation:history_read')
    if diagnostics:
        scopes.append('predictive_valuation:operator_read')
    return authenticate_request(request, *scopes)


def _predictive_diagnostics(request):
    return 'predictive_valuation:operator_read' in getattr(request, 'auth_scopes', [])


def _predictive_error(request, error):
    return _handle_request_error(request, error)


def _validate_predictive_query(request, allowed):
    unknown = sorted(set(request.GET.keys()) - set(allowed))
    if unknown:
        raise PredictiveValuationRequestError(
            'INVALID_REQUEST', '包含不支持的查询参数', details={'unknown_parameters': unknown},
        )


def security_predictive_valuation(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    if (response := _predictive_auth(request)) is not None:
        return response
    diagnostics = _predictive_diagnostics(request)
    try:
        _validate_predictive_query(
            request, {'asof_date', 'report_type', 'anchor_mode', 'model_version', 'serving_slot'},
        )
        asof_date = parse_date(request.GET.get('asof_date'), 'asof_date')
        data = get_predictive_current(
            ts_code=normalize_ts_code(ts_code), asof_date=asof_date,
            report_type=request.GET.get('report_type') or 'LATEST',
            anchor_mode=request.GET.get('anchor_mode'), model_version=request.GET.get('model_version'),
            serving_slot=request.GET.get('serving_slot'), include_diagnostics=diagnostics,
        )
    except (MarketDataRequestError, PredictiveValuationRequestError) as error:
        return _predictive_error(request, error)
    return api_response(
        request, data=data,
        meta=_meta(
            data_status=data['data_status'],
            asof_date=_date_from_string(data.get('asof_date')),
            source_trade_date=_date_from_string(data.get('source_market_date')),
        ),
    )


def security_predictive_valuation_history(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    if (response := _predictive_auth(request, history=True)) is not None:
        return response
    diagnostics = _predictive_diagnostics(request)
    try:
        _validate_predictive_query(
            request, {'start_date', 'end_date', 'report_type', 'page', 'page_size'},
        )
        start_date = parse_date(request.GET.get('start_date'), 'start_date')
        end_date = parse_date(request.GET.get('end_date'), 'end_date')
        page, page_size = parse_pagination(request.GET)
        result = get_predictive_history(
            ts_code=normalize_ts_code(ts_code), start_date=start_date, end_date=end_date,
            report_type=request.GET.get('report_type') or None, page=page, page_size=page_size,
            include_diagnostics=diagnostics,
        )
    except (MarketDataRequestError, PredictiveValuationRequestError) as error:
        return _predictive_error(request, error)
    return api_response(
        request, data=result['items'],
        meta=_meta(
            page=Page(result['items'], result['page'], result['page_size'], result['total']),
            data_status='COMPLETE' if result['total'] else 'NOT_AVAILABLE',
            asof_date=end_date,
        ),
    )


def security_predictive_valuation_fusion(request, ts_code):
    if (response := _require_get(request)) is not None:
        return response
    if (response := _predictive_auth(request)) is not None:
        return response
    diagnostics = _predictive_diagnostics(request)
    try:
        _validate_predictive_query(request, {'asof_date', 'anchor_mode', 'model_version'})
        asof_date = parse_date(request.GET.get('asof_date'), 'asof_date')
        data = get_predictive_fusion(
            ts_code=normalize_ts_code(ts_code), asof_date=asof_date,
            anchor_mode=request.GET.get('anchor_mode'), model_version=request.GET.get('model_version'),
            include_diagnostics=diagnostics,
        )
    except (MarketDataRequestError, PredictiveValuationRequestError) as error:
        return _predictive_error(request, error)
    return api_response(
        request, data=data,
        meta=_meta(
            data_status=data['data_status'], asof_date=_date_from_string(data.get('asof_date')),
            source_trade_date=_date_from_string(data.get('source_market_date')),
        ),
    )


def predictive_valuation_status(request):
    if (response := _require_get(request)) is not None:
        return response
    if (response := _predictive_auth(request)) is not None:
        return response
    try:
        _validate_predictive_query(request, {'report_type', 'model_version', 'serving_slot'})
        data = get_predictive_status(
            report_type=request.GET.get('report_type') or None,
            model_version=request.GET.get('model_version'), serving_slot=request.GET.get('serving_slot'),
        )
    except PredictiveValuationRequestError as error:
        return _predictive_error(request, error)
    return api_response(request, data=data, meta=_meta(data_status=data['data_status']))


def _date_from_string(value):
    return date.fromisoformat(value) if value else None
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
