from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/telemetry/<uuid:server_id>/', consumers.ServerTelemetryConsumer.as_asgi()),
]
