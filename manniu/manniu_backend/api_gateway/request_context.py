import uuid


REQUEST_ID_HEADER = 'X-Request-ID'


def get_request_id(request):
    request_id = getattr(request, 'request_id', None)
    if request_id:
        return request_id
    request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
    request.request_id = request_id
    return request_id
