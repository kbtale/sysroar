import secrets
import pytest
from channels.testing import WebsocketCommunicator
from django.test import Client
from accounts.models import Company, User
from monitoring.metrics import WS_ACTIVE_CONNECTIONS
from monitoring.models import Incident, Server, UptimeCheck
from telemetry.consumers import CompanyTelemetryConsumer


@pytest.mark.django_db
def test_metrics_endpoint_disabled_without_token(settings):
    settings.METRICS_AUTH_TOKEN = ''
    client = Client()
    response = client.get('/metrics')
    assert response.status_code == 403


@pytest.mark.django_db
def test_metrics_endpoint_rejects_missing_or_invalid_bearer(settings):
    settings.METRICS_AUTH_TOKEN = secrets.token_hex(16)
    client = Client()

    no_header = client.get('/metrics')
    assert no_header.status_code == 401

    bad_header = client.get('/metrics', HTTP_AUTHORIZATION='Bearer invalid-value')
    assert bad_header.status_code == 401


@pytest.mark.django_db
def test_metrics_endpoint_exports_dogfood_platform_gauges(settings):
    expected = secrets.token_hex(16)
    settings.METRICS_AUTH_TOKEN = expected

    company = Company.objects.create(name='Dogfood Ops')
    s1 = Server.unscoped.create(company=company, name='dogfood-web-01', is_active=True)
    Server.unscoped.create(company=company, name='dogfood-db-01', is_active=True)
    Server.unscoped.create(company=company, name='dogfood-retired', is_active=False)

    Incident.unscoped.create(company=company, server=s1, title='High CPU', status='open', severity='critical')
    Incident.unscoped.create(company=company, server=s1, title='High RAM', status='acknowledged', severity='warning')
    Incident.unscoped.create(company=company, server=s1, title='Old Issue', status='resolved', severity='warning')

    UptimeCheck.unscoped.create(
        company=company,
        name='Down Probe',
        target='https://down.example.com',
        is_active=True,
        last_status='down',
    )
    UptimeCheck.unscoped.create(
        company=company,
        name='Up Probe',
        target='https://up.example.com',
        is_active=True,
        last_status='up',
    )
    UptimeCheck.unscoped.create(
        company=company,
        name='Disabled Down Probe',
        target='https://disabled.example.com',
        is_active=False,
        last_status='down',
    )

    client = Client()
    response = client.get('/metrics', HTTP_AUTHORIZATION=f'Bearer {expected}')
    assert response.status_code == 200
    body = response.content.decode('utf-8')

    assert 'sysroar_active_servers_total 2.0' in body
    assert 'sysroar_open_incidents_total 2.0' in body
    assert 'sysroar_uptime_checks_down_total 1.0' in body
    assert 'sysroar_db_up 1.0' in body
    assert 'sysroar_redis_up 1.0' in body
    assert 'sysroar_ws_active_connections' in body


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_ws_active_connections_gauge_tracks_lifecycle():
    company = await Company.objects.acreate(name='WS Gauge Co')
    user = await User.objects.acreate(username='ws-gauge-user', company=company)
    before = WS_ACTIVE_CONNECTIONS._value.get()

    unauth = WebsocketCommunicator(CompanyTelemetryConsumer.as_asgi(), '/ws/telemetry/')
    connected_unauth, _ = await unauth.connect()
    assert not connected_unauth
    assert WS_ACTIVE_CONNECTIONS._value.get() == before

    comm = WebsocketCommunicator(CompanyTelemetryConsumer.as_asgi(), '/ws/telemetry/')
    comm.scope['user'] = user
    connected, _ = await comm.connect()
    assert connected
    assert WS_ACTIVE_CONNECTIONS._value.get() == before + 1

    await comm.disconnect()
    assert WS_ACTIVE_CONNECTIONS._value.get() == before
