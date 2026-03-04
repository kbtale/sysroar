import uuid
from django.db import models
from accounts.models import TenantModel

class Server(TenantModel):
    """
    Represents a physical or virtual machine being monitored.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    os_info = models.CharField(max_length=255, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    last_ping = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.ip_address})"

class AlertRule(TenantModel):
    """
    User-defined thresholds for when an alert should be triggered.
    """
    METRIC_CHOICES = [
        ('cpu', 'CPU Usage (%)'),
        ('ram', 'RAM Usage (%)'),
        ('disk', 'Disk I/O Wait'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='alert_rules')
    metric_type = models.CharField(max_length=10, choices=METRIC_CHOICES)
    threshold_value = models.FloatField(help_text="The ceiling value that triggers the alert (e.g., 90.0 for 90%).")
    duration_minutes = models.PositiveIntegerField(default=5, help_text="Sustain duration before alerting.")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('server', 'metric_type')

    def __str__(self):
        return f"{self.get_metric_type_display()} > {self.threshold_value} on {self.server.name}"

class ServerAlertState(TenantModel):
    """
    State machine storage for the escalating cooldown logic.
    """
    server = models.OneToOneField(Server, on_delete=models.CASCADE, primary_key=True, related_name='alert_state')
    consecutive_healthy_count = models.PositiveIntegerField(default=0)
    current_cooldown_tier = models.PositiveIntegerField(default=0, help_text="0=No active alert. 1-6=Escalating tiers.")
    last_alert_sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"State for {self.server.name} (Tier {self.current_cooldown_tier})"
