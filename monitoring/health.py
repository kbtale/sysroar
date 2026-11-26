import logging
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django_redis import get_redis_connection
from telemetry.ingestion import get_stream_metrics

logger = logging.getLogger(__name__)


@require_http_methods(['GET', 'HEAD'])
def healthz_view(request):
    response = JsonResponse({'status': 'ok'}, status=200)
    response['Cache-Control'] = 'no-store'
    return response


@require_http_methods(['GET', 'HEAD'])
def readyz_view(request):
    db_ok = False
    redis_ok = False
    lag_ok = False

    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        db_ok = True
    except Exception:
        logger.warning('Readiness database check failed', exc_info=True)

    try:
        con = get_redis_connection('default')
        redis_ok = bool(con.ping())
    except Exception:
        con = None
        logger.warning('Readiness redis check failed', exc_info=True)

    if redis_ok and con is not None:
        try:
            stream_metrics = get_stream_metrics(con=con)
            max_lag = int(getattr(settings, 'READY_MAX_STREAM_LAG', 10000))
            lag_ok = int(stream_metrics.get('lag', 0)) <= max_lag
        except Exception:
            logger.warning('Readiness stream lag check failed', exc_info=True)

    checks = {
        'database': db_ok,
        'redis': redis_ok,
        'ingest_lag': lag_ok,
    }
    all_ok = all(checks.values())
    status_code = 200 if all_ok else 503
    payload = {
        'status': 'ready' if all_ok else 'degraded',
        'checks': checks,
    }
    response = JsonResponse(payload, status=status_code)
    response['Cache-Control'] = 'no-store'
    return response
