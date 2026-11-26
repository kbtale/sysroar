import hmac
import logging
from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.http import require_http_methods
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from telemetry.ingestion import get_stream_metrics

logger = logging.getLogger(__name__)

METRICS_REGISTRY = CollectorRegistry()

INGEST_SAMPLES_TOTAL = Counter(
    'sysroar_ingest_samples_total',
    'Total telemetry samples accepted by the ingest API',
    registry=METRICS_REGISTRY,
)
INGEST_PERSISTED_TOTAL = Counter(
    'sysroar_ingest_persisted_total',
    'Total telemetry samples persisted to TimescaleDB',
    registry=METRICS_REGISTRY,
)
INGEST_DLQ_TOTAL = Counter(
    'sysroar_ingest_dlq_total',
    'Total telemetry entries routed to the dead-letter stream',
    registry=METRICS_REGISTRY,
)
INGEST_STREAM_LENGTH = Gauge(
    'sysroar_ingest_stream_length',
    'Current Redis telemetry stream length',
    registry=METRICS_REGISTRY,
)
INGEST_STREAM_PENDING = Gauge(
    'sysroar_ingest_stream_pending',
    'Pending unacknowledged entries in the telemetry consumer group',
    registry=METRICS_REGISTRY,
)
INGEST_STREAM_LAG = Gauge(
    'sysroar_ingest_stream_lag',
    'Consumer group lag on the telemetry stream',
    registry=METRICS_REGISTRY,
)
INGEST_DLQ_LENGTH = Gauge(
    'sysroar_ingest_dlq_length',
    'Current dead-letter stream length',
    registry=METRICS_REGISTRY,
)
ALERT_EVAL_DURATION_SECONDS = Histogram(
    'sysroar_alert_eval_duration_seconds',
    'Duration of scheduled alert rule evaluation runs in seconds',
    registry=METRICS_REGISTRY,
)
NOTIFICATION_OUTBOX_PENDING = Gauge(
    'sysroar_notification_outbox_pending',
    'Current count of pending notification outbox records',
    registry=METRICS_REGISTRY,
)
NOTIFICATION_OUTBOX_FAILED_TOTAL = Counter(
    'sysroar_notification_outbox_failed_total',
    'Total failed notification outbox delivery attempts',
    registry=METRICS_REGISTRY,
)


def refresh_live_gauges():
    try:
        stream_metrics = get_stream_metrics()
        INGEST_STREAM_LENGTH.set(stream_metrics.get('stream_length', 0))
        INGEST_STREAM_PENDING.set(stream_metrics.get('pending_count', 0))
        INGEST_STREAM_LAG.set(stream_metrics.get('lag', 0))
        INGEST_DLQ_LENGTH.set(stream_metrics.get('dlq_length', 0))
    except Exception:
        logger.warning('Failed to refresh stream metrics gauges', exc_info=True)

    try:
        from monitoring.models import NotificationOutbox

        pending_outbox = NotificationOutbox.unscoped.filter(status='PENDING').count()
        NOTIFICATION_OUTBOX_PENDING.set(pending_outbox)
    except Exception:
        logger.warning('Failed to refresh outbox pending gauge', exc_info=True)


def _extract_bearer_token(request) -> str:
    header = request.headers.get('Authorization', '')
    prefix = 'Bearer '
    if not header.startswith(prefix):
        return ''
    return header[len(prefix):].strip()


@require_http_methods(['GET', 'HEAD'])
def metrics_view(request):
    expected_token = getattr(settings, 'METRICS_AUTH_TOKEN', '') or ''
    if not expected_token:
        response = HttpResponse('Metrics endpoint disabled', status=403, content_type='text/plain')
        response['Cache-Control'] = 'no-store'
        return response

    provided_token = _extract_bearer_token(request)
    if not provided_token or not hmac.compare_digest(provided_token, expected_token):
        response = HttpResponse('Unauthorized', status=401, content_type='text/plain')
        response['WWW-Authenticate'] = 'Bearer'
        response['Cache-Control'] = 'no-store'
        return response

    refresh_live_gauges()
    payload = generate_latest(METRICS_REGISTRY)
    response = HttpResponse(payload, status=200, content_type=CONTENT_TYPE_LATEST)
    response['Cache-Control'] = 'no-store'
    return response
