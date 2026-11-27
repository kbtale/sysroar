import json
from unittest.mock import MagicMock, patch
import pytest
from rest_framework.test import APIClient
from accounts.models import Company, User
from monitoring.models import AlertRule, NotificationChannel, Server
from telemetry.notifications.dispatcher import NotificationDispatcher
from telemetry.notifications.providers import (
    DiscordStrategy,
    GotifyStrategy,
    NtfyStrategy,
    OpsgenieStrategy,
    PagerDutyStrategy,
    SlackStrategy,
    TeamsStrategy,
    TelegramStrategy,
)


@pytest.mark.parametrize(
    ('strategy_cls', 'target', 'secret', 'expected_header', 'expected_substring'),
    [
        (SlackStrategy, 'https://hooks.slack.com/services/T0/B0/XX', '', 'Content-Type', 'attachments'),
        (DiscordStrategy, 'https://discord.com/api/webhooks/1/tok', '', 'Content-Type', 'embeds'),
        (TeamsStrategy, 'https://outlook.office.com/webhook/abc', '', 'Content-Type', 'MessageCard'),
        (TelegramStrategy, '-100123456', '12345:bot-token', 'Content-Type', '"chat_id":"-100123456"'),
        (PagerDutyStrategy, '', 'pd-routing-key', 'Content-Type', '"event_action":"trigger"'),
        (OpsgenieStrategy, '', 'og-api-key', 'Authorization', 'GenieKey og-api-key'),
        (NtfyStrategy, 'https://ntfy.sh/sysroar-ops', 'tk_abc', 'Priority', 'urgent'),
        (GotifyStrategy, 'https://gotify.example.com', 'gotify-app-key', 'X-Gotify-Key', '"priority":8'),
    ],
)
def test_provider_payload_and_headers(strategy_cls, target, secret, expected_header, expected_substring):
    strategy = strategy_cls()
    url, body, headers = strategy.build_request(
        target=target,
        secret=secret,
        title='[SysRoar] CRITICAL: CPU on web-01',
        body='Host web-01 breached CPU threshold 85 with value 95.0.',
        severity='CRITICAL',
        dedup_key='sysroar-r1-s1',
        is_resolution=False,
    )
    assert url.startswith('https://')
    assert expected_header in headers
    decoded = body.decode('utf-8')
    assert expected_substring in decoded or expected_substring in headers.get(expected_header, '')


def test_opsgenie_and_pagerduty_resolution_payloads():
    pd_url, pd_body, _ = PagerDutyStrategy().build_request(
        target='',
        secret='rk',
        title='Resolved',
        body='OK',
        severity='WARNING',
        dedup_key='dk-1',
        is_resolution=True,
    )
    assert pd_url.endswith('/v2/enqueue')
    assert json.loads(pd_body)['event_action'] == 'resolve'

    og_url, _, og_headers = OpsgenieStrategy().build_request(
        target='',
        secret='ogk',
        title='Resolved',
        body='OK',
        severity='WARNING',
        dedup_key='dk-1',
        is_resolution=True,
    )
    assert '/dk-1/close?identifierType=alias' in og_url
    assert og_headers['Authorization'] == 'GenieKey ogk'


@pytest.mark.django_db
def test_expanded_channel_crud_ssrf_and_dispatch():
    company_a = Company.objects.create(name='Alpha')
    company_b = Company.objects.create(name='Beta')
    admin_a = User.objects.create_user(
        username='ch_admin_a',
        email='a@alpha.test',
        password='Password123!',
        company=company_a,
        role=User.ROLE_ADMIN,
    )
    admin_b = User.objects.create_user(
        username='ch_admin_b',
        email='b@beta.test',
        password='Password123!',
        company=company_b,
        role=User.ROLE_ADMIN,
    )

    client_a = APIClient()
    client_a.force_authenticate(user=admin_a)

    ssrf_resp = client_a.post(
        '/api/monitoring/channels/',
        data={
            'name': 'Bad Slack',
            'channel_type': 'SLACK',
            'target': 'http://127.0.0.1:8080/hook',
        },
        format='json',
    )
    assert ssrf_resp.status_code == 400

    missing_secret = client_a.post(
        '/api/monitoring/channels/',
        data={
            'name': 'Incomplete Telegram',
            'channel_type': 'TELEGRAM',
            'target': '-100999',
        },
        format='json',
    )
    assert missing_secret.status_code == 400

    with patch('monitoring.serializers.validate_webhook_url', return_value=('hooks.slack.com', '54.230.1.1', 443)):
        created = client_a.post(
            '/api/monitoring/channels/',
            data={
                'name': 'Ops Slack',
                'channel_type': 'SLACK',
                'target': 'https://hooks.slack.com/services/T0/B0/XYZ',
            },
            format='json',
        )
    assert created.status_code == 201
    channel_id = created.data['id']

    mock_resp = MagicMock(status_code=200)
    with patch('telemetry.notifications.providers.send_safe_webhook_post', return_value=mock_resp) as post_mock:
        test_resp = client_a.post(f'/api/monitoring/channels/{channel_id}/test/')
    assert test_resp.status_code == 200
    assert test_resp.data['delivered'] is True
    assert post_mock.called

    client_b = APIClient()
    client_b.force_authenticate(user=admin_b)
    assert client_b.post(f'/api/monitoring/channels/{channel_id}/test/').status_code == 404

    server_a = Server.unscoped.create(company=company_a, name='api-01')
    channel_obj = NotificationChannel.unscoped.get(id=channel_id)
    rule = AlertRule.unscoped.create(
        company=company_a,
        server=server_a,
        channel=channel_obj,
        metric_type='cpu',
        threshold_value=80.0,
    )
    with patch('telemetry.notifications.providers.send_safe_webhook_post', return_value=mock_resp):
        assert NotificationDispatcher.dispatch_alert(server_a, rule, {'value': 91.2, 'severity': 'critical'}) is True
