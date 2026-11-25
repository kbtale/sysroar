import json
from unittest.mock import patch
from django.contrib.auth import get_user_model
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
