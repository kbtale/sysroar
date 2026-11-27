import re
from datetime import timedelta
from django.utils import timezone
from rest_framework import serializers
from monitoring.heartbeat import compute_offline_threshold_seconds, get_live_heartbeats
from telemetry.notifications.providers import (
    DEFAULT_PROVIDER_URLS,
    SECRET_REQUIRED_CHANNELS,
    URL_BASED_CHANNELS,
)
from telemetry.notifications.ssrf import SSRFBlockedError, validate_webhook_url
from .models import (
    AgentKey,
    AlertRule,
    AlertSilence,
    AuditLog,
    EnrollmentToken,
    Incident,
    IncidentComment,
    MaintenanceWindow,
    NotificationChannel,
    Server,
    StatusPage,
    UptimeCheck,
    UptimeCheckResult,
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
        target = (attrs.get('target', getattr(self.instance, 'target', '')) or '').strip()
        if not target and channel_type in DEFAULT_PROVIDER_URLS:
            target = DEFAULT_PROVIDER_URLS[channel_type]
            attrs['target'] = target
        secret = attrs.get('webhook_secret', getattr(self.instance, 'webhook_secret', ''))
        if channel_type in SECRET_REQUIRED_CHANNELS and not (secret or '').strip():
            raise serializers.ValidationError({'webhook_secret': f'{channel_type} requires a secret/API key.'})
        if channel_type in URL_BASED_CHANNELS:
            try:
                validate_webhook_url(target)
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
            'log_query',
            'log_level',
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
        if notification_type in URL_BASED_CHANNELS:
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
            'uptime_check',
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
        if obj.server_id:
            return obj.server.name
        if obj.uptime_check_id:
            return obj.uptime_check.name
        return ''


class UptimeCheckResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = UptimeCheckResult
        fields = [
            'id',
            'status',
            'latency_ms',
            'status_code',
            'ssl_expiry_days',
            'error_message',
            'checked_at',
        ]
        read_only_fields = fields


class UptimeCheckSerializer(serializers.ModelSerializer):
    channel = serializers.PrimaryKeyRelatedField(
        queryset=NotificationChannel.unscoped.all(),
        required=False,
        allow_null=True,
    )
    uptime_24h_percent = serializers.SerializerMethodField()
    recent_statuses = serializers.SerializerMethodField()

    class Meta:
        model = UptimeCheck
        fields = [
            'id',
            'name',
            'check_type',
            'target',
            'port',
            'expected_status',
            'expected_keyword',
            'ssl_expiry_warning_days',
            'interval_seconds',
            'timeout_seconds',
            'allow_private_targets',
            'channel',
            'tags',
            'is_active',
            'last_status',
            'last_latency_ms',
            'last_ssl_expiry_days',
            'last_error',
            'last_checked_at',
            'consecutive_failures',
            'uptime_24h_percent',
            'recent_statuses',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'last_status',
            'last_latency_ms',
            'last_ssl_expiry_days',
            'last_error',
            'last_checked_at',
            'consecutive_failures',
            'uptime_24h_percent',
            'recent_statuses',
            'created_at',
        ]

    def validate_channel(self, value):
        if value is None:
            return None
        company_id = getattr(getattr(self.context.get('request'), 'user', None), 'company_id', None)
        if not company_id or value.company_id != company_id:
            raise serializers.ValidationError('Channel does not exist or access denied.')
        return value

    def validate_interval_seconds(self, value):
        if value < 30 or value > 3600:
            raise serializers.ValidationError('Interval must be between 30 and 3600 seconds.')
        return value

    def validate_timeout_seconds(self, value):
        if value < 1 or value > 60:
            raise serializers.ValidationError('Timeout must be between 1 and 60 seconds.')
        return value

    def validate(self, attrs):
        check_type = attrs.get('check_type', getattr(self.instance, 'check_type', 'http'))
        target = (attrs.get('target', getattr(self.instance, 'target', '')) or '').strip()
        allow_private = attrs.get(
            'allow_private_targets',
            getattr(self.instance, 'allow_private_targets', False),
        )
        if not target:
            raise serializers.ValidationError({'target': 'Target is required.'})
        if check_type == 'http' and not allow_private:
            try:
                validate_webhook_url(target)
            except SSRFBlockedError as exc:
                raise serializers.ValidationError({'target': str(exc)}) from exc
        attrs['target'] = target
        return attrs

    def get_uptime_24h_percent(self, obj) -> float | None:
        uptime_map = self.context.get('uptime_24h_map')
        if uptime_map is not None:
            return uptime_map.get(str(obj.id))
        return None

    def get_recent_statuses(self, obj) -> list[str]:
        bars_map = self.context.get('recent_bars_map')
        if bars_map is not None:
            return bars_map.get(str(obj.id), [])
        return []


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


class MaintenanceWindowSerializer(serializers.ModelSerializer):
    server = serializers.PrimaryKeyRelatedField(queryset=Server.unscoped.all(), required=False, allow_null=True)
    server_name = serializers.SerializerMethodField()
    is_currently_active = serializers.SerializerMethodField()

    class Meta:
        model = MaintenanceWindow
        fields = [
            'id',
            'name',
            'scope',
            'server',
            'server_name',
            'tag_filter',
            'recurrence',
            'starts_at',
            'ends_at',
            'reason',
            'is_active',
            'is_currently_active',
            'created_at',
        ]
        read_only_fields = ['id', 'server_name', 'is_currently_active', 'created_at']

    def get_server_name(self, obj) -> str | None:
        return obj.server.name if obj.server_id else None

    def get_is_currently_active(self, obj) -> bool:
        return obj.matches_time()

    def validate_server(self, value):
        if value is None:
            return None
        company_id = getattr(getattr(self.context.get('request'), 'user', None), 'company_id', None)
        if not company_id or value.company_id != company_id:
            raise serializers.ValidationError('Server does not exist or access denied.')
        return value

    def validate(self, attrs):
        scope = attrs.get('scope', getattr(self.instance, 'scope', 'all'))
        server = attrs.get('server', getattr(self.instance, 'server', None))
        tag_filter = (attrs.get('tag_filter', getattr(self.instance, 'tag_filter', '')) or '').strip().lower()
        attrs['tag_filter'] = tag_filter
        starts_at = attrs.get('starts_at', getattr(self.instance, 'starts_at', None))
        ends_at = attrs.get('ends_at', getattr(self.instance, 'ends_at', None))

        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError({'ends_at': 'End time must be after start time.'})
        if scope == 'server' and server is None:
            raise serializers.ValidationError({'server': 'Server is required when scope is server.'})
        if scope == 'tag' and not tag_filter:
            raise serializers.ValidationError({'tag_filter': 'Tag filter is required when scope is tag.'})
        return attrs


class StatusPageSerializer(serializers.ModelSerializer):
    servers = serializers.PrimaryKeyRelatedField(queryset=Server.unscoped.all(), many=True, required=False)
    uptime_checks = serializers.PrimaryKeyRelatedField(queryset=UptimeCheck.unscoped.all(), many=True, required=False)

    class Meta:
        model = StatusPage
        fields = [
            'id',
            'slug',
            'title',
            'description',
            'is_public',
            'accent_color',
            'show_incidents',
            'servers',
            'uptime_checks',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_slug(self, value):
        cleaned = (value or '').strip().lower()
        if not re.match(r'^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$', cleaned):
            raise serializers.ValidationError('Slug must be 3-80 lowercase letters, numbers, or hyphens.')
        return cleaned

    def validate_accent_color(self, value):
        cleaned = (value or '#0ea5e9').strip()
        if not re.match(r'^#[0-9a-fA-F]{6}$', cleaned):
            raise serializers.ValidationError('Accent color must be a 6-digit hex color like #0ea5e9.')
        return cleaned

    def validate_servers(self, values):
        company_id = getattr(getattr(self.context.get('request'), 'user', None), 'company_id', None)
        for srv in values:
            if not company_id or srv.company_id != company_id:
                raise serializers.ValidationError('One or more servers do not exist or access denied.')
        return values

    def validate_uptime_checks(self, values):
        company_id = getattr(getattr(self.context.get('request'), 'user', None), 'company_id', None)
        for chk in values:
            if not company_id or chk.company_id != company_id:
                raise serializers.ValidationError('One or more uptime checks do not exist or access denied.')
        return values


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
