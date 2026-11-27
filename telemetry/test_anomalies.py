from datetime import timedelta
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.models import Company, User
from monitoring.models import Server
from telemetry.anomalies import compute_server_anomalies
from telemetry.models import MetricLog


@pytest.mark.django_db
def test_anomaly_hints_detect_spike_and_preserve_tenant_isolation():
    company_a = Company.objects.create(name='Anomaly Co A')
    company_b = Company.objects.create(name='Anomaly Co B')
    admin_a = User.objects.create_user(username='anom_a', password='Password123!', company=company_a, role='admin')

    srv_spike = Server.unscoped.create(company=company_a, name='spike-node')
    srv_steady = Server.unscoped.create(company=company_a, name='steady-node')
    srv_other = Server.unscoped.create(company=company_b, name='other-node')

    now = timezone.now()
    for i in range(12):
        ts = now - timedelta(hours=1 + i)
        MetricLog.unscoped.create(
            company=company_a,
            server=srv_spike,
            cpu_usage=18.0 + (i % 3),
            ram_usage=40.0,
            disk_usage=35.0,
            load_1m=0.5,
            timestamp=ts,
        )
        MetricLog.unscoped.create(
            company=company_a,
            server=srv_steady,
            cpu_usage=25.0 + (i % 2),
            ram_usage=45.0,
            disk_usage=35.0,
            load_1m=0.6,
            timestamp=ts,
        )
        MetricLog.unscoped.create(
            company=company_b,
            server=srv_other,
            cpu_usage=10.0,
            ram_usage=20.0,
            disk_usage=20.0,
            load_1m=0.2,
            timestamp=ts,
        )

    MetricLog.unscoped.create(
        company=company_a,
        server=srv_spike,
        cpu_usage=89.0,
        ram_usage=41.0,
        disk_usage=35.0,
        load_1m=0.6,
        timestamp=now - timedelta(minutes=2),
    )
    MetricLog.unscoped.create(
        company=company_a,
        server=srv_steady,
        cpu_usage=26.0,
        ram_usage=45.0,
        disk_usage=35.0,
        load_1m=0.6,
        timestamp=now - timedelta(minutes=2),
    )
    MetricLog.unscoped.create(
        company=company_b,
        server=srv_other,
        cpu_usage=95.0,
        ram_usage=90.0,
        disk_usage=80.0,
        load_1m=8.0,
        timestamp=now - timedelta(minutes=2),
    )

    result_a = compute_server_anomalies(company_a.id, [srv_spike.id, srv_steady.id, srv_other.id], now=now)
    assert str(srv_spike.id) in result_a
    assert result_a[str(srv_spike.id)][0]['metric'] == 'cpu'
    assert result_a[str(srv_spike.id)][0]['z_score'] >= 2.5
    assert str(srv_steady.id) not in result_a
    assert str(srv_other.id) not in result_a

    client = APIClient()
    client.force_authenticate(user=admin_a)
    detail = client.get(f'/api/monitoring/servers/{srv_spike.id}/')
    assert detail.status_code == 200
    assert len(detail.data['anomalies']) == 1
    assert detail.data['anomalies'][0]['metric'] == 'cpu'
