import logging
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .serializers import MetricLogSerializer
from .ingestion import push_to_redis_queue

logger = logging.getLogger(__name__)

class TelemetryIngestView(APIView):
    """
    Endpoint for remote agents to push telemetry data.
    Implements a write-behind pattern by queueing data in Redis.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = MetricLogSerializer(data=request.data)
        if serializer.is_valid():
            try:
                # Make sure timestamp is set if not provided by the agent
                data = serializer.validated_data
                if not data.get('timestamp'):
                    from django.utils import timezone
                    data['timestamp'] = timezone.now()
                
                push_to_redis_queue(data)
                
                return Response(
                    {"status": "accepted", "message": "Telemetry queued for processing."},
                    status=status.HTTP_202_ACCEPTED
                )
            except Exception as e:
                logger.error(f"Error queueing telemetry: {e}", exc_info=True)
                return Response(
                    {"error": "Failed to queue telemetry data."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

from monitoring.models import Server

class TelemetryConfigView(APIView):
    """
    Returns dynamic configuration for remote agents.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        server_id = request.headers.get('X-Server-ID')
        if not server_id:
            return Response({"error": "X-Server-ID header is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            server = Server.unscoped.filter(company=request.user.company).get(id=server_id)
            config = {
                "telemetry_cadence": server.telemetry_cadence,
                "log_level": server.log_level
            }
            return Response(config, status=status.HTTP_200_OK)
        except Server.DoesNotExist:
            return Response({"error": "Server not found"}, status=status.HTTP_404_NOT_FOUND)
