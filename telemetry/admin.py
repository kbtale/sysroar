from django.contrib import admin
from accounts.admin import TenantAwareModelAdmin
from .models import MetricLog


@admin.register(MetricLog)
class MetricLogAdmin(TenantAwareModelAdmin):
    list_display = ('server', 'company', 'timestamp', 'received_at', 'cpu_usage', 'ram_usage', 'disk_io')
    list_filter = ('company', 'server')
    readonly_fields = ('id',)
