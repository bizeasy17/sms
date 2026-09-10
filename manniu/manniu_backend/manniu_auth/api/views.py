import json
import uuid
from datetime import timedelta

from django.contrib.auth import authenticate, update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from manniu_auth.models import AuthProfile, AuthSession
from manniu_auth.services.audit import record_event
from manniu_auth.services.authentication import get_profile, login_user, logout_session
from manniu_auth.services.authorization import user_scopes
from manniu_auth.services.token_service import authenticate_access_token, revoke_session, rotate_refresh_token


def _request_id(request):
    return request.headers.get('X-Request-ID') or str(uuid.uuid4())


def _response(request, *, data=None, error=None, status=200):
    payload = {
        'success': error is None,
        'api_version': 'v1',
        'request_id': _request_id(request),
    }
    if error is not None:
        payload['error'] = error
    else:
        payload['data'] = data
    return JsonResponse(payload, status=status)


def _error(code, message, retryable=False, details=None):
    return {'code': code, 'message': message, 'details': details or {}, 'retryable': retryable}


def _json_body(request):
    try:
        return json.loads(request.body or '{}')
    except (TypeError, ValueError):
        return None


def _auth_context(request):
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer '):
        return None
    raw_token = header[7:].strip()
    if not raw_token:
        return None
    access = authenticate_access_token(raw_token)
    if access is None:
        return None
    request.auth_access = access
    return access


def _token_data(session, scopes, access, refresh, access_raw, refresh_raw):
    return {
        'access_token': access_raw,
        'token_type': 'Bearer',
        'expires_in': max(0, int((access.expires_at - timezone.now()).total_seconds())),
        'refresh_token': refresh_raw,
        'refresh_expires_in': max(0, int((refresh.expires_at - timezone.now()).total_seconds())),
        'session_id': str(session.id),
        'user': {
            'id': session.user.id,
            'username': session.user.username,
            'display_name': get_profile(session.user).display_name,
            'scopes': scopes,
        },
    }


@csrf_exempt
def login(request):
    if request.method != 'POST':
        return _response(request, error=_error('INVALID_REQUEST', '仅支持 POST'), status=405)
    body = _json_body(request)
    if not isinstance(body, dict) or not body.get('username') or not body.get('password'):
        return _response(request, error=_error('INVALID_REQUEST', 'username 和 password 为必填项'), status=400)
    client_type = body.get('client_type', AuthSession.ClientType.WEB)
    if client_type not in AuthSession.ClientType.values:
        return _response(request, error=_error('INVALID_REQUEST', 'client_type 无效'), status=400)
    result = login_user(
        username=str(body['username']).strip(),
        password=body['password'],
        client_type=client_type,
        device_name=str(body.get('device_name', ''))[:128],
        request=request,
    )
    if result is None:
        return _response(request, error=_error('AUTHENTICATION_FAILED', '用户名或密码错误'), status=401)
    session, scopes, access_raw, refresh_raw, access, refresh = result
    return _response(
        request,
        data=_token_data(session, scopes, access, refresh, access_raw, refresh_raw),
    )


@csrf_exempt
def refresh(request):
    if request.method != 'POST':
        return _response(request, error=_error('INVALID_REQUEST', '仅支持 POST'), status=405)
    body = _json_body(request)
    raw_token = body.get('refresh_token') if isinstance(body, dict) else None
    if not raw_token:
        return _response(request, error=_error('INVALID_REQUEST', 'refresh_token 为必填项'), status=400)
    result, reason = rotate_refresh_token(raw_token)
    if result is None:
        code = 'REFRESH_TOKEN_REUSED' if reason == 'reused' else 'TOKEN_INVALID'
        return _response(request, error=_error(code, 'refresh token 无效或已使用'), status=401)
    access_raw, refresh_raw, access, new_refresh = result
    session = access.session
    scopes = access.scope_snapshot
    record_event('TOKEN_REFRESHED', user=session.user, session=session, request=request)
    return _response(request, data=_token_data(session, scopes, access, new_refresh, access_raw, refresh_raw))


def me(request):
    access = _auth_context(request)
    if access is None:
        return _response(request, error=_error('AUTHENTICATION_REQUIRED', '需要有效的 Bearer token'), status=401)
    profile = get_profile(access.session.user)
    return _response(request, data={
        'id': access.session.user.id,
        'username': access.session.user.username,
        'display_name': profile.display_name,
        'status': profile.status,
        'scopes': access.scope_snapshot,
        'session': {
            'id': str(access.session.id),
            'client_type': access.session.client_type,
            'created_at': access.session.created_at.isoformat(),
            'expires_at': access.session.expires_at.isoformat(),
        },
    })


def sessions(request):
    if request.method != 'GET':
        return _response(request, error=_error('INVALID_REQUEST', '仅支持 GET'), status=405)
    access = _auth_context(request)
    if access is None:
        return _response(request, error=_error('AUTHENTICATION_REQUIRED', '需要有效的 Bearer token'), status=401)
    if 'auth:session_read' not in access.scope_snapshot:
        return _response(request, error=_error('SCOPE_REQUIRED', '缺少 auth:session_read'), status=403)
    now = timezone.now()
    rows = AuthSession.objects.filter(user=access.session.user, expires_at__gt=now).order_by('-created_at')
    return _response(request, data=[{
        'id': str(row.id),
        'client_type': row.client_type,
        'device_name': row.device_name,
        'created_at': row.created_at,
        'last_seen_at': row.last_seen_at,
        'expires_at': row.expires_at,
        'revoked_at': row.revoked_at,
    } for row in rows])


def revoke_session(request, session_id):
    if request.method != 'DELETE':
        return _response(request, error=_error('INVALID_REQUEST', '仅支持 DELETE'), status=405)
    access = _auth_context(request)
    if access is None:
        return _response(request, error=_error('AUTHENTICATION_REQUIRED', '需要有效的 Bearer token'), status=401)
    if 'auth:session_revoke' not in access.scope_snapshot:
        return _response(request, error=_error('SCOPE_REQUIRED', '缺少 auth:session_revoke'), status=403)
    try:
        target = AuthSession.objects.get(pk=session_id, user=access.session.user)
    except (AuthSession.DoesNotExist, ValueError):
        return _response(request, data={'revoked': True})
    logout_session(target, request=request)
    return _response(request, data={'revoked': True})


def logout(request):
    if request.method != 'POST':
        return _response(request, error=_error('INVALID_REQUEST', '仅支持 POST'), status=405)
    access = _auth_context(request)
    if access is not None:
        logout_session(access.session, request=request)
    return _response(request, data={'logged_out': True})


def change_password(request):
    if request.method != 'POST':
        return _response(request, error=_error('INVALID_REQUEST', '仅支持 POST'), status=405)
    access = _auth_context(request)
    if access is None:
        return _response(request, error=_error('AUTHENTICATION_REQUIRED', '需要有效的 Bearer token'), status=401)
    body = _json_body(request)
    if not isinstance(body, dict) or not body.get('current_password') or not body.get('new_password'):
        return _response(request, error=_error('INVALID_REQUEST', 'current_password 和 new_password 为必填项'), status=400)
    user = access.session.user
    if authenticate(username=user.username, password=body['current_password']) is None:
        return _response(request, error=_error('AUTHENTICATION_FAILED', '当前密码错误'), status=401)
    try:
        validate_password(body['new_password'], user=user)
    except ValidationError as exc:
        return _response(request, error=_error('INVALID_REQUEST', '新密码不符合密码策略', details={'messages': exc.messages}), status=400)
    with transaction.atomic():
        user.set_password(body['new_password'])
        user.save(update_fields=['password'])
        profile = get_profile(user)
        profile.last_password_changed_at = timezone.now()
        profile.save(update_fields=['last_password_changed_at', 'updated_at'])
        other_sessions = AuthSession.objects.filter(user=user, revoked_at__isnull=True).exclude(pk=access.session_id)
        for session in other_sessions:
            revoke_session(session, 'password_changed')
        record_event('PASSWORD_CHANGED', user=user, session=access.session, request=request)
    update_session_auth_hash(request, user)
    return _response(request, data={'password_changed': True})
