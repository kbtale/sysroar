import asyncio
from unittest.mock import patch
import pytest
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from accounts.authentication import ticket_manager
from accounts.models import Company, CompanyInvite, User
from config.asgi import application
from monitoring.models import AgentKey, AlertRule, AuditLog, EnrollmentToken, Server
from telemetry.notifications.ssrf import SSRFBlockedError, validate_webhook_url

UserModel = get_user_model()


@pytest.fixture
def security_fixture(db):
    cache.clear()
    company_a = Company.objects.create(name='Matrix Tenant A')
    company_b = Company.objects.create(name='Matrix Tenant B')

    owner_a = UserModel.objects.create(
        username='m_owner_a',
        email='owner_a@example.com',
        password='!',
        company=company_a,
        role=User.ROLE_OWNER,
    )
    member_a = UserModel.objects.create(
        username='m_member_a',
        email='member_a@example.com',
        password='!',
        company=company_a,
        role=User.ROLE_MEMBER,
    )
    viewer_a = UserModel.objects.create(
        username='m_viewer_a',
        email='viewer_a@example.com',
        password='!',
        company=company_a,
        role=User.ROLE_VIEWER,
    )
    owner_b = UserModel.objects.create(
        username='m_owner_b',
        email='owner_b@example.com',
        password='!',
        company=company_b,
        role=User.ROLE_OWNER,
    )

    server_a = Server.unscoped.create(name='matrix-a-1', company=company_a, is_active=True)
    server_b = Server.unscoped.create(name='matrix-b-1', company=company_b, is_active=True)
    rule_b = AlertRule.unscoped.create(
        company=company_b,
        server=server_b,
        metric_type='cpu',
        threshold_value=80.0,
        notification_type='EMAIL',
        notification_target='ops-b@example.com',
    )
    enroll_b, _ = EnrollmentToken.generate(company=company_b, name='enroll-b', created_by=owner_b)
    key_a, raw_key_a = AgentKey.generate(server=server_a, created_by=owner_a)
    key_b, _ = AgentKey.generate(server=server_b, created_by=owner_b)
    invite_b, _ = CompanyInvite.generate(company=company_b, email='b@example.com', role=User.ROLE_MEMBER)
    audit_b = AuditLog.unscoped.create(
        company=company_b,
        actor=owner_b,
        actor_username=owner_b.username,
        action='server.created',
        resource_type='server',
        resource_id=str(server_b.id),
    )

    def make_client(user=None, agent_key=None):
        client = APIClient()
        if user is not None:
            token, _ = Token.objects.get_or_create(user=user)
            client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        elif agent_key is not None:
            client.credentials(HTTP_AUTHORIZATION=f'AgentKey {agent_key}')
        return client

    yield {
        'company_a': company_a,
        'company_b': company_b,
        'owner_a': owner_a,
        'member_a': member_a,
        'viewer_a': viewer_a,
        'owner_b': owner_b,
        'server_a': server_a,
        'server_b': server_b,
        'rule_b': rule_b,
        'enroll_b': enroll_b,
        'key_a': key_a,
        'raw_key_a': raw_key_a,
        'key_b': key_b,
        'invite_b': invite_b,
        'audit_b': audit_b,
        'client_owner_a': make_client(user=owner_a),
        'client_member_a': make_client(user=member_a),
        'client_viewer_a': make_client(user=viewer_a),
        'client_owner_b': make_client(user=owner_b),
        'client_agent_a': make_client(agent_key=raw_key_a),
        'client_anon': APIClient(),
    }
    cache.clear()


@pytest.mark.parametrize(
    ('method', 'path_builder', 'payload_builder', 'headers_builder', 'expected_statuses'),
    [
        ('get', lambda f: f"/api/monitoring/servers/{f['server_b'].id}/", None, None, (404,)),
        ('patch', lambda f: f"/api/monitoring/servers/{f['server_b'].id}/", lambda f: {'name': 'pwn'}, None, (404,)),
        ('delete', lambda f: f"/api/monitoring/servers/{f['server_b'].id}/", None, None, (404,)),
        ('get', lambda f: f"/api/monitoring/rules/{f['rule_b'].id}/", None, None, (404,)),
        (
            'post',
            lambda f: '/api/monitoring/rules/',
            lambda f: {'server': str(f['server_b'].id), 'metric_type': 'cpu', 'threshold_value': 50.0},
            None,
            (400,),
        ),
        (
            'patch',
            lambda f: f"/api/monitoring/rules/{f['rule_b'].id}/",
            lambda f: {'threshold_value': 1.0},
            None,
            (404,),
        ),
        ('delete', lambda f: f"/api/monitoring/rules/{f['rule_b'].id}/", None, None, (404,)),
        ('post', lambda f: f"/api/monitoring/rules/{f['rule_b'].id}/test-webhook/", None, None, (404,)),
        ('get', lambda f: f"/api/monitoring/enrollment-tokens/{f['enroll_b'].id}/", None, None, (404,)),
        ('post', lambda f: f"/api/monitoring/enrollment-tokens/{f['enroll_b'].id}/revoke/", None, None, (404,)),
        ('get', lambda f: f"/api/monitoring/agent-keys/{f['key_b'].id}/", None, None, (404,)),
        ('post', lambda f: f"/api/monitoring/agent-keys/{f['key_b'].id}/revoke/", None, None, (404,)),
        ('post', lambda f: '/api/monitoring/agent-keys/', lambda f: {'server': str(f['server_b'].id)}, None, (404,)),
        (
            'post',
            lambda f: '/api/monitoring/agent-keys/rotate/',
            lambda f: {'server': str(f['server_b'].id)},
            None,
            (404,),
        ),
        ('get', lambda f: f"/api/monitoring/audit-logs/{f['audit_b'].id}/", None, None, (404,)),
        ('get', lambda f: f"/api/accounts/invites/{f['invite_b'].id}/", None, None, (404,)),
        ('delete', lambda f: f"/api/accounts/invites/{f['invite_b'].id}/", None, None, (404,)),
        ('get', lambda f: f"/api/accounts/members/{f['owner_b'].id}/", None, None, (404,)),
        ('patch', lambda f: f"/api/accounts/members/{f['owner_b'].id}/", lambda f: {'role': 'viewer'}, None, (404,)),
        ('get', lambda f: f"/api/accounts/companies/{f['company_b'].id}/", None, None, (404,)),
        ('patch', lambda f: f"/api/accounts/companies/{f['company_b'].id}/", lambda f: {'name': 'pwn'}, None, (404,)),
        (
            'post',
            lambda f: '/api/telemetry/ingest/',
            lambda f: {'server': str(f['server_b'].id), 'cpu_usage': 10.0, 'ram_usage': 20.0},
            None,
            (400,),
        ),
        (
            'post',
            lambda f: '/api/telemetry/ingest/batch/',
            lambda f: {'samples': [{'server': str(f['server_b'].id), 'cpu_usage': 10.0, 'ram_usage': 20.0}]},
            None,
            (400,),
        ),
        (
            'post',
            lambda f: '/api/telemetry/inventory/',
            lambda f: {'server': str(f['server_b'].id), 'hostname': 'spoofed'},
            None,
            (400,),
        ),
        (
            'get',
            lambda f: '/api/telemetry/config/',
            None,
            lambda f: {'HTTP_X_SERVER_ID': str(f['server_b'].id)},
            (404,),
        ),
    ],
)
def test_cross_tenant_isolation_matrix(
    security_fixture,
    method,
    path_builder,
    payload_builder,
    headers_builder,
    expected_statuses,
):
    client = security_fixture['client_owner_a']
    path = path_builder(security_fixture)
    payload = payload_builder(security_fixture) if payload_builder else None
    headers = headers_builder(security_fixture) if headers_builder else {}
    resp = getattr(client, method)(path, data=payload, format='json', **headers)
    assert resp.status_code in expected_statuses, (method, path, resp.status_code, resp.data)


@pytest.mark.parametrize(
    ('method', 'path'),
    [
        ('get', '/api/monitoring/servers/'),
        ('post', '/api/monitoring/servers/'),
        ('get', '/api/monitoring/rules/'),
        ('post', '/api/monitoring/rules/'),
        ('get', '/api/monitoring/agent-keys/'),
        ('post', '/api/monitoring/agent-keys/'),
        ('get', '/api/monitoring/enrollment-tokens/'),
        ('post', '/api/monitoring/enrollment-tokens/'),
        ('get', '/api/monitoring/audit-logs/'),
        ('get', '/api/accounts/auth/me/'),
        ('post', '/api/accounts/auth/ticket/'),
        ('get', '/api/accounts/invites/'),
        ('get', '/api/accounts/members/'),
        ('get', '/api/accounts/companies/'),
    ],
)
def test_agent_key_denied_on_all_monitoring_and_accounts_endpoints(security_fixture, method, path):
    resp = getattr(security_fixture['client_agent_a'], method)(path, data={}, format='json')
    assert resp.status_code == 401


@pytest.mark.parametrize(
    ('method', 'path'),
    [
        ('get', '/api/monitoring/servers/'),
        ('get', '/api/monitoring/rules/'),
        ('get', '/api/monitoring/agent-keys/'),
        ('get', '/api/monitoring/enrollment-tokens/'),
        ('get', '/api/monitoring/audit-logs/'),
        ('get', '/api/accounts/auth/me/'),
        ('post', '/api/accounts/auth/ticket/'),
        ('get', '/api/accounts/invites/'),
        ('get', '/api/accounts/members/'),
        ('get', '/api/accounts/companies/'),
        ('post', '/api/telemetry/ingest/'),
        ('post', '/api/telemetry/ingest/batch/'),
        ('post', '/api/telemetry/inventory/'),
        ('get', '/api/telemetry/config/'),
    ],
)
def test_unauthenticated_denied_on_all_protected_endpoints(security_fixture, method, path):
    resp = getattr(security_fixture['client_anon'], method)(path, data={}, format='json')
    assert resp.status_code in (401, 403)


@pytest.mark.parametrize(
    ('role_client', 'method', 'path', 'payload'),
    [
        ('client_viewer_a', 'post', '/api/monitoring/servers/', {'name': 'blocked'}),
        ('client_viewer_a', 'post', '/api/monitoring/rules/', {'metric_type': 'cpu', 'threshold_value': 90}),
        ('client_member_a', 'get', '/api/monitoring/agent-keys/', None),
        ('client_member_a', 'get', '/api/monitoring/enrollment-tokens/', None),
        ('client_member_a', 'get', '/api/monitoring/audit-logs/', None),
        ('client_member_a', 'get', '/api/accounts/invites/', None),
        ('client_member_a', 'get', '/api/accounts/members/', None),
    ],
)
def test_rbac_privilege_boundary_matrix(security_fixture, role_client, method, path, payload):
    resp = getattr(security_fixture[role_client], method)(path, data=payload, format='json')
    assert resp.status_code == 403


@pytest.mark.parametrize(
    'blocked_url',
    [
        'http://127.0.0.1/hook',
        'http://10.0.0.1/hook',
        'http://172.16.0.1/hook',
        'http://192.168.1.1/hook',
        'http://169.254.169.254/latest/meta-data/',
        'http://100.64.0.1/hook',
        'http://[::1]/hook',
        'http://[::ffff:127.0.0.1]/hook',
        'file:///etc/passwd',
        'gopher://127.0.0.1:6379/_PING',
    ],
)
def test_ssrf_deny_matrix(blocked_url):
    with pytest.raises(SSRFBlockedError):
        validate_webhook_url(blocked_url)


@pytest.mark.django_db(transaction=True)
def test_websocket_cross_tenant_rejection(security_fixture):
    from asgiref.sync import sync_to_async
    from django.db import connections

    owner_a = security_fixture['owner_a']
    server_b = security_fixture['server_b']
    ticket = ticket_manager.create_ticket(str(owner_a.id), session_epoch=owner_a.session_epoch)

    async def check_ws():
        communicator = WebsocketCommunicator(
            application,
            f'/ws/telemetry/{server_b.id}/?ticket={ticket}',
            headers=[(b'origin', b'http://localhost:5173')],
        )
        try:
            connected, close_code = await communicator.connect()
            assert not connected
            assert close_code == 4403
        finally:
            await communicator.disconnect()
            await sync_to_async(connections.close_all)()

    with patch('telemetry.consumers.record_system_event.delay'):
        asyncio.run(check_ws())


def test_audit_log_records_mutations_is_immutable_and_isolated(security_fixture):
    client_a = security_fixture['client_owner_a']
    client_b = security_fixture['client_owner_b']

    srv_resp = client_a.post('/api/monitoring/servers/', {'name': 'audited-srv'}, format='json')
    assert srv_resp.status_code == 201
    srv_id = srv_resp.data['id']

    key_resp = client_a.post('/api/monitoring/agent-keys/', {'server': srv_id}, format='json')
    assert key_resp.status_code == 201
    plaintext_key = key_resp.data['key']

    logs_a = client_a.get('/api/monitoring/audit-logs/')
    assert logs_a.status_code == 200
    actions_a = [item['action'] for item in logs_a.data['results']]
    assert 'server.created' in actions_a
    assert 'agent_key.created' in actions_a
    assert plaintext_key not in str(logs_a.data)

    logs_b = client_b.get('/api/monitoring/audit-logs/')
    assert logs_b.status_code == 200
    ids_b = {item['resource_id'] for item in logs_b.data['results']}
    assert srv_id not in ids_b

    assert client_a.post('/api/monitoring/audit-logs/', {'action': 'fake'}, format='json').status_code == 405
    first_log_id = logs_a.data['results'][0]['id']
    assert client_a.delete(f'/api/monitoring/audit-logs/{first_log_id}/').status_code == 405


def test_owasp_baseline_security_headers(security_fixture):
    with patch('telemetry.views.push_to_stream'):
        resp = security_fixture['client_owner_a'].get('/api/monitoring/servers/')
    assert resp.status_code == 200
    assert "default-src 'self'" in resp['Content-Security-Policy']
    assert "frame-ancestors 'none'" in resp['Content-Security-Policy']
    assert resp['X-Content-Type-Options'] == 'nosniff'
    assert resp['X-Frame-Options'] == 'DENY'
    assert resp['Referrer-Policy'] == 'same-origin'
    assert 'Permissions-Policy' in resp
    assert resp['Cross-Origin-Opener-Policy'] == 'same-origin'
    assert 'X-Powered-By' not in resp
    assert timezone.now() is not None
