from django.http import JsonResponse

from .request_context import get_request_id


API_VERSION = 'v1'


def error_payload(code, message, *, retryable=False, details=None):
    return {
        'code': code,
        'message': message,
        'details': details or {},
        'retryable': retryable,
    }


def api_response(request, *, data=None, meta=None, error=None, status=200):
    payload = {
        'success': error is None,
        'api_version': API_VERSION,
        'request_id': get_request_id(request),
    }
    if error is None:
        payload['data'] = data
        if meta:
            payload['meta'] = meta
    else:
        payload['error'] = error
    response = JsonResponse(payload, status=status)
    response['X-Request-ID'] = payload['request_id']
    return response


def api_error(request, code, message, *, status, retryable=False, details=None):
    return api_response(
        request,
        error=error_payload(code, message, retryable=retryable, details=details),
        status=status,
    )
