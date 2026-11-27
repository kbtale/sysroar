from datetime import timedelta
from unittest.mock import MagicMock, patch
import pytest
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.models import Company, User
from monitoring.models import AlertRule, Incident, Server
from monitoring.tasks import evaluate_alert_rules


@pytest.mark.django_db
@override_settings(LOG_BACKEND='none')
def test_logs_disabled_by_default_returns_empty():
    company = Company.objects.create(name='No Logs Co')
    user = User.objects.create_user(username='nolog_u', password='Password123!', company=company, role='viewer')
    client = APIClient()
    client.force_authenticate(user=user)

    st = client.get('/api/logs/status/')
    assert st.status_code == 200
    assert st.data == {'enabled': False, 'backend': 'none', 'healthy': True}

    q = client.get('/api/logs/query/')
    assert q.status_code == 200
    assert q.data['enabled'] is False
    assert q.data['entries'] == []


@pytest.mark.django_db
@override_settings(LOG_BACKEND='loki', LOKI_URL='http://loki.internal:3100')
def test_loki_backend_enforces_scope_org_id_and_cross_tenant_server_filter():
    company_a = Company.objects.create(name='Loki Co A')
    company_b = Company.objects.create(name='Loki Co B')
    user_a = User.objects.create_user(username='loki_a', password='Password123!', company=company_a, role='admin')
    srv_a = Server.unscoped.create(company=company_a, name='api-1')
    srv_b = Server.unscoped.create(company=company_b, name='other-1')

    client = APIClient()
    client.force_authenticate(user=user_a)

    assert client.get(f'/api/logs/query/?server_id={srv_b.id}').status_code == 404

    fake_loki_resp = MagicMock()
    fake_loki_resp.raise_for_status.return_value = None
    fake_loki_resp.json.return_value = {
        'data': {
            'result': [
                {
                    'stream': {
                        'company_id': str(company_a.id),
                        'server_id': str(srv_a.id),
                        'level': 'ERROR',
                        'source': 'nginx',
                    },
                    'values': [['1764259200000000000', 'upstream timed out']],
                }
            ]
        }
    }

    with patch('telemetry.logs.loki.requests.get', return_value=fake_loki_resp) as mock_get:
        resp = client.get(f'/api/logs/query/?server_id={srv_a.id}&level=ERROR&q=upstream')
    assert resp.status_code == 200
    assert resp.data['backend'] == 'loki'
    assert len(resp.data['entries']) == 1
    assert resp.data['entries'][0]['message'] == 'upstream timed out'
    assert 'company_id' not in resp.data['entries'][0]['labels']
    assert mock_get.call_args.kwargs['headers']['X-Scope-OrgID'] == str(company_a.id)


@pytest.mark.django_db
@override_settings(LOG_BACKEND='elasticsearch', ELASTICSEARCH_URL='http://es.internal:9200')
def test_elasticsearch_backend_injects_company_id_filter():
    company = Company.objects.create(name='ES Co')
    user = User.objects.create_user(username='es_u', password='Password123!', company=company, role='admin')
    client = APIClient()
    client.force_authenticate(user=user)

    fake_es_resp = MagicMock()
    fake_es_resp.raise_for_status.return_value = None
    fake_es_resp.json.return_value = {
        'hits': {
            'hits': [
                {
                    '_source': {
                        '@timestamp': '2026-11-27T12:00:00Z',
                        'company_id': str(company.id),
                        'server_id': 'srv-1',
                        'level': 'WARN',
                        'source': 'syslog',
                        'message': 'disk queue depth high',
                    }
                }
            ]
        }
    }

    with patch('telemetry.logs.elasticsearch.requests.post', return_value=fake_es_resp) as mock_post:
        resp = client.get('/api/logs/query/?q=disk&level=WARN')
    assert resp.status_code == 200
    assert len(resp.data['entries']) == 1
    sent_filters = mock_post.call_args.kwargs['json']['query']['bool']['filter']
    assert {'term': {'company_id': str(company.id)}} in sent_filters


@pytest.mark.django_db
@override_settings(LOG_BACKEND='loki', LOKI_URL='http://loki.internal:3100')
def test_log_count_alert_rule_triggers_incident_and_outbox():
    company = Company.objects.create(name='Log Alert Co')
    srv = Server.unscoped.create(company=company, name='worker-1')
    rule = AlertRule.unscoped.create(
        company=company,
        server=srv,
        metric_type='log_count',
        operator='gt',
        threshold_value=5.0,
        duration_minutes=0,
        log_level='ERROR',
        log_query='OOMKilled',
        severity='critical',
        notification_type='EMAIL',
        notification_target='sre@example.com',
    )

    fake_count_resp = MagicMock()
    fake_count_resp.raise_for_status.return_value = None
    fake_count_resp.json.return_value = {'data': {'result': [{'value': [1764259200, '12']}]}}

    now = timezone.now()
    with (
        patch('telemetry.logs.loki.requests.get', return_value=fake_count_resp) as mock_get,
        patch('monitoring.tasks.deliver_notification_outbox.delay'),
    ):
        res = evaluate_alert_rules(now=now)
    assert res['enqueued'] == 1
    assert mock_get.call_args.kwargs['headers']['X-Scope-OrgID'] == str(company.id)
    assert Incident.unscoped.filter(company=company, rule=rule, status='open').count() == 1
    assert timedelta(minutes=5).total_seconds() == 300
