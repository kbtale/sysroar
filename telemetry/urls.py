from django.urls import path
from .views import (
    TelemetryBatchIngestView,
    TelemetryConfigView,
    TelemetryIngestView,
    TelemetryInventoryView,
)

urlpatterns = [
    path('ingest/', TelemetryIngestView.as_view(), name='telemetry-ingest'),
    path('ingest/batch/', TelemetryBatchIngestView.as_view(), name='telemetry-ingest-batch'),
    path('inventory/', TelemetryInventoryView.as_view(), name='telemetry-inventory'),
    path('config/', TelemetryConfigView.as_view(), name='telemetry-config'),
]
