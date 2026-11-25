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
