from .request_context import REQUEST_ID_HEADER, get_request_id


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        get_request_id(request)
        response = self.get_response(request)
        response[REQUEST_ID_HEADER] = request.request_id
        return response
