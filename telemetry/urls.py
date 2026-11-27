from django.urls import path
from .views import (
    OtlpMetricsIngestView,
    PrometheusRemoteWriteView,
    ServerMetricsHistoryView,
    TelemetryBatchIngestView,
    TelemetryConfigView,
    TelemetryEnrollView,
    TelemetryIngestView,
    TelemetryInventoryView,
)

urlpatterns = [
    path('enroll/', TelemetryEnrollView.as_view(), name='telemetry-enroll'),
    path('ingest/', TelemetryIngestView.as_view(), name='telemetry-ingest'),
    path('ingest/batch/', TelemetryBatchIngestView.as_view(), name='telemetry-ingest-batch'),
    path('otlp/v1/metrics', OtlpMetricsIngestView.as_view(), name='telemetry-otlp-metrics-noslash'),
    path('otlp/v1/metrics/', OtlpMetricsIngestView.as_view(), name='telemetry-otlp-metrics'),
    path('prometheus/remote-write', PrometheusRemoteWriteView.as_view(), name='telemetry-prom-rw-noslash'),
    path('prometheus/remote-write/', PrometheusRemoteWriteView.as_view(), name='telemetry-prom-rw'),
    path('inventory/', TelemetryInventoryView.as_view(), name='telemetry-inventory'),
    path('config/', TelemetryConfigView.as_view(), name='telemetry-config'),
    path('servers/<uuid:server_id>/metrics/', ServerMetricsHistoryView.as_view(), name='server-metrics-history'),
]
