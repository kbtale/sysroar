import logging
from rest_framework.views import exception_handler
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated

logger = logging.getLogger(__name__)

def custom_exception_handler(exc, context):
    """
    Custom exception handler for Django REST Framework.
    Logs FAILED_AUTHENTICATION events for observability.
    """
    # Call DRF's default exception handler first to get the standard response
    response = exception_handler(exc, context)

    if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
        request = context.get('view').request
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')
        ip_address = request.META.get('REMOTE_ADDR', 'unknown')
        method = request.method
        path = request.path
        
        # Log the authentication failure with metadata
        logger.error(
            f"FAILED_AUTHENTICATION | Method: {method} | Path: {path} | "
            f"IP: {ip_address} | User-Agent: {user_agent} | Error: {str(exc)}"
        )

    return response
