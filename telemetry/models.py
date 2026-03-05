import uuid
from django.db import models
from accounts.models import TenantModel
from monitoring.models import Server

class MetricLog(TenantModel):
    """
    High-volume, raw time-series data. 
    Retained temporarily before being purged/rolled up.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='metrics')
    timestamp = models.DateTimeField(db_index=True)
    
    # Core Metrics
    cpu_usage = models.FloatField(help_text="CPU Usage Percentage")
    ram_usage = models.FloatField(help_text="RAM Usage Percentage")
    disk_io = models.FloatField(help_text="Disk I/O Throughput (MB)", null=True, blank=True)

    class Meta:
        # Compound index for fast charting and querying by tenant and time
        indexes = [
            models.Index(fields=['company', 'server', 'timestamp']),
            models.Index(fields=['server', 'timestamp']),
        ]
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.server.name} at {self.timestamp}"


class MetricRollup(TenantModel):
    """
    Long-term, historical aggregated data (e.g., hourly averages).
    Retained indefinitely for capacity planning.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='rollups')
    timestamp = models.DateTimeField(db_index=True, help_text="Truncated to the hour")
    
    # Aggregated Metrics
    avg_cpu = models.FloatField()
    avg_ram = models.FloatField()
    avg_disk_io = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ('server', 'timestamp')
        indexes = [
            models.Index(fields=['company', 'server', 'timestamp']),
        ]
        ordering = ['-timestamp']

    def __str__(self):
        return f"Rollup: {self.server.name} at {self.timestamp}"
