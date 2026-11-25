import uuid
from django.db import models
from django.utils import timezone
from accounts.models import TenantModel
from monitoring.models import Server


class MetricLog(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sample_id = models.UUIDField(null=True, blank=True)
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='metrics')
    timestamp = models.DateTimeField(db_index=True)
    received_at = models.DateTimeField(default=timezone.now, db_index=True)

    cpu_usage = models.FloatField()
    ram_usage = models.FloatField()
    disk_io = models.FloatField(null=True, blank=True)
    swap_usage = models.FloatField(null=True, blank=True)
    disk_usage = models.FloatField(null=True, blank=True)
    disk_read_bps = models.FloatField(null=True, blank=True)
    disk_write_bps = models.FloatField(null=True, blank=True)
    net_rx_bps = models.FloatField(null=True, blank=True)
    net_tx_bps = models.FloatField(null=True, blank=True)
    load_1m = models.FloatField(null=True, blank=True)
    uptime_seconds = models.BigIntegerField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['company', 'server', 'timestamp']),
            models.Index(fields=['server', 'timestamp']),
        ]
        ordering = ['-timestamp']

    def __str__(self):
        return f'{self.server.name} at {self.timestamp}'
