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
    tags = models.JSONField(default=list, blank=True)
    last_ping = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} ({self.ip_address})'


class NotificationChannel(TenantModel):
    CHANNEL_CHOICES = [
        ('EMAIL', 'Email'),
        ('WEBHOOK', 'Webhook'),
        ('SLACK', 'Slack'),
        ('DISCORD', 'Discord'),
        ('TEAMS', 'Microsoft Teams'),
        ('TELEGRAM', 'Telegram'),
        ('PAGERDUTY', 'PagerDuty'),
        ('OPSGENIE', 'Opsgenie'),
        ('NTFY', 'ntfy'),
        ('GOTIFY', 'Gotify'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128)
    channel_type = models.CharField(max_length=16, choices=CHANNEL_CHOICES, default='EMAIL')
    target = models.CharField(max_length=512)
    webhook_secret = models.CharField(max_length=255, blank=True, default='')
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.channel_type == 'WEBHOOK' and not self.webhook_secret:
            self.webhook_secret = f'whsec_{secrets.token_urlsafe(32)}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.name} ({self.channel_type})'


class AlertRule(TenantModel):
    METRIC_CHOICES = [
        ('cpu', 'CPU Usage (%)'),
        ('ram', 'RAM Usage (%)'),
        ('disk', 'Disk Usage (%)'),
        ('disk_io', 'Disk I/O (MB)'),
        ('swap', 'Swap Usage (%)'),
        ('load', 'Load Average (1m)'),
        ('no_data', 'Host Offline / No Data'),
        ('log_count', 'Log Match Count'),
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

    NOTIFICATION_CHOICES = NotificationChannel.CHANNEL_CHOICES

    SCOPE_CHOICES = [
        ('server', 'Server'),
        ('tag', 'Tag'),
        ('all', 'All Servers'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    server = models.ForeignKey(Server, on_delete=models.CASCADE, related_name='alert_rules', null=True, blank=True)
    scope = models.CharField(max_length=16, choices=SCOPE_CHOICES, default='server')
    tag_filter = models.CharField(max_length=64, blank=True, default='')
    channel = models.ForeignKey(
        NotificationChannel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='alert_rules',
    )
    metric_type = models.CharField(max_length=16, choices=METRIC_CHOICES)
    operator = models.CharField(max_length=4, choices=OPERATOR_CHOICES, default='gt')
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default='warning')
    aggregation = models.CharField(max_length=8, choices=AGGREGATION_CHOICES, default='avg')
    threshold_value = models.FloatField()
    hysteresis_margin = models.FloatField(default=0.0)
    duration_minutes = models.PositiveIntegerField(default=5)
    log_query = models.CharField(max_length=255, blank=True, default='')
    log_level = models.CharField(max_length=16, blank=True, default='')
    is_active = models.BooleanField(default=True)

    notification_type = models.CharField(
        max_length=16,
        choices=NOTIFICATION_CHOICES,
        default='EMAIL',
    )
    notification_target = models.CharField(
        max_length=512,
        blank=True,
        null=True,
    )
    webhook_secret = models.CharField(max_length=255, blank=True, default='')

    def save(self, *args, **kwargs):
        if self.channel_id is not None and self.channel is not None:
            self.notification_type = self.channel.channel_type
            self.notification_target = self.channel.target
            if self.channel.webhook_secret:
                self.webhook_secret = self.channel.webhook_secret
        if self.notification_type == 'WEBHOOK' and not self.webhook_secret:
            self.webhook_secret = f'whsec_{secrets.token_urlsafe(32)}'
        super().save(*args, **kwargs)

    def __str__(self):
        if self.server_id:
            target_label = self.server.name
        elif self.scope == 'tag':
            target_label = f'tag:{self.tag_filter}'
        else:
            target_label = 'all'
        return (
            f'[{self.severity.upper()}] {self.get_metric_type_display()} '
            f'{self.get_operator_display()} {self.threshold_value} on {target_label}'
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


class AuditLog(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
    )
    actor_username = models.CharField(max_length=150, blank=True, default='')
    action = models.CharField(max_length=64, db_index=True)
    resource_type = models.CharField(max_length=64, db_index=True)
    resource_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    correlation_id = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', '-created_at']),
        ]

    def __str__(self):
        return f'{self.actor_username} {self.action} {self.resource_type}:{self.resource_id}'


class UptimeCheck(TenantModel):
    CHECK_TYPE_CHOICES = [
        ('http', 'HTTP / HTTPS'),
        ('tcp', 'TCP Port'),
        ('ping', 'Ping'),
        ('dns', 'DNS Lookup'),
        ('ssl', 'SSL Certificate'),
    ]

    STATUS_CHOICES = [
        ('up', 'Up'),
        ('degraded', 'Degraded'),
        ('down', 'Down'),
        ('unknown', 'Unknown'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128)
    check_type = models.CharField(max_length=16, choices=CHECK_TYPE_CHOICES, default='http')
    target = models.CharField(max_length=512)
    port = models.PositiveIntegerField(null=True, blank=True)
    expected_status = models.PositiveIntegerField(default=200)
    expected_keyword = models.CharField(max_length=255, blank=True, default='')
    ssl_expiry_warning_days = models.PositiveIntegerField(default=14)
    interval_seconds = models.PositiveIntegerField(default=60)
    timeout_seconds = models.PositiveIntegerField(default=10)
    allow_private_targets = models.BooleanField(default=False)
    tags = models.JSONField(default=list, blank=True)
    channel = models.ForeignKey(
        NotificationChannel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uptime_checks',
    )
    is_active = models.BooleanField(default=True, db_index=True)
    last_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='unknown')
    last_latency_ms = models.FloatField(null=True, blank=True)
    last_ssl_expiry_days = models.IntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=512, blank=True, default='')
    last_checked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} ({self.check_type}:{self.target})'


class UptimeCheckResult(TenantModel):
    STATUS_CHOICES = [
        ('up', 'Up'),
        ('degraded', 'Degraded'),
        ('down', 'Down'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    check_obj = models.ForeignKey(UptimeCheck, on_delete=models.CASCADE, related_name='results')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES)
    latency_ms = models.FloatField(null=True, blank=True)
    status_code = models.PositiveIntegerField(null=True, blank=True)
    ssl_expiry_days = models.IntegerField(null=True, blank=True)
    error_message = models.CharField(max_length=512, blank=True, default='')
    checked_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['company', 'check_obj', '-checked_at'], name='monitoring_u_co_chk_idx'),
        ]

    def __str__(self):
        return f'{self.check_obj_id} {self.status} @ {self.checked_at}'


class Incident(TenantModel):
    STATUS_CHOICES = [
        ('open', 'Open'),
        ('acknowledged', 'Acknowledged'),
        ('resolved', 'Resolved'),
    ]

    SEVERITY_CHOICES = [
        ('warning', 'Warning'),
        ('critical', 'Critical'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    server = models.ForeignKey(Server, on_delete=models.CASCADE, null=True, blank=True, related_name='incidents')
    uptime_check = models.ForeignKey(
        UptimeCheck,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='incidents',
    )
    rule = models.ForeignKey(AlertRule, on_delete=models.SET_NULL, null=True, blank=True, related_name='incidents')
    title = models.CharField(max_length=255)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES, default='warning', db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='open', db_index=True)
    trigger_value = models.FloatField(null=True, blank=True)
    opened_at = models.DateTimeField(default=timezone.now, db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='acknowledged_incidents',
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resolved_incidents',
    )

    class Meta:
        ordering = ['-opened_at']
        indexes = [
            models.Index(fields=['company', 'status', '-opened_at']),
        ]

    def __str__(self):
        return f'[{self.severity.upper()}] {self.title} ({self.status})'


class IncidentComment(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='incident_comments',
    )
    author_username = models.CharField(max_length=150, blank=True, default='')
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class AlertSilence(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, null=True, blank=True, related_name='silences')
    server = models.ForeignKey(Server, on_delete=models.CASCADE, null=True, blank=True, related_name='silences')
    reason = models.CharField(max_length=255, blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_silences',
    )
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-ends_at']

    @classmethod
    def is_silenced(cls, company_id, server_id=None, rule_id=None, now=None) -> bool:
        now = now or timezone.now()
        active = cls.unscoped.filter(company_id=company_id, starts_at__lte=now, ends_at__gt=now)
        for silence in active.only('server_id', 'rule_id'):
            server_match = silence.server_id is None or (server_id is not None and silence.server_id == server_id)
            rule_match = silence.rule_id is None or (rule_id is not None and silence.rule_id == rule_id)
            if server_match and rule_match:
                return True
        return False


class MaintenanceWindow(TenantModel):
    SCOPE_CHOICES = [
        ('all', 'All Resources'),
        ('server', 'Single Server'),
        ('tag', 'Server Tag'),
    ]

    RECURRENCE_CHOICES = [
        ('none', 'One-time'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128)
    scope = models.CharField(max_length=16, choices=SCOPE_CHOICES, default='all')
    server = models.ForeignKey(
        Server,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='maintenance_windows',
    )
    tag_filter = models.CharField(max_length=64, blank=True, default='')
    recurrence = models.CharField(max_length=16, choices=RECURRENCE_CHOICES, default='none')
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField(db_index=True)
    reason = models.CharField(max_length=255, blank=True, default='')
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_maintenance_windows',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-starts_at']
        indexes = [
            models.Index(fields=['company', 'is_active', 'starts_at'], name='monitoring_mw_co_act_idx'),
        ]

    def matches_time(self, now=None) -> bool:
        now = now or timezone.now()
        if not self.is_active or self.ends_at <= self.starts_at:
            return False
        if self.recurrence == 'none':
            return self.starts_at <= now < self.ends_at
        if now < self.starts_at:
            return False
        duration = self.ends_at - self.starts_at
        if self.recurrence == 'daily':
            period = timedelta(days=1)
        elif self.recurrence == 'weekly':
            period = timedelta(days=7)
        else:
            return False
        elapsed = now - self.starts_at
        offset = elapsed - period * int(elapsed // period)
        return offset < duration

    def matches_target(self, server=None, tags=None) -> bool:
        if self.scope == 'all':
            return True
        if self.scope == 'server':
            return server is not None and self.server_id == getattr(server, 'id', server)
        if self.scope == 'tag':
            needle = (self.tag_filter or '').strip().lower()
            if not needle:
                return False
            candidate_tags = tags if tags is not None else getattr(server, 'tags', None) or []
            return any(str(t).strip().lower() == needle for t in candidate_tags)
        return False

    @classmethod
    def is_in_maintenance(cls, company_id, server=None, tags=None, now=None) -> bool:
        now = now or timezone.now()
        windows = cls.unscoped.filter(company_id=company_id, is_active=True, starts_at__lte=now)
        for window in windows:
            if window.matches_time(now) and window.matches_target(server=server, tags=tags):
                return True
        return False

    def __str__(self):
        return f'{self.name} ({self.scope}/{self.recurrence})'


class StatusPage(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=128)
    description = models.TextField(blank=True, default='')
    is_public = models.BooleanField(default=True, db_index=True)
    accent_color = models.CharField(max_length=16, default='#0ea5e9')
    show_incidents = models.BooleanField(default=True)
    servers = models.ManyToManyField(Server, blank=True, related_name='status_pages')
    uptime_checks = models.ManyToManyField(UptimeCheck, blank=True, related_name='status_pages')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['title', 'slug']

    def __str__(self):
        return f'{self.title} (/status/{self.slug})'
