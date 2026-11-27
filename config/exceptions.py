import logging
from django.conf import settings
from django_redis import get_redis_connection
from rest_framework.exceptions import AuthenticationFailed, NotAuthenticated
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


def _should_record_failed_auth(ip_address: str, path: str) -> tuple[bool, int]:
    window_seconds = int(getattr(settings, 'FAILED_AUTH_DEDUP_WINDOW_SECONDS', 60))
    sample_every = max(int(getattr(settings, 'FAILED_AUTH_SAMPLE_EVERY', 50)), 1)
    if window_seconds <= 0:
        return True, 1

    key = f'sysroar:auth_fail:{ip_address}:{path[:128]}'
    try:
        con = get_redis_connection('default')
        count = int(con.incr(key))
        if count == 1:
            con.expire(key, window_seconds)
        should_record = count == 1 or (count % sample_every == 0)
        return should_record, count
    except Exception:
        return True, 1


def custom_exception_handler(exc, context):
    from monitoring.tasks import record_system_event

    response = exception_handler(exc, context)

    if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
        view = context.get('view')
        request = getattr(view, 'request', None) if view is not None else context.get('request')
        user_agent = request.META.get('HTTP_USER_AGENT', 'unknown')[:256] if request else 'unknown'
        ip_address = request.META.get('REMOTE_ADDR', 'unknown') if request else 'unknown'
        method = getattr(request, 'method', 'UNKNOWN') if request else 'UNKNOWN'
        path = getattr(request, 'path', '') if request else ''

        should_record, count = _should_record_failed_auth(ip_address, path)
        if should_record:
            logger.warning(
                f'FAILED_AUTHENTICATION | Method: {method} | Path: {path} | '
                f'IP: {ip_address} | Count: {count} | Error: {str(exc)}'
            )
            record_system_event.delay(
                event_type='FAILED_AUTHENTICATION',
                severity='ERROR',
                context={
                    'method': method,
                    'path': path,
                    'ip_address': ip_address,
                    'user_agent': user_agent,
                    'error': str(exc),
                    'window_count': count,
                },
            )

    return response
