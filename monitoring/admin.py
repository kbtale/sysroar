from django.contrib import admin
from accounts.admin import TenantAwareModelAdmin
from .models import (
    AgentKey,
    AlertRule,
    AlertState,
    AuditLog,
    EnrollmentToken,
    NotificationOutbox,
    Server,
    ServerAlertState,
)


@admin.register(Server)
class ServerAdmin(TenantAwareModelAdmin):
    list_display = ('name', 'ip_address', 'company', 'is_active', 'telemetry_cadence', 'last_ping')
    list_filter = ('is_active', 'company')
    search_fields = ('name', 'ip_address')
    readonly_fields = ('id', 'created_at')


@admin.register(AlertRule)
class AlertRuleAdmin(TenantAwareModelAdmin):
    list_display = (
        'server',
        'metric_type',
        'operator',
        'threshold_value',
        'severity',
        'duration_minutes',
        'notification_type',
        'is_active',
    )
    list_filter = ('metric_type', 'severity', 'notification_type', 'is_active')


@admin.register(AlertState)
class AlertStateAdmin(TenantAwareModelAdmin):
    list_display = ('rule', 'status', 'current_cooldown_tier', 'is_flapping', 'last_value', 'last_evaluated_at')
    list_filter = ('status', 'is_flapping')
    readonly_fields = ('rule',)


@admin.register(NotificationOutbox)
class NotificationOutboxAdmin(TenantAwareModelAdmin):
    list_display = ('event_type', 'server', 'rule', 'status', 'attempts', 'next_attempt_at', 'delivered_at')
    list_filter = ('status', 'event_type')
    readonly_fields = ('id', 'created_at', 'delivered_at')


@admin.register(ServerAlertState)
class ServerAlertStateAdmin(TenantAwareModelAdmin):
    list_display = ('server', 'current_cooldown_tier', 'consecutive_healthy_count', 'last_alert_sent_at')
    readonly_fields = ('server',)


@admin.register(EnrollmentToken)
class EnrollmentTokenAdmin(TenantAwareModelAdmin):
    list_display = ('name', 'prefix', 'company', 'uses_count', 'max_uses', 'expires_at', 'revoked_at')
    list_filter = ('company',)
    readonly_fields = ('id', 'prefix', 'token_hash', 'uses_count', 'created_at', 'revoked_at')


@admin.register(AgentKey)
class AgentKeyAdmin(TenantAwareModelAdmin):
    list_display = ('prefix', 'server', 'company', 'is_active', 'last_used_at', 'revoked_at')
    list_filter = ('is_active', 'company')
    readonly_fields = ('id', 'prefix', 'key_hash', 'created_at', 'last_used_at', 'revoked_at')


@admin.register(AuditLog)
class AuditLogAdmin(TenantAwareModelAdmin):
    list_display = ('created_at', 'company', 'actor_username', 'action', 'resource_type', 'resource_id')
    list_filter = ('action', 'resource_type', 'company')
    readonly_fields = (
        'id',
        'company',
        'actor',
        'actor_username',
        'action',
        'resource_type',
        'resource_id',
        'metadata',
        'ip_address',
        'correlation_id',
        'created_at',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
