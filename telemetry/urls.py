from django.urls import path
from .views import TelemetryBatchIngestView, TelemetryConfigView, TelemetryIngestView

urlpatterns = [
    path('ingest/', TelemetryIngestView.as_view(), name='telemetry-ingest'),
    path('ingest/batch/', TelemetryBatchIngestView.as_view(), name='telemetry-ingest-batch'),
    path('config/', TelemetryConfigView.as_view(), name='telemetry-config'),
]
