import json
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import wraps
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from api_gateway.permissions import authenticate_request
from market_data.models import Security
from personal_user.models import (
    HoldingPortfolio,
    HoldingPosition,
    PersonalProfile,
    UserSecurityListItem,
)


def _request_id(request):
    return request.headers.get('X-Request-ID') or str(uuid.uuid4())


def _error(code, message, details=None):
    return {'code': code, 'message': message, 'details': details or {}, 'retryable': False}


def _response(request, *, data=None, error=None, status=200):
    payload = {
        'success': error is None,
        'api_version': 'v1',
        'request_id': _request_id(request),
    }
    if error is None:
        payload['data'] = data
    else:
        payload['error'] = error
    return JsonResponse(payload, status=status)


def _body(request):
    try:
        value = json.loads(request.body or '{}')
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def authenticated(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        auth_error = authenticate_request(request)
        if auth_error is not None:
            return auth_error
        request.personal_user = request.auth_access.session.user
        return view(request, *args, **kwargs)

    return wrapped


def _method(request, methods):
    if request.method not in methods:
        return _response(request, error=_error('INVALID_REQUEST', '请求方法不支持'), status=405)
    return None


def _get_profile(user):
    profile, _ = PersonalProfile.objects.get_or_create(
        user=user,
        defaults={'display_name': getattr(user, 'first_name', '') or ''},
    )
    return profile


def _profile_data(profile):
    return {
        'id': profile.id,
        'user_id': profile.user_id,
        'username': profile.user.username,
        'display_name': profile.display_name,
        'email': profile.email,
        'email_verified_at': profile.email_verified_at,
        'mobile': profile.mobile,
        'mobile_verified_at': profile.mobile_verified_at,
        'timezone': profile.timezone,
        'avatar_url': profile.avatar_url,
        'created_at': profile.created_at,
        'updated_at': profile.updated_at,
    }


@csrf_exempt
@authenticated
def profile(request):
    invalid = _method(request, {'GET', 'PATCH'})
    if invalid:
        return invalid
    current = _get_profile(request.personal_user)
    if request.method == 'GET':
        return _response(request, data=_profile_data(current))
    body = _body(request)
    if body is None:
        return _response(request, error=_error('VALIDATION_ERROR', '请求体必须是 JSON 对象'), status=400)
    allowed = {'display_name', 'email', 'mobile', 'timezone', 'avatar_url'}
    unknown = sorted(set(body) - allowed)
    if unknown:
        return _response(request, error=_error('VALIDATION_ERROR', '包含不支持的字段', {'fields': unknown}), status=400)
    for field in allowed & body.keys():
        value = body[field]
        if value is None:
            value = ''
        if not isinstance(value, str):
            return _response(request, error=_error('VALIDATION_ERROR', f'{field} 必须是字符串'), status=400)
        setattr(current, field, value.strip())
    try:
        current.full_clean()
    except ValidationError as exc:
        return _response(request, error=_error('VALIDATION_ERROR', 'profile 字段无效', exc.message_dict), status=400)
    current.save()
    return _response(request, data=_profile_data(current))


def _security_data(security):
    return {'id': security.id, 'ts_code': security.ts_code, 'symbol': security.symbol, 'name': security.name,
            'asset_type': security.asset_type, 'list_status': security.list_status}


def _page(request, queryset):
    try:
        limit = int(request.GET.get('limit', 50))
        offset = int(request.GET.get('offset', 0))
    except (TypeError, ValueError):
        raise ValueError('limit 和 offset 必须是整数')
    if limit < 1 or limit > 100 or offset < 0:
        raise ValueError('limit 范围为 1-100，offset 不能为负数')
    total = queryset.count()
    return list(queryset[offset:offset + limit]), {
        'limit': limit,
        'offset': offset,
        'total': total,
        'has_more': offset + limit < total,
    }


def _list_data(item):
    return {
        'id': item.id,
        'list_type': item.list_type,
        'security': _security_data(item.security),
        'sort_order': item.sort_order,
        'note': item.note,
        'created_at': item.created_at,
        'updated_at': item.updated_at,
    }


def _list_error(request, message, details=None, status=400):
    return _response(request, error=_error('VALIDATION_ERROR', message, details), status=status)


def _security_from_body(body):
    security_id = body.get('security_id')
    ts_code = str(body.get('ts_code', '')).strip()
    if security_id is None and not ts_code:
        raise ValueError('security_id 或 ts_code 为必填项')
    query = {'pk': security_id} if security_id is not None else {'ts_code': ts_code}
    try:
        return Security.objects.get(**query)
    except (Security.DoesNotExist, ValueError, TypeError):
        raise LookupError('证券不存在')


def _list_view(request, list_type):
    invalid = _method(request, {'GET', 'POST'})
    if invalid:
        return invalid
    user = request.personal_user
    if request.method == 'GET':
        rows = UserSecurityListItem.objects.filter(user=user, list_type=list_type).select_related('security')
        try:
            page, pagination = _page(request, rows.order_by('sort_order', 'id'))
        except ValueError as exc:
            return _list_error(request, str(exc))
        return _response(request, data={'items': [_list_data(row) for row in page], 'pagination': pagination})
    body = _body(request)
    if body is None:
        return _list_error(request, '请求体必须是 JSON 对象')
    try:
        security = _security_from_body(body)
    except ValueError as exc:
        return _list_error(request, str(exc))
    except LookupError as exc:
        return _response(request, error=_error('SECURITY_NOT_FOUND', str(exc)), status=404)
    item, created = UserSecurityListItem.objects.get_or_create(
        user=user,
        security=security,
        list_type=list_type,
        defaults={'sort_order': body.get('sort_order', 0), 'note': str(body.get('note', ''))[:512]},
    )
    if not created:
        return _response(request, data=_list_data(item))
    return _response(request, data=_list_data(item), status=201)


def _list_item_view(request, item_id, list_type):
    invalid = _method(request, {'PATCH', 'DELETE'})
    if invalid:
        return invalid
    try:
        item = UserSecurityListItem.objects.select_related('security').get(
            pk=item_id, user=request.personal_user, list_type=list_type,
        )
    except UserSecurityListItem.DoesNotExist:
        return _response(request, error=_error('ITEM_NOT_FOUND', '列表项不存在'), status=404)
    if request.method == 'DELETE':
        item.delete()
        return _response(request, data={'deleted': True})
    body = _body(request)
    if body is None or set(body) - {'sort_order', 'note'}:
        return _list_error(request, '只允许更新 sort_order 和 note')
    if 'sort_order' in body:
        try:
            item.sort_order = int(body['sort_order'])
            if item.sort_order < 0:
                raise ValueError
        except (TypeError, ValueError):
            return _list_error(request, 'sort_order 必须是非负整数')
    if 'note' in body:
        item.note = str(body['note'])[:512]
    item.save()
    return _response(request, data=_list_data(item))


def _reorder(request, list_type):
    if request.method != 'POST':
        return _method(request, {'POST'})
    body = _body(request)
    item_ids = body.get('item_ids') if body else None
    if not isinstance(item_ids, list) or not all(isinstance(item_id, int) for item_id in item_ids):
        return _list_error(request, 'item_ids 必须是整数数组')
    if len(item_ids) != len(set(item_ids)):
        return _list_error(request, 'item_ids 必须是不重复的数组')
    with transaction.atomic():
        rows = list(UserSecurityListItem.objects.filter(
            user=request.personal_user, list_type=list_type, id__in=item_ids,
        ))
        if len(rows) != len(item_ids) or {row.id for row in rows} != set(item_ids):
            return _list_error(request, 'item_ids 必须全部属于当前用户和列表', status=400)
        by_id = {row.id: row for row in rows}
        for order, item_id in enumerate(item_ids):
            by_id[item_id].sort_order = order
            by_id[item_id].save(update_fields=['sort_order', 'updated_at'])
    return _response(request, data={'updated': len(item_ids)})


@csrf_exempt
@authenticated
def watchlist(request):
    return _list_view(request, UserSecurityListItem.ListType.WATCHLIST)


@csrf_exempt
@authenticated
def watchlist_item(request, item_id):
    return _list_item_view(request, item_id, UserSecurityListItem.ListType.WATCHLIST)


@csrf_exempt
@authenticated
def watchlist_reorder(request):
    return _reorder(request, UserSecurityListItem.ListType.WATCHLIST)


@csrf_exempt
@authenticated
def observations(request):
    return _list_view(request, UserSecurityListItem.ListType.OBSERVATION)


@csrf_exempt
@authenticated
def observation_item(request, item_id):
    return _list_item_view(request, item_id, UserSecurityListItem.ListType.OBSERVATION)


@csrf_exempt
@authenticated
def observation_reorder(request):
    return _reorder(request, UserSecurityListItem.ListType.OBSERVATION)


def _portfolio_data(portfolio, include_positions=False):
    data = {
        'id': portfolio.id,
        'name': portfolio.name,
        'description': portfolio.description,
        'is_default': portfolio.is_default,
        'sort_order': portfolio.sort_order,
        'archived_at': portfolio.archived_at,
        'created_at': portfolio.created_at,
        'updated_at': portfolio.updated_at,
    }
    if include_positions:
        data['positions'] = [_position_data(row) for row in portfolio.positions.select_related('security').order_by('id')]
    return data


def _position_data(position):
    return {
        'id': position.id,
        'portfolio_id': position.portfolio_id,
        'security': _security_data(position.security),
        'quantity': str(position.quantity),
        'available_quantity': str(position.available_quantity),
        'average_cost': str(position.average_cost),
        'cost_currency': position.cost_currency,
        'note': position.note,
        'as_of_date': position.as_of_date,
        'created_at': position.created_at,
        'updated_at': position.updated_at,
    }


def _portfolio_name(name):
    return str(name or '').strip()[:128]


def _ensure_default_portfolio(user):
    portfolio = HoldingPortfolio.objects.filter(user=user, archived_at__isnull=True).order_by('is_default', 'id').first()
    if portfolio:
        return portfolio
    return HoldingPortfolio.objects.create(user=user, name='默认组合', is_default=True)


@csrf_exempt
@authenticated
def portfolios(request):
    invalid = _method(request, {'GET', 'POST'})
    if invalid:
        return invalid
    if request.method == 'GET':
        rows = HoldingPortfolio.objects.filter(user=request.personal_user).order_by('sort_order', 'id')
        try:
            page, pagination = _page(request, rows)
        except ValueError as exc:
            return _response(request, error=_error('VALIDATION_ERROR', str(exc)), status=400)
        return _response(request, data={'items': [_portfolio_data(row) for row in page], 'pagination': pagination})
    body = _body(request)
    name = _portfolio_name(body.get('name') if body else '')
    if not name:
        return _response(request, error=_error('VALIDATION_ERROR', 'name 为必填项'), status=400)
    if HoldingPortfolio.objects.filter(user=request.personal_user, name=name).exists():
        return _response(request, error=_error('DUPLICATE_RELATION', '组合名称已存在'), status=409)
    is_default = bool(body.get('is_default', False))
    with transaction.atomic():
        if is_default:
            HoldingPortfolio.objects.filter(user=request.personal_user, is_default=True).update(is_default=False)
        portfolio = HoldingPortfolio.objects.create(
            user=request.personal_user,
            name=name,
            description=str(body.get('description', ''))[:512],
            is_default=is_default,
            sort_order=body.get('sort_order', 0),
        )
    return _response(request, data=_portfolio_data(portfolio), status=201)


@csrf_exempt
@authenticated
def portfolio_detail(request, portfolio_id):
    invalid = _method(request, {'GET', 'PATCH', 'DELETE'})
    if invalid:
        return invalid
    try:
        portfolio = HoldingPortfolio.objects.get(pk=portfolio_id, user=request.personal_user)
    except HoldingPortfolio.DoesNotExist:
        return _response(request, error=_error('PORTFOLIO_NOT_FOUND', '组合不存在'), status=404)
    if request.method == 'GET':
        return _response(request, data=_portfolio_data(portfolio, include_positions=True))
    if request.method == 'DELETE':
        if portfolio.is_default and not HoldingPortfolio.objects.filter(
            user=request.personal_user, archived_at__isnull=True,
        ).exclude(pk=portfolio.pk).exists():
            return _response(request, error=_error('VALIDATION_ERROR', '唯一默认组合不能删除'), status=400)
        portfolio.archived_at = timezone.now()
        portfolio.save(update_fields=['archived_at', 'updated_at'])
        return _response(request, data={'archived': True})
    body = _body(request)
    if body is None or set(body) - {'name', 'description', 'is_default', 'sort_order'}:
        return _response(request, error=_error('VALIDATION_ERROR', '包含不支持的组合字段'), status=400)
    if portfolio.archived_at and any(field in body for field in ('name', 'description', 'is_default', 'sort_order')):
        return _response(request, error=_error('VALIDATION_ERROR', '已归档组合不可修改'), status=400)
    if 'name' in body:
        name = _portfolio_name(body['name'])
        if not name:
            return _response(request, error=_error('VALIDATION_ERROR', 'name 不能为空'), status=400)
        if HoldingPortfolio.objects.filter(user=request.personal_user, name=name).exclude(pk=portfolio.pk).exists():
            return _response(request, error=_error('DUPLICATE_RELATION', '组合名称已存在'), status=409)
        portfolio.name = name
    if 'description' in body:
        portfolio.description = str(body['description'])[:512]
    if 'sort_order' in body:
        try:
            portfolio.sort_order = int(body['sort_order'])
            if portfolio.sort_order < 0:
                raise ValueError
        except (TypeError, ValueError):
            return _response(request, error=_error('VALIDATION_ERROR', 'sort_order 必须是非负整数'), status=400)
    with transaction.atomic():
        if body.get('is_default') is True:
            HoldingPortfolio.objects.filter(user=request.personal_user, is_default=True).exclude(pk=portfolio.pk).update(
                is_default=False,
            )
            portfolio.is_default = True
        portfolio.save()
    return _response(request, data=_portfolio_data(portfolio))


@csrf_exempt
@authenticated
def portfolio_reorder(request):
    if request.method != 'POST':
        return _method(request, {'POST'})
    body = _body(request)
    portfolio_ids = body.get('portfolio_ids') if body else None
    if not isinstance(portfolio_ids, list) or not all(isinstance(item_id, int) for item_id in portfolio_ids):
        return _response(request, error=_error('VALIDATION_ERROR', 'portfolio_ids 必须是整数数组'), status=400)
    if len(portfolio_ids) != len(set(portfolio_ids)):
        return _response(request, error=_error('VALIDATION_ERROR', 'portfolio_ids 必须是不重复的数组'), status=400)
    with transaction.atomic():
        rows = list(HoldingPortfolio.objects.filter(user=request.personal_user, id__in=portfolio_ids))
        if len(rows) != len(portfolio_ids) or {row.id for row in rows} != set(portfolio_ids):
            return _response(request, error=_error('VALIDATION_ERROR', 'portfolio_ids 必须全部属于当前用户'), status=400)
        by_id = {row.id: row for row in rows}
        for order, portfolio_id in enumerate(portfolio_ids):
            by_id[portfolio_id].sort_order = order
            by_id[portfolio_id].save(update_fields=['sort_order', 'updated_at'])
    return _response(request, data={'updated': len(portfolio_ids)})


def _decimal(value, field, places):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{field} 必须是数字')
    if number < 0 or number.as_tuple().exponent < -places:
        raise ValueError(f'{field} 数值无效')
    return number


def _position_values(body, existing=None):
    source = {
        'quantity': existing.quantity if existing else None,
        'available_quantity': existing.available_quantity if existing else None,
        'average_cost': existing.average_cost if existing else None,
        'cost_currency': existing.cost_currency if existing else 'CNY',
        'note': existing.note if existing else '',
        'as_of_date': existing.as_of_date if existing else None,
    }
    source.update(body)
    for required in ('quantity', 'available_quantity', 'average_cost', 'as_of_date'):
        if source[required] is None:
            raise ValueError(f'{required} 为必填项')
    quantity = _decimal(source['quantity'], 'quantity', 4)
    available = _decimal(source['available_quantity'], 'available_quantity', 4)
    average_cost = _decimal(source['average_cost'], 'average_cost', 6)
    if available > quantity:
        raise ValueError('available_quantity 不能大于 quantity')
    try:
        as_of_date = date.fromisoformat(str(source['as_of_date']))
    except (TypeError, ValueError):
        raise ValueError('as_of_date 必须是 YYYY-MM-DD')
    currency = str(source['cost_currency'] or 'CNY').upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError('cost_currency 必须是 3 位货币代码')
    return {
        'quantity': quantity,
        'available_quantity': available,
        'average_cost': average_cost,
        'cost_currency': currency,
        'note': str(source['note'] or '')[:512],
        'as_of_date': as_of_date,
    }


@csrf_exempt
@authenticated
def positions(request, portfolio_id):
    invalid = _method(request, {'GET', 'POST'})
    if invalid:
        return invalid
    try:
        portfolio = HoldingPortfolio.objects.get(pk=portfolio_id, user=request.personal_user)
    except HoldingPortfolio.DoesNotExist:
        return _response(request, error=_error('PORTFOLIO_NOT_FOUND', '组合不存在'), status=404)
    if request.method == 'GET':
        rows = portfolio.positions.select_related('security').order_by('id')
        try:
            page, pagination = _page(request, rows)
        except ValueError as exc:
            return _response(request, error=_error('VALIDATION_ERROR', str(exc)), status=400)
        return _response(request, data={'items': [_position_data(row) for row in page], 'pagination': pagination})
    if portfolio.archived_at:
        return _response(request, error=_error('VALIDATION_ERROR', '已归档组合不可新增持仓'), status=400)
    body = _body(request)
    if body is None:
        return _response(request, error=_error('VALIDATION_ERROR', '请求体必须是 JSON 对象'), status=400)
    try:
        security = _security_from_body(body)
        values = _position_values(body)
    except ValueError as exc:
        return _response(request, error=_error('VALIDATION_ERROR', str(exc)), status=400)
    except LookupError as exc:
        return _response(request, error=_error('SECURITY_NOT_FOUND', str(exc)), status=404)
    position, created = HoldingPosition.objects.update_or_create(
        portfolio=portfolio,
        security=security,
        defaults={'user': request.personal_user, **values},
    )
    position = HoldingPosition.objects.select_related('security').get(pk=position.pk)
    return _response(request, data=_position_data(position), status=201 if created else 200)


@csrf_exempt
@authenticated
def position_detail(request, portfolio_id, position_id):
    invalid = _method(request, {'PATCH', 'DELETE'})
    if invalid:
        return invalid
    try:
        position = HoldingPosition.objects.select_related('security', 'portfolio').get(
            pk=position_id, portfolio_id=portfolio_id, user=request.personal_user,
        )
    except HoldingPosition.DoesNotExist:
        return _response(request, error=_error('ITEM_NOT_FOUND', '持仓不存在'), status=404)
    if position.portfolio.archived_at:
        return _response(request, error=_error('VALIDATION_ERROR', '已归档组合不可修改持仓'), status=400)
    if request.method == 'DELETE':
        position.delete()
        return _response(request, data={'deleted': True})
    body = _body(request)
    if body is None or set(body) - {'quantity', 'available_quantity', 'average_cost', 'cost_currency', 'note', 'as_of_date'}:
        return _response(request, error=_error('VALIDATION_ERROR', '包含不支持的持仓字段'), status=400)
    try:
        values = _position_values(body, existing=position)
    except ValueError as exc:
        return _response(request, error=_error('VALIDATION_ERROR', str(exc)), status=400)
    for field, value in values.items():
        setattr(position, field, value)
    position.save()
    return _response(request, data=_position_data(position))