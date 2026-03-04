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
                push_to_redis_queue(serializer.validated_data)
                
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
