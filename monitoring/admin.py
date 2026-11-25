from django.contrib import admin
from accounts.admin import TenantAwareModelAdmin
from .models import AlertRule, Server, ServerAlertState


@admin.register(Server)
class ServerAdmin(TenantAwareModelAdmin):
    list_display = ('name', 'ip_address', 'company', 'is_active', 'telemetry_cadence', 'last_ping')
    list_filter = ('is_active', 'company')
    search_fields = ('name', 'ip_address')
    readonly_fields = ('id', 'created_at')


@admin.register(AlertRule)
class AlertRuleAdmin(TenantAwareModelAdmin):
    list_display = ('server', 'metric_type', 'threshold_value', 'notification_type', 'is_active')
    list_filter = ('metric_type', 'notification_type', 'is_active')


@admin.register(ServerAlertState)
class ServerAlertStateAdmin(TenantAwareModelAdmin):
    list_display = ('server', 'current_cooldown_tier', 'consecutive_healthy_count', 'last_alert_sent_at')
    readonly_fields = ('server',)
