from django.contrib import admin
from accounts.admin import TenantAwareModelAdmin
from .models import MetricLog, MetricRollup


@admin.register(MetricLog)
class MetricLogAdmin(TenantAwareModelAdmin):
    list_display = ('server', 'company', 'timestamp', 'cpu_usage', 'ram_usage', 'disk_io')
    list_filter = ('company', 'server')
    readonly_fields = ('id',)


@admin.register(MetricRollup)
class MetricRollupAdmin(TenantAwareModelAdmin):
    list_display = ('server', 'company', 'timestamp', 'avg_cpu', 'avg_ram', 'avg_disk_io')
    list_filter = ('company', 'server')
    readonly_fields = ('id',)
