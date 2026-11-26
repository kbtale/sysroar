from django.urls import path
from .views import (
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
    path('inventory/', TelemetryInventoryView.as_view(), name='telemetry-inventory'),
    path('config/', TelemetryConfigView.as_view(), name='telemetry-config'),
]
