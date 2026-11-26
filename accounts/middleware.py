from contextvars import ContextVar
from django.contrib.auth import logout

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
            if hasattr(request, 'session'):
                stored_epoch = request.session.get('session_epoch')
                user_epoch = getattr(request.user, 'session_epoch', None)
                if stored_epoch is not None and user_epoch is not None and stored_epoch != user_epoch:
                    logout(request)
            if request.user.is_authenticated:
                company_id = getattr(request.user, 'company_id', None)
        token = set_current_company_id(company_id)
        try:
            return self.get_response(request)
        finally:
            reset_current_company_id(token)
