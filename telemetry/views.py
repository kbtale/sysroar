import hashlib
import ipaddress
import json
import logging
import uuid
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.authentication import (
    AgentKeyAuthentication,
    TenantSessionAuthentication,
    TenantTokenAuthentication,
)
from monitoring.heartbeat import record_heartbeat, record_heartbeats_batch
from monitoring.metrics import INGEST_SAMPLES_TOTAL
from monitoring.models import AgentKey, EnrollmentToken, Server
from .ingestion import push_batch_to_stream, push_to_stream
from .parsers import GzipJSONParser
from .serializers import (
    AgentEnrollmentSerializer,
    MetricBatchRequestSerializer,
    MetricLogSerializer,
    ServerInventorySerializer,
)
from .throttling import ServerIngestRateThrottle

_TELEMETRY_AUTH_CLASSES = [
    AgentKeyAuthentication,
    TenantTokenAuthentication,
    TenantSessionAuthentication,
]

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
    authentication_classes = _TELEMETRY_AUTH_CLASSES
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
                INGEST_SAMPLES_TOTAL.inc(1)

                ip_address = data.get('ip_address') or _extract_remote_ip(request)
                record_heartbeat(
                    server_id=data['server_id'],
                    company_id=data['company_id'],
                    seen_at=now,
                    ip_address=ip_address,
                    os_info=data.get('os_info'),
                )

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
    authentication_classes = _TELEMETRY_AUTH_CLASSES
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
            INGEST_SAMPLES_TOTAL.inc(len(payloads))
            record_heartbeats_batch([
                {
                    'server_id': server_id,
                    'company_id': company_id,
                    'seen_at': update_fields['last_ping'],
                    'ip_address': update_fields.get('ip_address'),
                    'os_info': update_fields.get('os_info'),
                }
                for server_id, update_fields in server_updates.items()
            ])
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


class TelemetryInventoryView(APIView):
    authentication_classes = _TELEMETRY_AUTH_CLASSES
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = ServerInventorySerializer(data=request.data, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        now = timezone.now()
        update_fields = {'last_ping': now}
        for field in (
            'hostname',
            'os_info',
            'kernel',
            'cpu_model',
            'cpu_cores',
            'total_ram_bytes',
            'agent_version',
        ):
            if data.get(field) is not None:
                update_fields[field] = data[field]

        ip_address = data.get('ip_address') or _extract_remote_ip(request)
        if ip_address:
            update_fields['ip_address'] = ip_address

        Server.unscoped.filter(
            id=data['server_id'],
            company_id=data['company_id'],
        ).update(**update_fields)

        record_heartbeat(
            server_id=data['server_id'],
            company_id=data['company_id'],
            seen_at=now,
            ip_address=ip_address,
            os_info=data.get('os_info'),
        )
        return Response({'status': 'updated'}, status=status.HTTP_200_OK)


class TelemetryConfigView(APIView):
    authentication_classes = _TELEMETRY_AUTH_CLASSES
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        is_agent = getattr(request.user, 'is_agent', False)
        agent_server_id = getattr(request.user, 'server_id', None) if is_agent else None
        server_id = request.headers.get('X-Server-ID')
        if not server_id:
            if agent_server_id is not None:
                server_uuid = agent_server_id
            else:
                return Response({'error': 'X-Server-ID header is required'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            try:
                server_uuid = uuid.UUID(server_id)
            except (ValueError, TypeError):
                return Response({'error': 'Invalid X-Server-ID header'}, status=status.HTTP_400_BAD_REQUEST)
            if agent_server_id is not None and server_uuid != agent_server_id:
                return Response(
                    {'error': 'Agent key is not authorized for this server'},
                    status=status.HTTP_403_FORBIDDEN,
                )
        company_id = getattr(request.user, 'company_id', None)
        if not company_id:
            return Response({'error': 'Server not found'}, status=status.HTTP_404_NOT_FOUND)
        try:
            server = Server.unscoped.filter(company_id=company_id).get(id=server_uuid)
            config = {
                'telemetry_cadence': server.telemetry_cadence,
                'log_level': server.log_level,
            }
            digest = hashlib.sha256(json.dumps(config, sort_keys=True).encode('utf-8')).hexdigest()[:16]
            etag = f'"{digest}"'
            if request.headers.get('If-None-Match') == etag:
                response = Response(status=status.HTTP_304_NOT_MODIFIED)
                response['ETag'] = etag
                return response
            response = Response(config, status=status.HTTP_200_OK)
            response['ETag'] = etag
            return response
        except Server.DoesNotExist:
            return Response({'error': 'Server not found'}, status=status.HTTP_404_NOT_FOUND)


class TelemetryEnrollView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = AgentEnrollmentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        raw_token = data['enrollment_token'].strip()
        if '.' not in raw_token:
            return Response({'error': 'Invalid or expired enrollment token.'}, status=status.HTTP_401_UNAUTHORIZED)

        prefix = raw_token.split('.', 1)[0]
        now = timezone.now()

        with transaction.atomic():
            token = (
                EnrollmentToken.unscoped.select_for_update()
                .select_related('company')
                .filter(prefix=prefix)
                .first()
            )
            if token is None or not token.verify(raw_token, now=now):
                return Response(
                    {'error': 'Invalid or expired enrollment token.'},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            token.uses_count += 1
            token.save(update_fields=['uses_count'])

            server = Server.unscoped.create(
                company=token.company,
                name=data['name'],
                hostname=data.get('hostname'),
                os_info=data.get('os_info'),
                kernel=data.get('kernel'),
                cpu_model=data.get('cpu_model'),
                cpu_cores=data.get('cpu_cores'),
                total_ram_bytes=data.get('total_ram_bytes'),
                agent_version=data.get('agent_version'),
                ip_address=_extract_remote_ip(request),
                is_active=True,
                last_ping=now,
            )
            agent_key, plaintext_key = AgentKey.generate(server=server)

        return Response(
            {
                'server_id': str(server.id),
                'agent_key': plaintext_key,
                'key_prefix': agent_key.prefix,
                'telemetry_cadence': server.telemetry_cadence,
            },
            status=status.HTTP_201_CREATED,
        )
