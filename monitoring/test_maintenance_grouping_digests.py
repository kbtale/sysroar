from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, patch
import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.models import Company, User
from monitoring.models import (
    AlertRule,
    Incident,
    MaintenanceWindow,
    NotificationOutbox,
    Server,
    UptimeCheck,
)
from monitoring.tasks import evaluate_alert_rules, send_daily_digests
from monitoring.uptime import execute_uptime_check
from telemetry.models import MetricLog


@pytest.mark.django_db
def test_maintenance_window_crud_suppression_and_cross_tenant():
    company_a = Company.objects.create(name='Maint Co A')
    company_b = Company.objects.create(name='Maint Co B')
    admin_a = User.objects.create_user(username='mw_a', password='Password123!', company=company_a, role='admin')
    admin_b = User.objects.create_user(username='mw_b', password='Password123!', company=company_b, role='admin')

    server_a = Server.unscoped.create(company=company_a, name='api-prod-1', tags=['prod', 'web'])
    server_b = Server.unscoped.create(company=company_b, name='db-prod-2', tags=['prod'])

    client_a = APIClient()
    client_a.force_authenticate(user=admin_a)

    now = timezone.now()
    cross_resp = client_a.post(
        '/api/monitoring/maintenance-windows/',
        data={
            'name': 'Cross Tenant Attempt',
            'scope': 'server',
            'server': str(server_b.id),
            'starts_at': (now - timedelta(minutes=5)).isoformat(),
            'ends_at': (now + timedelta(minutes=30)).isoformat(),
        },
        format='json',
    )
    assert cross_resp.status_code == 400

    created = client_a.post(
        '/api/monitoring/maintenance-windows/',
        data={
            'name': 'Prod Deploy Window',
            'scope': 'tag',
            'tag_filter': 'prod',
            'recurrence': 'daily',
            'starts_at': (now - timedelta(minutes=10)).isoformat(),
            'ends_at': (now + timedelta(minutes=50)).isoformat(),
            'reason': 'Nightly deploy',
        },
        format='json',
    )
    assert created.status_code == 201
    window_id = created.data['id']
    assert created.data['is_currently_active'] is True

    client_b = APIClient()
    client_b.force_authenticate(user=admin_b)
    assert client_b.get(f'/api/monitoring/maintenance-windows/{window_id}/').status_code == 404
    assert client_b.delete(f'/api/monitoring/maintenance-windows/{window_id}/').status_code == 404

    window = MaintenanceWindow.unscoped.get(id=window_id)
    assert window.matches_time(now + timedelta(days=1, minutes=5)) is True
    assert window.matches_time(now + timedelta(days=1, hours=3)) is False

    rule_a = AlertRule.unscoped.create(
        company=company_a,
        server=server_a,
        metric_type='cpu',
        operator='gt',
        threshold_value=80.0,
        duration_minutes=0,
        notification_type='EMAIL',
        notification_target='ops@example.com',
    )
    MetricLog.unscoped.create(
        company=company_a,
        server=server_a,
        cpu_usage=95.0,
        ram_usage=50.0,
        disk_usage=40.0,
        timestamp=now - timedelta(seconds=10),
    )

    with patch('monitoring.tasks.deliver_notification_outbox.delay'):
        res = evaluate_alert_rules(now=now)
    assert res['enqueued'] == 0
    assert Incident.unscoped.filter(company=company_a, rule=rule_a).count() == 0

    check_a = UptimeCheck.unscoped.create(
        company=company_a,
        name='Prod API',
        check_type='http',
        target='https://prod.example.com/health',
        tags=['prod'],
    )
    bad_resp = MagicMock(status_code=503, text='down')
    with (
        patch('monitoring.uptime.validate_webhook_url', return_value=('prod.example.com', '93.184.216.34', 443)),
        patch('monitoring.uptime.requests.get', return_value=bad_resp),
        patch('monitoring.uptime._inspect_ssl_expiry_days', return_value=40),
    ):
        execute_uptime_check(check_a, now=now)
    assert Incident.unscoped.filter(company=company_a, uptime_check=check_a).count() == 0


@pytest.mark.django_db
def test_alert_grouping_consolidates_simultaneous_channel_alerts():
    company = Company.objects.create(name='Grouping Co')
    srv1 = Server.unscoped.create(company=company, name='web-1')
    srv2 = Server.unscoped.create(company=company, name='web-2')
    now = timezone.now()

    AlertRule.unscoped.create(
        company=company,
        server=srv1,
        metric_type='cpu',
        operator='gt',
        threshold_value=80.0,
        duration_minutes=0,
        severity='warning',
        notification_type='EMAIL',
        notification_target='oncall@example.com',
    )
    AlertRule.unscoped.create(
        company=company,
        server=srv2,
        metric_type='ram',
        operator='gt',
        threshold_value=85.0,
        duration_minutes=0,
        severity='critical',
        notification_type='EMAIL',
        notification_target='oncall@example.com',
    )
    MetricLog.unscoped.create(
        company=company,
        server=srv1,
        cpu_usage=92.0,
        ram_usage=40.0,
        disk_usage=30.0,
        timestamp=now - timedelta(seconds=10),
    )
    MetricLog.unscoped.create(
        company=company,
        server=srv2,
        cpu_usage=30.0,
        ram_usage=96.0,
        disk_usage=30.0,
        timestamp=now - timedelta(seconds=10),
    )

    with patch('monitoring.tasks.deliver_notification_outbox.delay'):
        res = evaluate_alert_rules(now=now)
    assert res['enqueued'] == 1
    outbox = NotificationOutbox.unscoped.get(company=company)
    assert outbox.payload['grouped_count'] == 2
    assert len(outbox.payload['grouped_alerts']) == 2
    assert outbox.payload['severity'] == 'critical'


@pytest.mark.django_db
def test_daily_digest_sends_once_at_configured_utc_hour():
    company = Company.objects.create(
        name='Digest Co',
        digest_enabled=True,
        digest_hour_utc=9,
        digest_email='digest@example.com',
    )
    right_hour = datetime(2026, 6, 15, 9, 5, tzinfo=dt_timezone.utc)
    Server.unscoped.create(company=company, name='node-1', last_ping=right_hour - timedelta(minutes=1))

    mail.outbox.clear()
    wrong_hour = datetime(2026, 6, 15, 7, 0, tzinfo=dt_timezone.utc)
    assert send_daily_digests(now=wrong_hour)['sent'] == 0
    assert len(mail.outbox) == 0

    assert send_daily_digests(now=right_hour)['sent'] == 1
    assert len(mail.outbox) == 1
    assert 'Digest Co' in mail.outbox[0].subject
    assert '1/1 active servers online' in mail.outbox[0].body
    assert mail.outbox[0].to == ['digest@example.com']

    assert send_daily_digests(now=right_hour + timedelta(minutes=20))['sent'] == 0
    assert len(mail.outbox) == 1
