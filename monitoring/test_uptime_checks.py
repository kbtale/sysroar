from unittest.mock import MagicMock, patch
import pytest
from rest_framework.test import APIClient
from accounts.models import Company, User
from monitoring.models import Incident, UptimeCheck
from monitoring.uptime import execute_uptime_check


@pytest.mark.django_db
def test_uptime_check_crud_ssrf_and_cross_tenant_isolation():
    company_a = Company.objects.create(name='Uptime Alpha')
    company_b = Company.objects.create(name='Uptime Beta')
    admin_a = User.objects.create_user(
        username='up_a',
        email='a@up.test',
        password='Password123!',
        company=company_a,
        role=User.ROLE_ADMIN,
    )
    admin_b = User.objects.create_user(
        username='up_b',
        email='b@up.test',
        password='Password123!',
        company=company_b,
        role=User.ROLE_ADMIN,
    )

    client_a = APIClient()
    client_a.force_authenticate(user=admin_a)

    blocked = client_a.post(
        '/api/monitoring/uptime-checks/',
        data={
            'name': 'Metadata SSRF',
            'check_type': 'http',
            'target': 'http://169.254.169.254/latest/meta-data/',
        },
        format='json',
    )
    assert blocked.status_code == 400

    with patch(
        'monitoring.serializers.validate_webhook_url',
        return_value=('status.example.com', '93.184.216.34', 443),
    ):
        created = client_a.post(
            '/api/monitoring/uptime-checks/',
            data={
                'name': 'Public API Health',
                'check_type': 'http',
                'target': 'https://status.example.com/health',
                'expected_status': 200,
                'expected_keyword': 'ok',
            },
            format='json',
        )
    assert created.status_code == 201
    check_id = created.data['id']

    client_b = APIClient()
    client_b.force_authenticate(user=admin_b)
    assert client_b.get(f'/api/monitoring/uptime-checks/{check_id}/').status_code == 404
    assert client_b.post(f'/api/monitoring/uptime-checks/{check_id}/run/').status_code == 404
    assert client_b.get(f'/api/monitoring/uptime-checks/{check_id}/results/').status_code == 404

    check_obj = UptimeCheck.unscoped.get(id=check_id)
    bad_resp = MagicMock(status_code=503, text='service unavailable')
    with (
        patch('monitoring.uptime.validate_webhook_url', return_value=('status.example.com', '93.184.216.34', 443)),
        patch('monitoring.uptime.requests.get', return_value=bad_resp),
        patch('monitoring.uptime._inspect_ssl_expiry_days', return_value=45),
    ):
        res_down = execute_uptime_check(check_obj)
    assert res_down.status == 'down'
    assert Incident.unscoped.filter(company=company_a, uptime_check=check_obj, status='open').count() == 1

    good_resp = MagicMock(status_code=200, text='status: ok')
    with (
        patch('monitoring.uptime.validate_webhook_url', return_value=('status.example.com', '93.184.216.34', 443)),
        patch('monitoring.uptime.requests.get', return_value=good_resp),
        patch('monitoring.uptime._inspect_ssl_expiry_days', return_value=45),
    ):
        res_up = execute_uptime_check(check_obj)
    assert res_up.status == 'up'
    assert Incident.unscoped.filter(company=company_a, uptime_check=check_obj, status='resolved').count() == 1

    results_resp = client_a.get(f'/api/monitoring/uptime-checks/{check_id}/results/')
    assert results_resp.status_code == 200
    assert len(results_resp.data) == 2

    ssl_check = UptimeCheck.unscoped.create(
        company=company_a,
        name='Expiring TLS',
        check_type='ssl',
        target='tls.example.com',
        port=443,
        ssl_expiry_warning_days=14,
    )
    with (
        patch('monitoring.uptime._resolve_target_host', return_value='93.184.216.34'),
        patch('monitoring.uptime._inspect_ssl_expiry_days', return_value=5),
    ):
        ssl_res = execute_uptime_check(ssl_check)
    assert ssl_res.status == 'degraded'
    assert ssl_res.ssl_expiry_days == 5
