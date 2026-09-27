from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from financials.models import FinancialDisclosureRecord, FinancialIndicatorRecord
from market_data.models import (
    IndexDailyFundamentalHistory,
    MarketBarDailyHistory,
    Security,
)
from .models import FinancialHealthSearchHistory
from .services import classify_stock, compute_score, normalize_ts_code, suggest_stocks
from .services.model_topn_scoring import attach_feature_hints, rebuild_score

logger = logging.getLogger(__name__)
RETURN_SPREAD_PERIOD_DAYS = {'1Y': 365, '2Y': 730, '5Y': 1825}
RETURN_SPREAD_BENCHMARKS = {
    'sh_index': {'name': '上证指数', 'ts_code': '000001.SH'},
    'sz_index': {'name': '深证成指', 'ts_code': '399001.SZ'},
    'cyb_index': {'name': '创业板指', 'ts_code': '399006.SZ'},
    'hs300': {'name': '沪深300', 'ts_code': '000300.SH'},
}


def _error(code: str, message: str, status: int, details: dict | None = None) -> Response:
    return Response({'code': code, 'message': message, 'details': details or {}}, status=status)


def _parse_limit(raw: str | None, default: int, minimum: int, maximum: int) -> int:
    if raw in (None, ''):
        return default
    return max(minimum, min(maximum, int(raw)))


def _parse_bool(raw: str | None) -> bool:
    return str(raw or '').strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _user_key(request) -> str:
    user = getattr(request, 'user', None)
    if user and getattr(user, 'is_authenticated', False):
        return f'u:{user.id}'
    return 'u:anonymous'


def _stock_meta(ts_code: str) -> tuple[str, str]:
    security = Security.objects.select_related('industry').filter(ts_code=ts_code).first()
    if not security:
        return '', ''
    return security.name or '', security.industry.name if security.industry else ''


def _search_history_items(user_key: str, limit: int) -> dict[str, Any]:
    records = FinancialHealthSearchHistory.objects.filter(user_key=user_key).order_by('-searched_at')[:limit]
    return {
        'items': [
            {
                'id': str(row.id),
                'ts_code': row.ts_code,
                'symbol': row.symbol,
                'name': row.name,
                'industry': row.industry,
                'searched_at': row.searched_at.isoformat().replace('+00:00', 'Z'),
            }
            for row in records
        ],
        'total': FinancialHealthSearchHistory.objects.filter(user_key=user_key).count(),
    }


def _latest_financial_period(ts_code: str) -> tuple[str, str]:
    security = Security.objects.filter(ts_code=ts_code).first()
    if not security:
        return '', ''
    row = FinancialIndicatorRecord.objects.filter(security=security).order_by('-end_date', '-ann_date').first()
    if not row or not row.end_date:
        return '', ''
    report_type = {
        (3, 31): 'Q1',
        (6, 30): 'H1',
        (9, 30): 'Q3',
        (12, 31): 'FY',
    }.get((row.end_date.month, row.end_date.day), '')
    return row.end_date.strftime('%Y%m%d'), report_type


def _parse_date(raw: str | None) -> date | None:
    text = (raw or '').strip()
    if not text:
        return None
    for fmt in ('%Y%m%d', '%Y-%m-%d'):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _daily_return(row: dict[str, Any]) -> float | None:
    change = row.get('pct_change')
    if change is not None:
        try:
            return float(change) / 100.0
        except (TypeError, ValueError):
            pass
    close, previous = row.get('close'), row.get('pre_close')
    try:
        return float(close) / float(previous) - 1.0 if close is not None and previous else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _cumulative_returns(rows: list[dict[str, Any]]) -> dict[date, float]:
    result: dict[date, float] = {}
    cumulative = 1.0
    for row in rows:
        change = _daily_return(row)
        if change is None:
            continue
        cumulative *= 1.0 + change
        result[row['trade_date']] = (cumulative - 1.0) * 100.0
    return result


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def search_suggest(request):
    query = (request.query_params.get('q') or '').strip()
    if not query:
        return _error('INVALID_PARAM', 'q is required', HTTP_400_BAD_REQUEST)
    try:
        limit = _parse_limit(request.query_params.get('limit'), 10, 1, 20)
    except (TypeError, ValueError):
        return _error('INVALID_PARAM', 'limit is invalid', HTTP_400_BAD_REQUEST)
    return Response({'query': query, 'items': suggest_stocks(query, limit)}, status=HTTP_200_OK)


@api_view(['GET', 'POST', 'DELETE'])
@permission_classes([permissions.AllowAny])
def search_history(request):
    user_key = _user_key(request)
    if request.method == 'GET':
        try:
            limit = _parse_limit(request.query_params.get('limit'), 10, 1, 10)
        except (TypeError, ValueError):
            return _error('INVALID_PARAM', 'limit is invalid', HTTP_400_BAD_REQUEST)
        return Response(_search_history_items(user_key, limit), status=HTTP_200_OK)

    if request.method == 'POST':
        raw_code = request.data.get('ts_code')
        if not raw_code:
            return _error('INVALID_PARAM', 'ts_code is required', HTTP_400_BAD_REQUEST)
        try:
            ts_code = normalize_ts_code(str(raw_code))
        except ValueError as exc:
            return _error('INVALID_PARAM', str(exc), HTTP_400_BAD_REQUEST)
        name, industry = _stock_meta(ts_code)
        if not Security.objects.filter(ts_code=ts_code, asset_type='STOCK').exists():
            return _error('NOT_FOUND', 'security not found', HTTP_404_NOT_FOUND)
        record, created = FinancialHealthSearchHistory.objects.update_or_create(
            user_key=user_key,
            ts_code=ts_code,
            defaults={
                'symbol': ts_code.split('.')[0],
                'name': name,
                'industry': industry,
                'searched_at': timezone.now(),
            },
        )
        old_ids = list(
            FinancialHealthSearchHistory.objects.filter(user_key=user_key)
            .order_by('-searched_at').values_list('id', flat=True)[10:]
        )
        if old_ids:
            FinancialHealthSearchHistory.objects.filter(id__in=old_ids).delete()
        logger.info('metrics.search_history_upsert', extra={'event': 'metrics.search_history_upsert', 'ts_code': ts_code, 'is_created': created})
        return Response({
            'ok': True,
            'record': {
                'id': str(record.id),
                'ts_code': record.ts_code,
                'searched_at': record.searched_at.isoformat().replace('+00:00', 'Z'),
            },
        }, status=HTTP_200_OK)

    deleted, _ = FinancialHealthSearchHistory.objects.filter(user_key=user_key).delete()
    return Response({'ok': True, 'deleted': deleted}, status=HTTP_200_OK)


@api_view(['DELETE'])
@permission_classes([permissions.AllowAny])
def search_history_delete(request, history_id: str):
    deleted, _ = FinancialHealthSearchHistory.objects.filter(id=history_id, user_key=_user_key(request)).delete()
    if not deleted:
        return _error('NOT_FOUND', 'history not found', HTTP_404_NOT_FOUND)
    return Response({'ok': True}, status=HTTP_200_OK)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def classify(request):
    raw_code = request.data.get('ts_code')
    if not raw_code:
        return _error('INVALID_PARAM', 'ts_code is required', HTTP_400_BAD_REQUEST)
    try:
        return Response(classify_stock(str(raw_code), request.data.get('asof_date')), status=HTTP_200_OK)
    except ValueError as exc:
        return _error('INVALID_PARAM', str(exc), HTTP_400_BAD_REQUEST)
    except LookupError:
        return _error('NOT_FOUND', 'security not found', HTTP_404_NOT_FOUND)
    except Exception as exc:
        logger.exception('metrics.classify.error')
        return _error('INTERNAL_ERROR', str(exc), HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def score(request):
    raw_code = request.query_params.get('ts_code')
    if not raw_code:
        return _error('INVALID_PARAM', 'ts_code is required', HTTP_400_BAD_REQUEST)
    asof_date = request.query_params.get('asof_date')
    requested_report_type = request.query_params.get('report_type') or ''
    try:
        score_topn = _parse_limit(request.query_params.get('score_topn') or request.query_params.get('topn'), 20, 6, 20)
        store_topn = _parse_limit(request.query_params.get('store_topn'), 50, 20, 50)
    except (TypeError, ValueError):
        return _error('INVALID_PARAM', 'score_topn/store_topn is invalid', HTTP_400_BAD_REQUEST)
    use_top20_dimension = _parse_bool(request.query_params.get('use_top20_dimension'))
    try:
        payload = compute_score(
            str(raw_code), asof_date, _parse_bool(request.query_params.get('force_recompute')),
            include_feature_values=use_top20_dimension,
        )
    except ValueError as exc:
        code = 'DATA_INSUFFICIENT' if 'missing' in str(exc) else 'INVALID_PARAM'
        status = HTTP_422_UNPROCESSABLE_ENTITY if code == 'DATA_INSUFFICIENT' else HTTP_400_BAD_REQUEST
        return _error(code, str(exc), status)
    except LookupError:
        return _error('NOT_FOUND', 'security not found', HTTP_404_NOT_FOUND)
    except Exception as exc:
        logger.exception('metrics.score.error')
        return _error('CALCULATION_FAILED', str(exc), HTTP_500_INTERNAL_SERVER_ERROR)

    feature_values = payload.pop('_feature_values', {})
    normalized_overrides = payload.pop('_normalization_overrides', {})
    include_model_topn = _parse_bool(request.query_params.get('include_model_topn')) or use_top20_dimension
    if include_model_topn:
        latest_end_date, inferred_report_type = _latest_financial_period(payload['ts_code'])
        resolved_report_type = requested_report_type or inferred_report_type
        try:
            from predictive_valuation.services.feature_provider import get_model_top_features

            top_payload = get_model_top_features(
                ts_code=payload['ts_code'],
                stock_type=payload.get('stock_type'),
                topn=store_topn,
                model_version=request.query_params.get('model_version'),
                report_type=resolved_report_type,
            )
            payload.update({
                'model_top_features': top_payload['top_features'],
                'model_version': top_payload['model_version'],
                'report_type': top_payload['report_type'],
                'requested_report_type': requested_report_type,
                'resolved_report_type': top_payload['report_type'],
                'latest_financial_end_date': latest_end_date,
                'model_scope': top_payload['model_scope'],
                'model_degraded': bool(top_payload['degraded']),
                'model_degrade_reason': top_payload['degrade_reason'],
                'score_topn': score_topn,
                'store_topn': store_topn,
            })
            if use_top20_dimension:
                rebuilt = rebuild_score(
                    payload,
                    payload['model_top_features'],
                    score_topn,
                    feature_values,
                    normalized_overrides,
                )
                payload.update(rebuilt)
                payload['ai_summary'] = '评分由模型 TopN 特征映射至六维后生成。'
            else:
                attach_feature_hints(payload, payload['model_top_features'])
        except Exception as exc:
            logger.warning(
                'metrics.score.model_topn_unavailable',
                extra={'event': 'metrics.score.model_topn_unavailable', 'ts_code': payload['ts_code'], 'error': str(exc)},
            )
            payload.update({
                'model_top_features': [],
                'model_version': '',
                'report_type': '',
                'requested_report_type': requested_report_type,
                'resolved_report_type': resolved_report_type,
                'latest_financial_end_date': latest_end_date,
                'model_scope': '',
                'model_degraded': True,
                'model_degrade_reason': str(exc),
                'score_topn': score_topn,
                'store_topn': store_topn,
            })
            if not use_top20_dimension:
                attach_feature_hints(payload, [])
    return Response(payload, status=HTTP_200_OK)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def return_spread(request):
    raw_code = request.query_params.get('ts_code')
    if not raw_code:
        return _error('INVALID_PARAM', 'ts_code is required', HTTP_400_BAD_REQUEST)
    try:
        ts_code = normalize_ts_code(str(raw_code))
    except ValueError as exc:
        return _error('INVALID_PARAM', str(exc), HTTP_400_BAD_REQUEST)
    period = (request.query_params.get('period') or '1Y').strip().upper()
    if period not in RETURN_SPREAD_PERIOD_DAYS:
        return _error('INVALID_PARAM', 'period is invalid', HTTP_400_BAD_REQUEST)
    benchmark = (request.query_params.get('benchmark') or 'hs300').strip().lower()
    benchmark_info = RETURN_SPREAD_BENCHMARKS.get(benchmark)
    if not benchmark_info:
        return _error('INVALID_PARAM', 'benchmark is invalid', HTTP_400_BAD_REQUEST)
    requested_asof = _parse_date(request.query_params.get('asof_date'))
    if request.query_params.get('asof_date') and requested_asof is None:
        return _error('INVALID_PARAM', 'asof_date is invalid, expected YYYYMMDD', HTTP_400_BAD_REQUEST)

    stock_security = Security.objects.filter(ts_code=ts_code).first()
    if not stock_security:
        return _error('NOT_FOUND', 'security not found', HTTP_404_NOT_FOUND)
    latest_date = MarketBarDailyHistory.objects.filter(security=stock_security).order_by('-trade_date').values_list('trade_date', flat=True).first()
    if latest_date is None:
        return _error('NOT_FOUND', 'security not found', HTTP_404_NOT_FOUND)
    asof = min(requested_asof or latest_date, latest_date)
    start_date = asof - timedelta(days=RETURN_SPREAD_PERIOD_DAYS[period])

    def rows_for(security):
        return list(MarketBarDailyHistory.objects.filter(
            security=security, trade_date__gte=start_date, trade_date__lte=asof,
        ).order_by('trade_date').values('trade_date', 'pct_change', 'close', 'pre_close'))

    stock_rows = rows_for(stock_security)
    benchmark_security = Security.objects.filter(ts_code=benchmark_info['ts_code']).first()
    benchmark_rows = rows_for(benchmark_security) if benchmark_security else []
    if not stock_rows:
        return _error('INSUFFICIENT_DATA', 'stock series is empty in requested range', HTTP_422_UNPROCESSABLE_ENTITY)
    if not benchmark_rows:
        return _error('BENCHMARK_DATA_NOT_READY', 'benchmark daily series is not ready', HTTP_503_SERVICE_UNAVAILABLE, {'benchmark': benchmark, 'benchmark_ts_code': benchmark_info['ts_code']})

    stock_cum = _cumulative_returns(stock_rows)
    benchmark_cum = _cumulative_returns(benchmark_rows)
    dates = sorted(set(stock_cum) & set(benchmark_cum))
    if len(dates) < 20:
        return _error('INSUFFICIENT_DATA', 'not enough overlapping trading days', HTTP_422_UNPROCESSABLE_ENTITY, {'overlap_days': len(dates)})
    stock_series = [round(stock_cum[day], 4) for day in dates]
    benchmark_series = [round(benchmark_cum[day], 4) for day in dates]
    spread = [round(stock - index, 4) for stock, index in zip(stock_series, benchmark_series)]
    name, _ = _stock_meta(ts_code)
    return Response({
        'ts_code': ts_code,
        'stock_name': name,
        'benchmark': benchmark,
        'benchmark_name': benchmark_info['name'],
        'benchmark_ts_code': benchmark_info['ts_code'],
        'period': period,
        'asof_date': dates[-1].strftime('%Y%m%d'),
        'start_date': dates[0].strftime('%Y%m%d'),
        'end_date': dates[-1].strftime('%Y%m%d'),
        'series': {
            'dates': [day.isoformat() for day in dates],
            'stock_cum_return': stock_series,
            'benchmark_cum_return': benchmark_series,
            'spread_return': spread,
        },
        'stats': {
            'stock_total_return': stock_series[-1],
            'benchmark_total_return': benchmark_series[-1],
            'spread_total_return': spread[-1],
            'spread_max': max(spread),
            'spread_min': min(spread),
            'spread_latest': spread[-1],
        },
    }, status=HTTP_200_OK)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def health_report(_request, ts_code: str):
    try:
        payload = compute_score(ts_code)
    except ValueError as exc:
        return _error('DATA_INSUFFICIENT', str(exc), HTTP_422_UNPROCESSABLE_ENTITY)
    except LookupError:
        return _error('NOT_FOUND', 'security not found', HTTP_404_NOT_FOUND)
    return Response({'ts_code': payload['ts_code'], 'health': {'score': payload['total_score'], 'grade': payload['score_grade'], 'dimensions': payload['dimension_scores'], 'risk_flags': payload['risk_flags']}}, status=HTTP_200_OK)


@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def index_cards(request):
    asof_date = _parse_date(request.query_params.get('asof_date'))
    if asof_date is None:
        asof_date = MarketBarDailyHistory.objects.order_by('-trade_date').values_list('trade_date', flat=True).first() or date.today()

    valuation_items = []
    valuation_percentiles = []
    for label, ts_code in (('上证', '000001.SH'), ('深证', '399001.SZ'), ('沪深300', '000300.SH')):
        security = Security.objects.filter(ts_code=ts_code).first()
        if not security:
            valuation_items.append({'metric': label, 'value': None, 'percentile': None, 'percentile_text': '--', 'history_median': None, 'status': 'unknown'})
            continue
        history = list(IndexDailyFundamentalHistory.objects.filter(
            security=security, trade_date__lte=asof_date,
        ).order_by('-trade_date').values_list('pe_ttm', flat=True)[:2520])
        latest = next((float(value) for value in history if value is not None and float(value) > 0), None)
        valid = sorted(float(value) for value in history if value is not None and float(value) > 0)
        percentile = sum(value <= latest for value in valid) / len(valid) if valid and latest is not None else None
        if percentile is not None:
            valuation_percentiles.append(percentile)
        valuation_items.append({
            'metric': label,
            'value': round(latest, 2) if latest is not None else None,
            'percentile': percentile,
            'percentile_text': f'{round(percentile * 100):.0f}%' if percentile is not None else '--',
            'history_median': round(valid[len(valid) // 2], 2) if valid else None,
            'status': 'low' if percentile is not None and percentile <= 0.33 else 'mid' if percentile is not None and percentile <= 0.67 else 'high' if percentile is not None else 'unknown',
        })

    benchmark = Security.objects.filter(ts_code='000300.SH').first()
    bars = list(MarketBarDailyHistory.objects.filter(
        security=benchmark, trade_date__lte=asof_date,
    ).order_by('-trade_date').values('trade_date', 'high', 'low', 'pre_close', 'close')[:260]) if benchmark else []
    bars.reverse()
    atr_values = []
    true_ranges = []
    for bar in bars:
        high, low = _number_or_none(bar['high']), _number_or_none(bar['low'])
        previous, close = _number_or_none(bar['pre_close']), _number_or_none(bar['close'])
        if None in (high, low, previous, close) or close <= 0:
            continue
        true_ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
        if len(true_ranges) >= 14:
            atr_values.append(sum(true_ranges[-14:]) / 14 / close * 100.0)
    latest_atr = atr_values[-1] if atr_values else None
    sorted_atr = sorted(atr_values)
    atr_percentile = sum(value <= latest_atr for value in sorted_atr) / len(sorted_atr) if sorted_atr and latest_atr is not None else None
    change_5d = latest_atr - atr_values[-6] if len(atr_values) > 5 else None
    change_20d = latest_atr - atr_values[-21] if len(atr_values) > 20 else None
    slope_5d = change_5d / 5 if change_5d is not None else None
    slope_20d = change_20d / 20 if change_20d is not None else None
    zone = 'low' if atr_percentile is not None and atr_percentile <= 0.33 else 'mid' if atr_percentile is not None and atr_percentile <= 0.67 else 'high' if atr_percentile is not None else 'unknown'
    trend = 'up' if slope_5d is not None and slope_20d is not None and slope_5d > 0 and slope_20d > 0 else 'down' if slope_5d is not None and slope_20d is not None and slope_5d < 0 and slope_20d < 0 else 'flat' if slope_5d is not None and slope_20d is not None else 'unknown'

    monday = asof_date - timedelta(days=asof_date.weekday())
    calendar_end = monday + timedelta(days=27)
    event_rows = FinancialDisclosureRecord.objects.filter(
        Q(actual_date__range=(monday, calendar_end))
        | Q(actual_date__isnull=True, ann_date__range=(monday, calendar_end))
    ).values('security__ts_code', 'end_date', 'actual_date', 'ann_date')
    event_dates: dict[tuple[str, date | None], date] = {}
    for event in event_rows:
        event_date = event['actual_date'] or event['ann_date']
        if event_date:
            key = (event['security__ts_code'], event['end_date'])
            event_dates[key] = max(event_date, event_dates.get(key, event_date))
    weeks = []
    peak_week = None
    for week_index in range(2):
        start = monday + timedelta(days=week_index * 7)
        end = start + timedelta(days=6)
        count = sum(1 for event_date in event_dates.values() if start <= event_date <= end)
        label = '本周' if week_index == 0 else '下周'
        weeks.append({'week': label, 'date_range': f'{start.isoformat()}~{end.isoformat()}', 'count': count, 'is_current': week_index == 0})
        if peak_week is None or count > weeks[0]['count']:
            peak_week = label

    return Response({
        'ok': True,
        'asof_date': asof_date.isoformat(),
        'cards': {
            'valuation': {
                'title': '大盘估值分位',
                'subtitle': '近10年 PE 分位',
                'items': valuation_items,
                'summary': '当前处于历史低位区间' if valuation_percentiles and sum(valuation_percentiles) / len(valuation_percentiles) <= 0.33 else '当前处于历史中位区间' if valuation_percentiles and sum(valuation_percentiles) / len(valuation_percentiles) <= 0.67 else '当前处于历史高位区间' if valuation_percentiles else '暂无可用样本',
            },
            'volatility': {
                'title': '市场波动率',
                'subtitle': 'ATR14%（沪深300）',
                'value': round(latest_atr, 2) if latest_atr is not None else None,
                'unit': '%',
                'percentile': atr_percentile,
                'change_wow': round(change_5d, 2) if change_5d is not None else None,
                'change_mom': round(change_20d, 2) if change_20d is not None else None,
                'zone': zone,
                'trend_direction': trend,
                'trend_strength': 'strong' if slope_5d is not None and abs(slope_5d) >= 0.12 else 'medium' if slope_5d is not None and abs(slope_5d) >= 0.05 else 'weak' if slope_5d is not None else 'unknown',
                'slope_5d': round(slope_5d, 4) if slope_5d is not None else None,
                'slope_20d': round(slope_20d, 4) if slope_20d is not None else None,
                'accel_5d': round(slope_5d - slope_20d, 4) if slope_5d is not None and slope_20d is not None else None,
                'pct_change_5d': round(change_5d / atr_values[-6] * 100, 2) if change_5d is not None and atr_values[-6] else None,
                'pct_change_20d': round(change_20d / atr_values[-21] * 100, 2) if change_20d is not None and atr_values[-21] else None,
                'action_hint': '波动数据有限，建议先观察并控制仓位。' if latest_atr is None else '',
            },
            'industry_flow': {
                'title': '板块资金流向',
                'subtitle': '近30天净流入排行',
                'window': '30d',
                'items': [],
                'summary': '目标项目尚未接入板块资金流数据',
            },
            'earnings_calendar': {
                'title': '财报季日历',
                'subtitle': '本周与下周披露统计',
                'weeks': weeks,
                'peak_week': peak_week,
            },
        },
    }, status=HTTP_200_OK)
