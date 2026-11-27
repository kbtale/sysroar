from datetime import timedelta
from django.utils import timezone
from rest_framework import serializers
from monitoring.heartbeat import compute_offline_threshold_seconds, get_live_heartbeats
from .models import AgentKey, AlertRule, EnrollmentToken, Server


class ServerSerializer(serializers.ModelSerializer):
    last_seen = serializers.SerializerMethodField()
    ip_address = serializers.SerializerMethodField()
    os_info = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = Server
        fields = [
            'id',
            'name',
            'hostname',
            'ip_address',
            'os_info',
            'kernel',
            'cpu_model',
            'cpu_cores',
            'total_ram_bytes',
            'agent_version',
            'is_active',
            'telemetry_cadence',
            'log_level',
            'last_seen',
            'status',
            'created_at',
        ]
        read_only_fields = ['id', 'last_seen', 'status', 'created_at']

    def _get_live(self, obj):
        live_map = self.context.get('live_heartbeats')
        if live_map is None:
            live_map = get_live_heartbeats([obj.id])
        return live_map.get(str(obj.id), {})

    def _effective_last_ping(self, obj):
        live_ping = self._get_live(obj).get('last_ping')
        if live_ping and (obj.last_ping is None or live_ping > obj.last_ping):
            return live_ping
        return obj.last_ping

    def get_last_seen(self, obj):
        effective = self._effective_last_ping(obj)
        return effective.isoformat() if effective else None

    def get_ip_address(self, obj):
        return self._get_live(obj).get('ip_address') or obj.ip_address

    def get_os_info(self, obj):
        return self._get_live(obj).get('os_info') or obj.os_info

    def get_status(self, obj):
        effective = self._effective_last_ping(obj)
        if effective is None:
            return 'unknown'
        threshold = timedelta(seconds=compute_offline_threshold_seconds(obj.telemetry_cadence))
        if timezone.now() - effective <= threshold:
            return 'online'
        return 'offline'


class EnrollmentTokenSerializer(serializers.ModelSerializer):
    class Meta:
        model = EnrollmentToken
        fields = [
            'id',
            'name',
            'prefix',
            'max_uses',
            'uses_count',
            'expires_at',
            'revoked_at',
            'created_at',
        ]
        read_only_fields = fields


class EnrollmentTokenCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=128)
    max_uses = serializers.IntegerField(min_value=1, max_value=10000, required=False, allow_null=True, default=1)
    expires_in_hours = serializers.IntegerField(
        min_value=1,
        max_value=8760,
        required=False,
        allow_null=True,
        default=24,
    )


class AgentKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentKey
        fields = [
            'id',
            'server',
            'prefix',
            'is_active',
            'created_at',
            'last_used_at',
            'revoked_at',
        ]
        read_only_fields = fields


class AgentKeyServerActionSerializer(serializers.Serializer):
    server = serializers.UUIDField()


class AlertRuleSerializer(serializers.ModelSerializer):
    server = serializers.PrimaryKeyRelatedField(queryset=Server.unscoped.all())

    class Meta:
        model = AlertRule
        fields = [
            'id',
            'server',
            'metric_type',
            'operator',
            'severity',
            'aggregation',
            'threshold_value',
            'hysteresis_margin',
            'duration_minutes',
            'is_active',
            'notification_type',
            'notification_target',
        ]
        read_only_fields = ['id']

    def validate_server(self, value):
        request = self.context.get('request')
        company_id = getattr(getattr(request, 'user', None), 'company_id', None)
        if not company_id or value.company_id != company_id:
            raise serializers.ValidationError('Server does not exist or access denied.')
        return value
