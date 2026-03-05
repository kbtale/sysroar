from django.urls import path
from .views import TelemetryIngestView, TelemetryConfigView

urlpatterns = [
    path('ingest/', TelemetryIngestView.as_view(), name='telemetry-ingest'),
    path('config/', TelemetryConfigView.as_view(), name='telemetry-config'),
]
