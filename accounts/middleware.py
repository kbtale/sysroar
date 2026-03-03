import threading
from django.core.exceptions import DisallowedHost

_thread_locals = threading.local()

def get_current_company_id():
    """
    Retrieves the company ID associated with the current thread.
    Returns None if no company is associated (e.g., system tasks or unauthenticated requests).
    """
    return getattr(_thread_locals, 'company_id', None)

class CurrentTenantMiddleware:
    """
    Middleware that extracts the company_id from the authenticated user
    and stores it in thread-local storage for use by the TenantManager.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if hasattr(request, 'user') and request.user.is_authenticated:
            if getattr(request.user, 'company_id', None):
                _thread_locals.company_id = request.user.company_id
        
        try:
            return self.get_response(request)
        finally:
            if hasattr(_thread_locals, 'company_id'):
                del _thread_locals.company_id
