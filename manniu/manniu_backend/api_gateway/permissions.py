from functools import wraps

from manniu_auth.services.token_service import authenticate_access_token

from .errors import api_error


def require_scopes(*required_scopes):
    required = frozenset(required_scopes)

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            header = request.headers.get('Authorization', '')
            if not header.startswith('Bearer '):
                return api_error(
                    request,
                    'AUTHENTICATION_REQUIRED',
                    '需要 Bearer 认证凭证',
                    status=401,
                )
            raw_token = header[7:].strip()
            access = authenticate_access_token(raw_token) if raw_token else None
            if access is None:
                return api_error(request, 'TOKEN_INVALID', '认证凭证无效或已过期', status=401)
            granted = frozenset(access.scope_snapshot)
            if not required.issubset(granted):
                return api_error(
                    request,
                    'SCOPE_REQUIRED',
                    '缺少访问该资源所需的权限',
                    status=403,
                    details={'required_scopes': sorted(required)},
                )
            request.auth_access = access
            request.auth_scopes = sorted(granted)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
