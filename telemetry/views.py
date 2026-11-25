import logging
import uuid
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from monitoring.models import Server
from .ingestion import push_to_redis_queue
from .serializers import MetricLogSerializer

logger = logging.getLogger(__name__)


class TelemetryIngestView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = MetricLogSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            try:
                data = serializer.validated_data
                payload = {
                    'server_id': str(data['server_id']),
                    'company_id': str(data['company_id']),
                    'cpu_usage': data['cpu_usage'],
                    'ram_usage': data['ram_usage'],
                    'disk_io': data.get('disk_io'),
                    'timestamp': data.get('timestamp') or timezone.now(),
                }
                push_to_redis_queue(payload)
                return Response(
                    {'status': 'accepted', 'message': 'Telemetry queued for processing.'},
                    status=status.HTTP_202_ACCEPTED,
                )
            except Exception as e:
                logger.error(f'Error queueing telemetry: {e}', exc_info=True)
                return Response(
                    {'error': 'Failed to queue telemetry data.'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TelemetryConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        server_id = request.headers.get('X-Server-ID')
        if not server_id:
            return Response({'error': 'X-Server-ID header is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            server_uuid = uuid.UUID(server_id)
        except (ValueError, TypeError):
            return Response({'error': 'Invalid X-Server-ID header'}, status=status.HTTP_400_BAD_REQUEST)
        company_id = getattr(request.user, 'company_id', None)
        if not company_id:
            return Response({'error': 'Server not found'}, status=status.HTTP_404_NOT_FOUND)
        try:
            server = Server.unscoped.filter(company_id=company_id).get(id=server_uuid)
            config = {
                'telemetry_cadence': server.telemetry_cadence,
                'log_level': server.log_level,
            }
            return Response(config, status=status.HTTP_200_OK)
        except Server.DoesNotExist:
            return Response({'error': 'Server not found'}, status=status.HTTP_404_NOT_FOUND)
