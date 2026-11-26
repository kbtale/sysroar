import uuid
from django.db import models
from django.utils import timezone
from accounts.models import TenantModel


class Server(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    hostname = models.CharField(max_length=255, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    os_info = models.CharField(max_length=255, null=True, blank=True)
    kernel = models.CharField(max_length=255, null=True, blank=True)
    cpu_model = models.CharField(max_length=255, null=True, blank=True)
    cpu_cores = models.PositiveIntegerField(null=True, blank=True)
    total_ram_bytes = models.BigIntegerField(null=True, blank=True)
    agent_version = models.CharField(max_length=64, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    telemetry_cadence = models.PositiveIntegerField(default=30)
    log_level = models.CharField(max_length=20, default='INFO')
    last_ping = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} ({self.ip_address})'


class AlertRule(TenantModel):
    METRIC_CHOICES = [
        ('cpu', 'CPU Usage (%)'),
        ('ram', 'RAM Usage (%)'),
        ('disk', 'Disk Usage (%)'),
        ('disk_io', 'Disk I/O (MB)'),
        ('swap', 'Swap Usage (%)'),
        ('load', 'Load Average (1m)'),
        ('no_data', 'Host Offline / No Data'),
    ]

    OPERATOR_CHOICES = [
        ('gt', '>'),
        ('gte', '>='),
        ('lt', '<'),
        ('lte', '<='),
    ]

    SEVERITY_CHOICES = [
        ('warning', 'Warning'),
        ('critical', 'Critical'),
    ]

    AGGREGATION_CHOICES = [
        ('avg', 'Average'),
        ('max', 'Maximum'),
        ('min', 'Minimum'),
    ]

    NOTIFICATION_CHOICES = [
        ('EMAIL', 'Email'),
        ('WEBHOOK', 'Webhook'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='alert_rules')
    metric_type = models.CharField(max_length=16, choices=METRIC_CHOICES)
    operator = models.CharField(max_length=4, choices=OPERATOR_CHOICES, default='gt')
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default='warning')
    aggregation = models.CharField(max_length=8, choices=AGGREGATION_CHOICES, default='avg')
    threshold_value = models.FloatField()
    hysteresis_margin = models.FloatField(default=0.0)
    duration_minutes = models.PositiveIntegerField(default=5)
    is_active = models.BooleanField(default=True)

    notification_type = models.CharField(
        max_length=10,
        choices=NOTIFICATION_CHOICES,
        default='EMAIL',
    )
    notification_target = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    def __str__(self):
        return (
            f'[{self.severity.upper()}] {self.get_metric_type_display()} '
            f'{self.get_operator_display()} {self.threshold_value} on {self.server.name}'
        )


class AlertState(TenantModel):
    STATUS_CHOICES = [
        ('OK', 'OK'),
        ('PENDING', 'Pending'),
        ('FIRING', 'Firing'),
        ('RESOLVED', 'Resolved'),
    ]

    rule = models.OneToOneField(AlertRule, on_delete=models.CASCADE, primary_key=True, related_name='alert_state')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='OK', db_index=True)
    pending_since = models.DateTimeField(null=True, blank=True)
    firing_since = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    consecutive_healthy_count = models.PositiveIntegerField(default=0)
    current_cooldown_tier = models.PositiveIntegerField(default=0)
    last_alert_sent_at = models.DateTimeField(null=True, blank=True)
    transition_history = models.JSONField(default=list, blank=True)
    is_flapping = models.BooleanField(default=False)
    last_value = models.FloatField(null=True, blank=True)
    last_evaluated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'AlertState({self.rule_id}: {self.status}, Tier {self.current_cooldown_tier})'


class NotificationOutbox(TenantModel):
    EVENT_CHOICES = [
        ('ALERT', 'Alert'),
        ('RESOLUTION', 'Resolution'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('DELIVERED', 'Delivered'),
        ('FAILED', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='outbox_notifications')
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name='outbox_notifications')
    event_type = models.CharField(max_length=16, choices=EVENT_CHOICES)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='PENDING', db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'next_attempt_at']),
        ]

    def __str__(self):
        return f'{self.event_type} for {self.rule_id} ({self.status})'


class ServerAlertState(TenantModel):
    server = models.OneToOneField(Server, on_delete=models.CASCADE, primary_key=True, related_name='alert_state')
    consecutive_healthy_count = models.PositiveIntegerField(default=0)
    current_cooldown_tier = models.PositiveIntegerField(default=0)
    last_alert_sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'State for {self.server.name} (Tier {self.current_cooldown_tier})'


class SystemEvent(models.Model):
    SEVERITY_CHOICES = [
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('CRITICAL', 'Critical'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=100, db_index=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='ERROR', db_index=True)
    context = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'System Event'
        verbose_name_plural = 'System Events'

    def __str__(self):
        return f"{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - [{self.severity}] {self.event_type}"
