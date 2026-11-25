from contextvars import ContextVar

_current_company_id = ContextVar('current_company_id', default=None)


def get_current_company_id():
    return _current_company_id.get()


def set_current_company_id(company_id):
    return _current_company_id.set(company_id)


def reset_current_company_id(token):
    _current_company_id.reset(token)


class CurrentTenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        company_id = None
        if hasattr(request, 'user') and request.user.is_authenticated:
            company_id = getattr(request.user, 'company_id', None)
        token = set_current_company_id(company_id)
        try:
            return self.get_response(request)
        finally:
            reset_current_company_id(token)
