import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from django.urls import reverse
from django_redis import get_redis_connection
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase
from accounts.models import Company
from monitoring.models import Server
from telemetry.ingestion import TELEMETRY_QUEUE_KEY
from telemetry.models import MetricLog
from telemetry.tasks import process_telemetry_batch

User = get_user_model()


class TelemetryIngestionTests(APITestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name='Company A')
        self.company_b = Company.objects.create(name='Company B')

        self.user_a = User.objects.create_user(username='agent_a', password='password123', company=self.company_a)
        self.user_b = User.objects.create_user(username='agent_b', password='password123', company=self.company_b)
        self.user_no_company = User.objects.create_user(username='orphan_user', password='password123')

        self.token_a = Token.objects.create(user=self.user_a)
        self.token_b = Token.objects.create(user=self.user_b)
        self.token_no_company = Token.objects.create(user=self.user_no_company)

        self.server_a = Server.unscoped.create(name='Server A', company=self.company_a)
        self.server_b = Server.unscoped.create(name='Server B', company=self.company_b)

        self.ingest_url = reverse('telemetry-ingest')
        self.config_url = reverse('telemetry-config')

        self.redis_con = get_redis_connection('default')
        self.redis_con.delete(TELEMETRY_QUEUE_KEY)
        self.redis_con.delete(f'{TELEMETRY_QUEUE_KEY}:processing')

    def tearDown(self):
        self.redis_con.delete(TELEMETRY_QUEUE_KEY)
        self.redis_con.delete(f'{TELEMETRY_QUEUE_KEY}:processing')

    def _auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

    @patch('monitoring.tasks.evaluate_metrics_batch.delay')
    def test_ingest_and_worker_persists_with_server_derived_company_id(self, mock_evaluate):
        self._auth(self.token_a)
        payload = {
            'server': str(self.server_a.id),
            'cpu_usage': 45.5,
            'ram_usage': 60.1,
            'disk_io': 12.3,
        }

        response = self.client.post(self.ingest_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(self.redis_con.llen(TELEMETRY_QUEUE_KEY), 1)

        queued_item = json.loads(self.redis_con.lindex(TELEMETRY_QUEUE_KEY, 0))
        self.assertEqual(queued_item['server_id'], str(self.server_a.id))
        self.assertEqual(queued_item['company_id'], str(self.company_a.id))

        count = process_telemetry_batch()
        self.assertEqual(count, 1)
        self.assertEqual(self.redis_con.llen(TELEMETRY_QUEUE_KEY), 0)
        self.assertEqual(self.redis_con.llen(f'{TELEMETRY_QUEUE_KEY}:processing'), 0)

        log = MetricLog.unscoped.get(server=self.server_a)
        self.assertEqual(log.company_id, self.company_a.id)
        self.assertEqual(log.cpu_usage, 45.5)
        self.assertEqual(log.ram_usage, 60.1)
        mock_evaluate.assert_called_once()

    @patch('monitoring.tasks.evaluate_metrics_batch.delay')
    def test_ingest_ignores_forged_client_company(self, mock_evaluate):
        self._auth(self.token_a)
        payload = {
            'server': str(self.server_a.id),
            'company': str(self.company_b.id),
            'company_id': str(self.company_b.id),
            'cpu_usage': 30.0,
            'ram_usage': 40.0,
        }

        response = self.client.post(self.ingest_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        count = process_telemetry_batch()
        self.assertEqual(count, 1)

        log = MetricLog.unscoped.get(server=self.server_a)
        self.assertEqual(log.company_id, self.company_a.id)
        self.assertNotEqual(log.company_id, self.company_b.id)
        mock_evaluate.assert_called_once()

    def test_ingest_rejects_cross_tenant_server_id(self):
        self._auth(self.token_a)
        payload = {
            'server': str(self.server_b.id),
            'company': str(self.company_b.id),
            'cpu_usage': 50.0,
            'ram_usage': 50.0,
        }

        response = self.client.post(self.ingest_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.redis_con.llen(TELEMETRY_QUEUE_KEY), 0)

    def test_ingest_rejects_user_without_company(self):
        self._auth(self.token_no_company)
        payload = {
            'server': str(self.server_a.id),
            'cpu_usage': 50.0,
            'ram_usage': 50.0,
        }

        response = self.client.post(self.ingest_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.redis_con.llen(TELEMETRY_QUEUE_KEY), 0)

    def test_ingest_invalid_data(self):
        self._auth(self.token_a)
        payload = {
            'server': str(self.server_a.id),
            'cpu_usage': 150.0,
            'ram_usage': 50.0,
        }

        response = self.client.post(self.ingest_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cpu_usage', response.data)

    def test_ingest_missing_server(self):
        self._auth(self.token_a)
        payload = {
            'cpu_usage': 10.0,
            'ram_usage': 20.0,
        }

        response = self.client.post(self.ingest_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('server', response.data)

    def test_config_endpoint_enforces_tenant_isolation_and_validates_uuid(self):
        self._auth(self.token_a)

        own_resp = self.client.get(self.config_url, HTTP_X_SERVER_ID=str(self.server_a.id))
        self.assertEqual(own_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(own_resp.data['telemetry_cadence'], self.server_a.telemetry_cadence)

        cross_resp = self.client.get(self.config_url, HTTP_X_SERVER_ID=str(self.server_b.id))
        self.assertEqual(cross_resp.status_code, status.HTTP_404_NOT_FOUND)

        invalid_resp = self.client.get(self.config_url, HTTP_X_SERVER_ID='not-a-uuid')
        self.assertEqual(invalid_resp.status_code, status.HTTP_400_BAD_REQUEST)


class WebSocketConsumerAuthTests(TransactionTestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name='WS Company A')
        self.company_b = Company.objects.create(name='WS Company B')
        self.user_a = User.objects.create_user(username='ws_user_a', password='password123', company=self.company_a)
        self.server_a = Server.unscoped.create(name='WS Server A', company=self.company_a)
        self.server_b = Server.unscoped.create(name='WS Server B', company=self.company_b)

    def tearDown(self):
        from django.db import connections

        connections.close_all()

    @patch('monitoring.tasks.record_system_event.delay')
    async def test_ws_connect_succeeds_for_own_server_and_consumes_ticket_once(self, mock_event):
        from asgiref.sync import sync_to_async
        from channels.testing import WebsocketCommunicator
        from accounts.authentication import ticket_manager
        from config.asgi import application

        ticket = await sync_to_async(ticket_manager.create_ticket)(str(self.user_a.id))
        communicator = WebsocketCommunicator(
            application,
            f'/ws/telemetry/{self.server_a.id}/?ticket={ticket}',
            headers=[(b'origin', b'http://localhost:5173')],
        )
        try:
            connected, _ = await communicator.connect(timeout=10)
            self.assertTrue(connected)
        finally:
            await communicator.disconnect()

        replay = WebsocketCommunicator(
            application,
            f'/ws/telemetry/{self.server_a.id}/?ticket={ticket}',
            headers=[(b'origin', b'http://localhost:5173')],
        )
        try:
            replay_connected, _ = await replay.connect(timeout=10)
            self.assertFalse(replay_connected)
        finally:
            await replay.disconnect()

        mock_event.assert_not_called()

    @patch('monitoring.tasks.record_system_event.delay')
    async def test_ws_connect_rejects_cross_tenant_server(self, mock_event):
        from asgiref.sync import sync_to_async
        from channels.testing import WebsocketCommunicator
        from accounts.authentication import ticket_manager
        from config.asgi import application

        ticket = await sync_to_async(ticket_manager.create_ticket)(str(self.user_a.id))
        communicator = WebsocketCommunicator(
            application,
            f'/ws/telemetry/{self.server_b.id}/?ticket={ticket}',
            headers=[(b'origin', b'http://localhost:5173')],
        )
        try:
            connected, close_code = await communicator.connect(timeout=15)
            self.assertFalse(connected)
            self.assertEqual(close_code, 4403)
        finally:
            await communicator.disconnect()

        mock_event.assert_called_once()

    async def test_ws_connect_rejects_disallowed_origin_and_missing_ticket(self):
        from asgiref.sync import sync_to_async
        from channels.testing import WebsocketCommunicator
        from accounts.authentication import ticket_manager
        from config.asgi import application

        ticket = await sync_to_async(ticket_manager.create_ticket)(str(self.user_a.id))
        bad_origin = WebsocketCommunicator(
            application,
            f'/ws/telemetry/{self.server_a.id}/?ticket={ticket}',
            headers=[(b'origin', b'https://evil.example')],
        )
        try:
            bad_origin_connected, _ = await bad_origin.connect(timeout=10)
            self.assertFalse(bad_origin_connected)
        finally:
            await bad_origin.disconnect()

        no_ticket = WebsocketCommunicator(
            application,
            f'/ws/telemetry/{self.server_a.id}/',
            headers=[(b'origin', b'http://localhost:5173')],
        )
        try:
            no_ticket_connected, _ = await no_ticket.connect(timeout=10)
            self.assertFalse(no_ticket_connected)
        finally:
            await no_ticket.disconnect()


class TelemetryIngestThrottleTests(APITestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.company_a = Company.objects.create(name='Throttle Co A')
        self.company_b = Company.objects.create(name='Throttle Co B')
        self.user_a = User.objects.create_user(username='throttle_user', password='password123', company=self.company_a)
        self.token_a = Token.objects.create(user=self.user_a)
        self.server_a1 = Server.unscoped.create(name='Svr A1', company=self.company_a)
        self.server_a2 = Server.unscoped.create(name='Svr A2', company=self.company_a)
        self.server_b1 = Server.unscoped.create(name='Svr B1', company=self.company_b)
        self.ingest_url = reverse('telemetry-ingest')
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token_a.key}')
        self.redis_con = get_redis_connection('default')
        self.redis_con.delete(TELEMETRY_QUEUE_KEY)

    def tearDown(self):
        from django.core.cache import cache

        cache.clear()
        self.redis_con.delete(TELEMETRY_QUEUE_KEY)

    def test_ingest_is_throttled_per_server_not_per_user(self):
        from telemetry.throttling import ServerIngestRateThrottle

        with patch.object(ServerIngestRateThrottle, 'get_rate', return_value='2/min'):
            for _ in range(2):
                resp = self.client.post(
                    self.ingest_url,
                    {'server': str(self.server_a1.id), 'cpu_usage': 20.0, 'ram_usage': 30.0},
                    format='json',
                )
                self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)

            throttled = self.client.post(
                self.ingest_url,
                {'server': str(self.server_a1.id), 'cpu_usage': 20.0, 'ram_usage': 30.0},
                format='json',
            )
            self.assertEqual(throttled.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

            for _ in range(2):
                resp = self.client.post(
                    self.ingest_url,
                    {'server': str(self.server_a2.id), 'cpu_usage': 25.0, 'ram_usage': 35.0},
                    format='json',
                )
                self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)

            throttled_a2 = self.client.post(
                self.ingest_url,
                {'server': str(self.server_a2.id), 'cpu_usage': 25.0, 'ram_usage': 35.0},
                format='json',
            )
            self.assertEqual(throttled_a2.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_invalid_or_cross_tenant_server_ids_share_user_bucket(self):
        import uuid
        from telemetry.throttling import ServerIngestRateThrottle

        with patch.object(ServerIngestRateThrottle, 'get_rate', return_value='2/min'):
            resp1 = self.client.post(
                self.ingest_url,
                {'server': str(self.server_b1.id), 'cpu_usage': 20.0, 'ram_usage': 30.0},
                format='json',
            )
            self.assertEqual(resp1.status_code, status.HTTP_400_BAD_REQUEST)

            resp2 = self.client.post(
                self.ingest_url,
                {'server': str(uuid.uuid4()), 'cpu_usage': 20.0, 'ram_usage': 30.0},
                format='json',
            )
            self.assertEqual(resp2.status_code, status.HTTP_400_BAD_REQUEST)

            resp3 = self.client.post(
                self.ingest_url,
                {'server': str(uuid.uuid4()), 'cpu_usage': 20.0, 'ram_usage': 30.0},
                format='json',
            )
            self.assertEqual(resp3.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


class EmailConfigurationTests(APITestCase):
    def test_email_settings_have_non_default_smtp_configuration(self):
        from django.conf import settings

        self.assertEqual(settings.EMAIL_HOST, 'mailpit')
        self.assertEqual(settings.EMAIL_PORT, 1025)
        self.assertEqual(settings.DEFAULT_FROM_EMAIL, 'alerts@sysroar.local')
        self.assertGreater(getattr(settings, 'EMAIL_TIMEOUT', 0), 0)

    def test_email_strategy_dispatches_alert_and_resolution_with_configured_sender(self):
        from django.conf import settings
        from django.core import mail
        from django.test import override_settings
        from monitoring.models import AlertRule
        from telemetry.notifications.email import EmailStrategy

        company = Company.objects.create(name='Mail Co')
        server = Server.unscoped.create(name='app-01', ip_address='10.0.0.5', company=company)
        rule = AlertRule.unscoped.create(
            company=company,
            server=server,
            metric_type='cpu',
            threshold_value=80.0,
            notification_type='EMAIL',
            notification_target='ops@example.com',
        )

        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            strategy = EmailStrategy()
            self.assertTrue(strategy.send_alert(server, rule, {'value': 95.0, 'timestamp': '2026-11-25T12:00:00Z'}))
            self.assertTrue(strategy.send_resolution(server, rule, {'timestamp': '2026-11-25T12:05:00Z'}))

        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(mail.outbox[0].to, ['ops@example.com'])
        self.assertIn('Alert: CPU', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[1].from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertIn('RESOLVED: CPU', mail.outbox[1].subject)
