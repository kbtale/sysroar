import json
from datetime import timedelta
import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.models import Company, User
from monitoring.models import Incident, Server, UptimeCheck, UptimeCheckResult


@pytest.mark.django_db
def test_status_page_crud_cross_tenant_rejection_and_zero_leakage():
    company_a = Company.objects.create(name='Status Co A')
    company_b = Company.objects.create(name='Status Co B')
    admin_a = User.objects.create_user(
        username='sp_a',
        email='secret-admin@internal.corp',
        password='Password123!',
        company=company_a,
        role='admin',
    )
    admin_b = User.objects.create_user(
        username='sp_b',
        password='Password123!',
        company=company_b,
        role='admin',
    )

    now = timezone.now()
    srv_a = Server.unscoped.create(
        company=company_a,
        name='Core API Cluster',
        hostname='internal-prod-01.vpc.local',
        ip_address='10.42.99.11',
        last_ping=now - timedelta(seconds=10),
    )
    srv_b = Server.unscoped.create(company=company_b, name='Tenant B DB')
    chk_a = UptimeCheck.unscoped.create(
        company=company_a,
        name='Public Website',
        check_type='http',
        target='https://internal-secret-origin.example.com/healthz?token=abc',
        last_status='up',
        last_checked_at=now,
    )
    UptimeCheckResult.unscoped.create(
        company=company_a,
        check_obj=chk_a,
        status='up',
        latency_ms=42.5,
        status_code=200,
        checked_at=now,
    )
    Incident.unscoped.create(
        company=company_a,
        server=srv_a,
        title='Elevated latency resolved',
        severity='warning',
        status='resolved',
        opened_at=now - timedelta(hours=2),
        resolved_at=now - timedelta(hours=1),
    )

    client_a = APIClient()
    client_a.force_authenticate(user=admin_a)

    cross_m2m = client_a.post(
        '/api/monitoring/status-pages/',
        data={
            'slug': 'cross-attempt',
            'title': 'Cross Attempt',
            'servers': [str(srv_b.id)],
        },
        format='json',
    )
    assert cross_m2m.status_code == 400

    created = client_a.post(
        '/api/monitoring/status-pages/',
        data={
            'slug': 'acme-status',
            'title': 'Acme Platform Status',
            'description': 'Live service health for Acme.',
            'is_public': True,
            'accent_color': '#0ea5e9',
            'show_incidents': True,
            'servers': [str(srv_a.id)],
            'uptime_checks': [str(chk_a.id)],
        },
        format='json',
    )
    assert created.status_code == 201
    page_id = created.data['id']

    client_b = APIClient()
    client_b.force_authenticate(user=admin_b)
    assert client_b.get(f'/api/monitoring/status-pages/{page_id}/').status_code == 404
    assert client_b.delete(f'/api/monitoring/status-pages/{page_id}/').status_code == 404

    anon = APIClient()
    pub = anon.get('/api/public/status/acme-status/')
    assert pub.status_code == 200
    assert pub.data['title'] == 'Acme Platform Status'
    assert pub.data['overall_status'] == 'operational'
    assert len(pub.data['components']) == 2
    assert len(pub.data['incidents']) == 1

    raw = json.dumps(pub.data)
    assert '10.42.99.11' not in raw
    assert 'internal-prod-01.vpc.local' not in raw
    assert 'internal-secret-origin.example.com' not in raw
    assert 'secret-admin@internal.corp' not in raw
    assert str(company_a.id) not in raw

    patch_resp = client_a.patch(
        f'/api/monitoring/status-pages/{page_id}/',
        data={'is_public': False},
        format='json',
    )
    assert patch_resp.status_code == 200
    assert anon.get('/api/public/status/acme-status/').status_code == 404
