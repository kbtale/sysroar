import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta
from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from accounts.models import TenantModel


def hash_credential(raw_value: str) -> str:
    return hashlib.sha256(raw_value.encode('utf-8')).hexdigest()


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
    webhook_secret = models.CharField(max_length=128, blank=True, default='')

    def save(self, *args, **kwargs):
        if self.notification_type == 'WEBHOOK' and not self.webhook_secret:
            self.webhook_secret = f'whsec_{secrets.token_urlsafe(32)}'
        super().save(*args, **kwargs)

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


class EnrollmentToken(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128)
    prefix = models.CharField(max_length=16, unique=True, db_index=True)
    token_hash = models.CharField(max_length=64, unique=True)
    max_uses = models.PositiveIntegerField(default=1, null=True, blank=True)
    uses_count = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_enrollment_tokens',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def generate(cls, company, name: str, created_by=None, max_uses=1, expires_in_hours: int | None = 24):
        prefix = f'sre_{secrets.token_hex(4)}'
        secret_part = secrets.token_urlsafe(32)
        plaintext = f'{prefix}.{secret_part}'
        expires_at = timezone.now() + timedelta(hours=expires_in_hours) if expires_in_hours else None
        token = cls.unscoped.create(
            company=company,
            name=name,
            prefix=prefix,
            token_hash=hash_credential(plaintext),
            max_uses=max_uses,
            expires_at=expires_at,
            created_by=created_by,
        )
        return token, plaintext

    def verify(self, plaintext: str, now=None) -> bool:
        now = now or timezone.now()
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and now >= self.expires_at:
            return False
        if self.max_uses is not None and self.uses_count >= self.max_uses:
            return False
        return hmac.compare_digest(hash_credential(plaintext), self.token_hash)

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=['revoked_at'])

    def __str__(self):
        return f'{self.name} ({self.prefix})'


class AgentKey(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='agent_keys')
    prefix = models.CharField(max_length=16, unique=True, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_agent_keys',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def generate(cls, server: Server, created_by=None):
        prefix = f'srk_{secrets.token_hex(4)}'
        secret_part = secrets.token_urlsafe(32)
        plaintext = f'{prefix}.{secret_part}'
        key = cls.unscoped.create(
            company_id=server.company_id,
            server=server,
            prefix=prefix,
            key_hash=hash_credential(plaintext),
            is_active=True,
            created_by=created_by,
        )
        return key, plaintext

    @classmethod
    def rotate(cls, server: Server, created_by=None):
        with transaction.atomic():
            cls.unscoped.filter(
                server=server,
                company_id=server.company_id,
                is_active=True,
            ).update(is_active=False, revoked_at=timezone.now())
            return cls.generate(server=server, created_by=created_by)

    def verify(self, plaintext: str) -> bool:
        if not self.is_active or self.revoked_at is not None:
            return False
        if not self.server.is_active:
            return False
        return hmac.compare_digest(hash_credential(plaintext), self.key_hash)

    def revoke(self):
        if self.is_active or self.revoked_at is None:
            self.is_active = False
            self.revoked_at = timezone.now()
            self.save(update_fields=['is_active', 'revoked_at'])

    def __str__(self):
        return f'AgentKey({self.prefix} -> {self.server_id})'
