import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.models import Company, User
from monitoring.models import AgentKey, Server
from telemetry.models import MetricLog


@pytest.mark.django_db
def test_agent_v2_details_ingest_and_server_retrieve_isolation():
    company_a = Company.objects.create(name='Alpha Co')
    company_b = Company.objects.create(name='Beta Co')
    user_a = User.objects.create_user(
        username='alpha_admin',
        email='a@alpha.test',
        password='Password123!',
        company=company_a,
        role=User.ROLE_ADMIN,
    )
    user_b = User.objects.create_user(
        username='beta_admin',
        email='b@beta.test',
        password='Password123!',
        company=company_b,
        role=User.ROLE_ADMIN,
    )
    server_a = Server.unscoped.create(company=company_a, name='alpha-node-01')
    _, raw_key = AgentKey.generate(server=server_a)

    v2_details = {
        'cpu_iowait_percent': 1.8,
        'cpu_steal_percent': 0.2,
        'disk_iops_read': 142.5,
        'disk_iops_write': 88.0,
        'disk_util_percent': 19.4,
        'process_count': 134,
        'top_processes': [
            {'pid': 412, 'name': 'postgres', 'cpu_percent': 14.2, 'mem_bytes': 536870912},
        ],
        'mounts': [
            {
                'mount': '/',
                'used_percent': 48.2,
                'total_bytes': 107374182400,
                'available_bytes': 55619829760,
                'inodes_used_percent': 9.5,
            }
        ],
        'temperatures': [{'label': 'Package id 0', 'celsius': 54.0}],
        'systemd_units': [{'name': 'docker.service', 'active_state': 'active', 'sub_state': 'running'}],
        'docker_containers': [
            {
                'id': 'a1b2c3d4e5f6',
                'name': 'api-gateway',
                'image': 'nginx:1.27',
                'state': 'running',
                'status': 'Up 4 hours',
                'cpu_percent': 3.4,
                'mem_bytes': 67108864,
                'mem_limit_bytes': 536870912,
                'mem_percent': 12.5,
            }
        ],
    }

    MetricLog.unscoped.create(
        company=company_a,
        server=server_a,
        timestamp=timezone.now(),
        cpu_usage=34.5,
        ram_usage=61.0,
        details=v2_details,
    )

    client_a = APIClient()
    client_a.force_authenticate(user=user_a)
    resp_a = client_a.get(f'/api/monitoring/servers/{server_a.id}/')
    assert resp_a.status_code == 200
    assert resp_a.data['latest_details']['process_count'] == 134
    assert resp_a.data['latest_details']['docker_containers'][0]['name'] == 'api-gateway'
    assert resp_a.data['latest_details']['systemd_units'][0]['name'] == 'docker.service'
    assert resp_a.data['latest_details']['mounts'][0]['inodes_used_percent'] == 9.5

    client_b = APIClient()
    client_b.force_authenticate(user=user_b)
    resp_b = client_b.get(f'/api/monitoring/servers/{server_a.id}/')
    assert resp_b.status_code == 404

    agent_client = APIClient()
    oversized = agent_client.post(
        '/api/telemetry/ingest/batch/',
        data={
            'samples': [
                {
                    'server': str(server_a.id),
                    'cpu_usage': 10.0,
                    'ram_usage': 20.0,
                    'details': {'blob': 'x' * 70000},
                }
            ]
        },
        format='json',
        HTTP_AUTHORIZATION=f'AgentKey {raw_key}',
    )
    assert oversized.status_code == 400
