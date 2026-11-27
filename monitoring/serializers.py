import re
from datetime import timedelta
from django.utils import timezone
from rest_framework import serializers
from monitoring.heartbeat import compute_offline_threshold_seconds, get_live_heartbeats
from telemetry.notifications.ssrf import SSRFBlockedError, validate_webhook_url
from .models import (
    AgentKey,
    AlertRule,
    AlertSilence,
    AuditLog,
    EnrollmentToken,
    Incident,
    IncidentComment,
    NotificationChannel,
    Server,
)

_TAG_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{0,31}$')


class ServerSerializer(serializers.ModelSerializer):
    last_seen = serializers.SerializerMethodField()
    ip_address = serializers.SerializerMethodField()
    os_info = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    alert_status = serializers.SerializerMethodField()
    sparkline = serializers.SerializerMethodField()
    latest_details = serializers.SerializerMethodField()

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
            'tags',
            'last_seen',
            'status',
            'alert_status',
            'sparkline',
            'latest_details',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'last_seen',
            'status',
            'alert_status',
            'sparkline',
            'latest_details',
            'created_at',
        ]

    def validate_tags(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError('Tags must be a list of strings.')
        if len(value) > 20:
            raise serializers.ValidationError('A server may have at most 20 tags.')
        cleaned = []
        seen = set()
        for raw in value:
            tag = str(raw).strip().lower()
            if not _TAG_RE.match(tag):
                raise serializers.ValidationError(f'Invalid tag: {raw}')
            if tag not in seen:
                seen.add(tag)
                cleaned.append(tag)
        return cleaned

    def _get_live(self, obj) -> dict:
        live_map = self.context.get('live_heartbeats')
        if live_map is None:
            live_map = get_live_heartbeats([obj.id])
        return live_map.get(str(obj.id), {})

    def _effective_last_ping(self, obj):
        live_ping = self._get_live(obj).get('last_ping')
        if live_ping and (obj.last_ping is None or live_ping > obj.last_ping):
            return live_ping
        return obj.last_ping

    def get_last_seen(self, obj) -> str | None:
        effective = self._effective_last_ping(obj)
        return effective.isoformat() if effective else None

    def get_ip_address(self, obj) -> str | None:
        return self._get_live(obj).get('ip_address') or obj.ip_address

    def get_os_info(self, obj) -> str | None:
        return self._get_live(obj).get('os_info') or obj.os_info

    def get_status(self, obj) -> str:
        effective = self._effective_last_ping(obj)
        if effective is None:
            return 'unknown'
        threshold = timedelta(seconds=compute_offline_threshold_seconds(obj.telemetry_cadence))
        if timezone.now() - effective <= threshold:
            return 'online'
        return 'offline'

    def get_alert_status(self, obj) -> str:
        status_map = self.context.get('alert_statuses')
        if status_map is not None:
            return status_map.get(str(obj.id), 'ok')
        return 'ok'

    def get_sparkline(self, obj) -> list[dict]:
        spark_map = self.context.get('sparklines')
        if spark_map is not None:
            return spark_map.get(str(obj.id), [])
        return []

    def get_latest_details(self, obj) -> dict:
        details_map = self.context.get('latest_details')
        if details_map is not None:
            return details_map.get(str(obj.id), {})
        return {}


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


class NotificationChannelSerializer(serializers.ModelSerializer):
    has_webhook_secret = serializers.SerializerMethodField()

    class Meta:
        model = NotificationChannel
        fields = [
            'id',
            'name',
            'channel_type',
            'target',
            'webhook_secret',
            'has_webhook_secret',
            'is_default',
            'is_active',
            'created_at',
        ]
        read_only_fields = ['id', 'has_webhook_secret', 'created_at']
        extra_kwargs = {
            'webhook_secret': {'write_only': True, 'required': False},
        }

    def get_has_webhook_secret(self, obj) -> bool:
        return bool(obj.webhook_secret)

    def validate(self, attrs):
        channel_type = attrs.get('channel_type', getattr(self.instance, 'channel_type', 'EMAIL'))
        target = attrs.get('target', getattr(self.instance, 'target', ''))
        if channel_type == 'WEBHOOK':
            try:
                validate_webhook_url(target or '')
            except SSRFBlockedError as exc:
                raise serializers.ValidationError({'target': str(exc)}) from exc
        return attrs


class AlertRuleSerializer(serializers.ModelSerializer):
    server = serializers.PrimaryKeyRelatedField(queryset=Server.unscoped.all(), required=False, allow_null=True)
    channel = serializers.PrimaryKeyRelatedField(
        queryset=NotificationChannel.unscoped.all(),
        required=False,
        allow_null=True,
    )
    has_webhook_secret = serializers.SerializerMethodField()
    server_name = serializers.SerializerMethodField()

    class Meta:
        model = AlertRule
        fields = [
            'id',
            'server',
            'server_name',
            'scope',
            'tag_filter',
            'channel',
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
            'webhook_secret',
            'has_webhook_secret',
        ]
        read_only_fields = ['id', 'server_name', 'has_webhook_secret']
        extra_kwargs = {
            'webhook_secret': {'write_only': True, 'required': False},
        }

    def get_has_webhook_secret(self, obj) -> bool:
        return bool(obj.webhook_secret)

    def get_server_name(self, obj) -> str | None:
        return obj.server.name if obj.server_id else None

    def validate_server(self, value):
        if value is None:
            return None
        request = self.context.get('request')
        company_id = getattr(getattr(request, 'user', None), 'company_id', None)
        if not company_id or value.company_id != company_id:
            raise serializers.ValidationError('Server does not exist or access denied.')
        return value

    def validate_channel(self, value):
        if value is None:
            return None
        request = self.context.get('request')
        company_id = getattr(getattr(request, 'user', None), 'company_id', None)
        if not company_id or value.company_id != company_id:
            raise serializers.ValidationError('Channel does not exist or access denied.')
        return value

    def validate(self, attrs):
        scope = attrs.get('scope', getattr(self.instance, 'scope', 'server'))
        server = attrs.get('server', getattr(self.instance, 'server', None))
        tag_filter = (attrs.get('tag_filter', getattr(self.instance, 'tag_filter', '')) or '').strip().lower()
        attrs['tag_filter'] = tag_filter

        if scope == 'server' and server is None:
            raise serializers.ValidationError({'server': 'Server is required when scope is server.'})
        if scope == 'tag' and not tag_filter:
            raise serializers.ValidationError({'tag_filter': 'Tag filter is required when scope is tag.'})

        channel = attrs.get('channel', getattr(self.instance, 'channel', None))
        if channel is not None:
            notification_type = channel.channel_type
            notification_target = channel.target
        else:
            notification_type = attrs.get(
                'notification_type',
                getattr(self.instance, 'notification_type', 'EMAIL'),
            )
            notification_target = attrs.get(
                'notification_target',
                getattr(self.instance, 'notification_target', None),
            )
        if notification_type == 'WEBHOOK':
            try:
                validate_webhook_url(notification_target or '')
            except SSRFBlockedError as exc:
                raise serializers.ValidationError({'notification_target': str(exc)}) from exc
        return attrs


class IncidentCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = IncidentComment
        fields = ['id', 'incident', 'author', 'author_username', 'body', 'created_at']
        read_only_fields = fields


class IncidentCommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=2000)


class IncidentSilenceActionSerializer(serializers.Serializer):
    duration_minutes = serializers.IntegerField(min_value=5, max_value=43200, default=60)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')


class IncidentSerializer(serializers.ModelSerializer):
    server_name = serializers.SerializerMethodField()
    comments = IncidentCommentSerializer(many=True, read_only=True)

    class Meta:
        model = Incident
        fields = [
            'id',
            'server',
            'server_name',
            'rule',
            'title',
            'severity',
            'status',
            'trigger_value',
            'opened_at',
            'acknowledged_at',
            'acknowledged_by',
            'resolved_at',
            'resolved_by',
            'comments',
        ]
        read_only_fields = fields

    def get_server_name(self, obj) -> str:
        return obj.server.name if obj.server_id else ''


class AlertSilenceSerializer(serializers.ModelSerializer):
    rule = serializers.PrimaryKeyRelatedField(queryset=AlertRule.unscoped.all(), required=False, allow_null=True)
    server = serializers.PrimaryKeyRelatedField(queryset=Server.unscoped.all(), required=False, allow_null=True)

    class Meta:
        model = AlertSilence
        fields = ['id', 'rule', 'server', 'reason', 'starts_at', 'ends_at', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_rule(self, value):
        if value is None:
            return None
        company_id = getattr(getattr(self.context.get('request'), 'user', None), 'company_id', None)
        if not company_id or value.company_id != company_id:
            raise serializers.ValidationError('Rule does not exist or access denied.')
        return value

    def validate_server(self, value):
        if value is None:
            return None
        company_id = getattr(getattr(self.context.get('request'), 'user', None), 'company_id', None)
        if not company_id or value.company_id != company_id:
            raise serializers.ValidationError('Server does not exist or access denied.')
        return value


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            'id',
            'actor',
            'actor_username',
            'action',
            'resource_type',
            'resource_id',
            'metadata',
            'ip_address',
            'correlation_id',
            'created_at',
        ]
        read_only_fields = fields
