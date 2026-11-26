import ipaddress
import logging
import uuid
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from monitoring.models import Server
from .ingestion import push_batch_to_stream, push_to_stream
from .parsers import GzipJSONParser
from .serializers import MetricBatchRequestSerializer, MetricLogSerializer
from .throttling import ServerIngestRateThrottle

logger = logging.getLogger(__name__)

_STREAM_OPTIONAL_FIELDS = (
    'sample_id',
    'disk_io',
    'swap_usage',
    'disk_usage',
    'disk_read_bps',
    'disk_write_bps',
    'net_rx_bps',
    'net_tx_bps',
    'load_1m',
    'uptime_seconds',
    'details',
)


def _extract_remote_ip(request):
    candidate = request.META.get('REMOTE_ADDR')
    if not candidate:
        return None
    try:
        return str(ipaddress.ip_address(candidate.strip()))
    except ValueError:
        return None


def _build_stream_payload(validated_data, now):
    payload = {
        'server_id': str(validated_data['server_id']),
        'company_id': str(validated_data['company_id']),
        'cpu_usage': validated_data['cpu_usage'],
        'ram_usage': validated_data['ram_usage'],
        'timestamp': validated_data.get('timestamp') or now,
        'received_at': now,
    }
    for field in _STREAM_OPTIONAL_FIELDS:
        if validated_data.get(field) is not None:
            payload[field] = validated_data[field]
    return payload


class TelemetryIngestView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ServerIngestRateThrottle]
    parser_classes = [GzipJSONParser]

    def post(self, request, *args, **kwargs):
        serializer = MetricLogSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            try:
                data = serializer.validated_data
                now = timezone.now()
                payload = _build_stream_payload(data, now)
                push_to_stream(payload)

                update_fields = {'last_ping': now}
                ip_address = data.get('ip_address') or _extract_remote_ip(request)
                if ip_address:
                    update_fields['ip_address'] = ip_address
                if data.get('os_info'):
                    update_fields['os_info'] = data['os_info']

                Server.unscoped.filter(
                    id=data['server_id'],
                    company_id=data['company_id'],
                ).update(**update_fields)

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


class TelemetryBatchIngestView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ServerIngestRateThrottle]
    parser_classes = [GzipJSONParser]

    def post(self, request, *args, **kwargs):
        envelope = MetricBatchRequestSerializer(data=request.data)
        if not envelope.is_valid():
            return Response(envelope.errors, status=status.HTTP_400_BAD_REQUEST)

        company_id = getattr(request.user, 'company_id', None)
        raw_samples = envelope.validated_data['samples']

        candidate_uuids = set()
        for sample in raw_samples:
            raw_server = sample.get('server')
            if raw_server:
                try:
                    candidate_uuids.add(uuid.UUID(str(raw_server)))
                except (ValueError, TypeError):
                    pass

        allowed_servers = {}
        if company_id and candidate_uuids:
            allowed_servers = {
                s.id: s
                for s in Server.unscoped.filter(
                    id__in=candidate_uuids,
                    company_id=company_id,
                ).only('id', 'company_id')
            }

        now = timezone.now()
        payloads = []
        server_updates = {}
        errors = {}
        remote_ip = _extract_remote_ip(request)

        for idx, raw_sample in enumerate(raw_samples):
            item_serializer = MetricLogSerializer(
                data=raw_sample,
                context={'request': request, 'allowed_servers': allowed_servers},
            )
            if not item_serializer.is_valid():
                errors[str(idx)] = item_serializer.errors
                continue
            data = item_serializer.validated_data
            payloads.append(_build_stream_payload(data, now))

            server_id = data['server_id']
            update_fields = server_updates.setdefault(server_id, {'last_ping': now})
            ip_address = data.get('ip_address') or remote_ip
            if ip_address:
                update_fields['ip_address'] = ip_address
            if data.get('os_info'):
                update_fields['os_info'] = data['os_info']

        if errors:
            return Response({'samples': errors}, status=status.HTTP_400_BAD_REQUEST)

        try:
            push_batch_to_stream(payloads)
            for server_id, update_fields in server_updates.items():
                Server.unscoped.filter(id=server_id, company_id=company_id).update(**update_fields)
            return Response(
                {'status': 'accepted', 'accepted': len(payloads)},
                status=status.HTTP_202_ACCEPTED,
            )
        except Exception as e:
            logger.error(f'Error queueing telemetry batch: {e}', exc_info=True)
            return Response(
                {'error': 'Failed to queue telemetry batch.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


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
