import json
import re
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from rest_framework import serializers
from monitoring.models import Server

_CONTROL_CHARS_RE = re.compile(r'[\x00-\x1f\x7f]')
MAX_FUTURE_DRIFT = timedelta(minutes=5)
MAX_DETAILS_BYTES = 65536


class MetricLogSerializer(serializers.Serializer):
    server = serializers.UUIDField()
    sample_id = serializers.UUIDField(required=False, allow_null=True)
    timestamp = serializers.DateTimeField(required=False, allow_null=True)
    cpu_usage = serializers.FloatField(min_value=0.0, max_value=100.0)
    ram_usage = serializers.FloatField(min_value=0.0, max_value=100.0)
    disk_io = serializers.FloatField(min_value=0.0, required=False, allow_null=True)
    swap_usage = serializers.FloatField(min_value=0.0, max_value=100.0, required=False, allow_null=True)
    disk_usage = serializers.FloatField(min_value=0.0, max_value=100.0, required=False, allow_null=True)
    disk_read_bps = serializers.FloatField(min_value=0.0, required=False, allow_null=True)
    disk_write_bps = serializers.FloatField(min_value=0.0, required=False, allow_null=True)
    net_rx_bps = serializers.FloatField(min_value=0.0, required=False, allow_null=True)
    net_tx_bps = serializers.FloatField(min_value=0.0, required=False, allow_null=True)
    load_1m = serializers.FloatField(min_value=0.0, required=False, allow_null=True)
    uptime_seconds = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    details = serializers.DictField(required=False, default=dict)
    ip_address = serializers.IPAddressField(required=False, allow_null=True)
    os_info = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)

    def validate_server(self, value):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        user_company_id = getattr(user, 'company_id', None) if user and user.is_authenticated else None
        agent_server_id = getattr(user, 'server_id', None) if getattr(user, 'is_agent', False) else None
        allowed_servers = self.context.get('allowed_servers')

        if agent_server_id is not None and value != agent_server_id:
            raise serializers.ValidationError('Agent key is not authorized for this server.')

        if allowed_servers is not None:
            server = allowed_servers.get(value)
        else:
            server = Server.unscoped.filter(id=value).only('id', 'company_id').first()

        if server is None or user_company_id is None or server.company_id != user_company_id:
            raise serializers.ValidationError('Server does not exist or access denied.')
        self._validated_server = server
        return value

    def validate_timestamp(self, value):
        if value is None:
            return None
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.utc)
        if value > timezone.now() + MAX_FUTURE_DRIFT:
            raise serializers.ValidationError('Timestamp cannot be more than 5 minutes in the future.')
        return value

    def validate_os_info(self, value):
        if value is None:
            return None
        cleaned = _CONTROL_CHARS_RE.sub('', value).strip()
        return cleaned or None

    def validate_details(self, value):
        if not value:
            return {}
        encoded = json.dumps(value).encode('utf-8')
        if len(encoded) > MAX_DETAILS_BYTES:
            raise serializers.ValidationError('Details payload exceeds maximum allowed size.')
        return value

    def validate(self, attrs):
        attrs['server_id'] = self._validated_server.id
        attrs['company_id'] = self._validated_server.company_id
        return attrs


class MetricBatchRequestSerializer(serializers.Serializer):
    samples = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
    )

    def validate_samples(self, value):
        max_batch = getattr(settings, 'TELEMETRY_MAX_BATCH_SIZE', 500)
        if len(value) > max_batch:
            raise serializers.ValidationError(f'Batch cannot exceed {max_batch} samples.')
        return value


class ServerInventorySerializer(serializers.Serializer):
    server = serializers.UUIDField()
    hostname = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    os_info = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    kernel = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    cpu_model = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    cpu_cores = serializers.IntegerField(min_value=1, max_value=4096, required=False, allow_null=True)
    total_ram_bytes = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    ip_address = serializers.IPAddressField(required=False, allow_null=True)
    agent_version = serializers.CharField(max_length=64, required=False, allow_blank=True, allow_null=True)

    def _clean_text(self, value):
        if value is None:
            return None
        cleaned = _CONTROL_CHARS_RE.sub('', value).strip()
        return cleaned or None

    def validate_hostname(self, value):
        return self._clean_text(value)

    def validate_os_info(self, value):
        return self._clean_text(value)

    def validate_kernel(self, value):
        return self._clean_text(value)

    def validate_cpu_model(self, value):
        return self._clean_text(value)

    def validate_agent_version(self, value):
        return self._clean_text(value)

    def validate_server(self, value):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        user_company_id = getattr(user, 'company_id', None) if user and user.is_authenticated else None
        agent_server_id = getattr(user, 'server_id', None) if getattr(user, 'is_agent', False) else None
        if agent_server_id is not None and value != agent_server_id:
            raise serializers.ValidationError('Agent key is not authorized for this server.')
        server = Server.unscoped.filter(id=value).only('id', 'company_id').first()
        if server is None or user_company_id is None or server.company_id != user_company_id:
            raise serializers.ValidationError('Server does not exist or access denied.')
        self._validated_server = server
        return value

    def validate(self, attrs):
        attrs['server_id'] = self._validated_server.id
        attrs['company_id'] = self._validated_server.company_id
        return attrs


class AgentEnrollmentSerializer(serializers.Serializer):
    enrollment_token = serializers.CharField(max_length=128)
    name = serializers.CharField(max_length=255)
    hostname = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    os_info = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    kernel = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    cpu_model = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    cpu_cores = serializers.IntegerField(min_value=1, max_value=4096, required=False, allow_null=True)
    total_ram_bytes = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    agent_version = serializers.CharField(max_length=64, required=False, allow_blank=True, allow_null=True)

    def _clean(self, value):
        if value is None:
            return None
        cleaned = _CONTROL_CHARS_RE.sub('', value).strip()
        return cleaned or None

    def validate_name(self, value):
        cleaned = self._clean(value)
        if not cleaned:
            raise serializers.ValidationError('Server name is required.')
        return cleaned

    def validate_hostname(self, value):
        return self._clean(value)

    def validate_os_info(self, value):
        return self._clean(value)

    def validate_kernel(self, value):
        return self._clean(value)

    def validate_cpu_model(self, value):
        return self._clean(value)

    def validate_agent_version(self, value):
        return self._clean(value)


class MetricHistoryPointSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    cpu = serializers.FloatField(allow_null=True)
    max_cpu = serializers.FloatField(allow_null=True)
    ram = serializers.FloatField(allow_null=True)
    max_ram = serializers.FloatField(allow_null=True)
    swap = serializers.FloatField(allow_null=True)
    disk = serializers.FloatField(allow_null=True)
    disk_read_bps = serializers.FloatField(allow_null=True)
    disk_write_bps = serializers.FloatField(allow_null=True)
    net_rx_bps = serializers.FloatField(allow_null=True)
    net_tx_bps = serializers.FloatField(allow_null=True)
    load_1m = serializers.FloatField(allow_null=True)
    uptime_seconds = serializers.IntegerField(allow_null=True)


class ServerMetricsHistoryResponseSerializer(serializers.Serializer):
    server_id = serializers.UUIDField()
    range = serializers.CharField()
    bucket = serializers.CharField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    points = MetricHistoryPointSerializer(many=True)
