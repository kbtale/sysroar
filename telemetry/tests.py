import json
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from django_redis import get_redis_connection
from accounts.models import Company
from monitoring.models import Server
from telemetry.ingestion import TELEMETRY_QUEUE_KEY

User = get_user_model()

class TelemetryIngestionTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Ingestion Test Co")
        self.user = User.objects.create_user(username="agent_user", company=self.company)
        self.server = Server.objects.create(name="Test SVR", company=self.company)
        self.client.force_authenticate(user=self.user)
        self.url = reverse('telemetry-ingest')
        
        # Clear the test queue
        self.redis_con = get_redis_connection("default")
        self.redis_con.delete(TELEMETRY_QUEUE_KEY)

    def test_ingest_success(self):
        """
        Verify that a valid payload returns 202 and is placed in Redis.
        """
        data = {
            "server": str(self.server.id),
            "cpu_usage": 45.5,
            "ram_usage": 60.1,
            "disk_io": 12.3
        }
        
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data['status'], 'accepted')
        
        # Verify Redis queue
        queue_len = self.redis_con.llen(TELEMETRY_QUEUE_KEY)
        self.assertEqual(queue_len, 1)
        
        queued_item = json.loads(self.redis_con.lindex(TELEMETRY_QUEUE_KEY, 0))
        self.assertEqual(queued_item['server'], str(self.server.id))
        self.assertEqual(queued_item['cpu_usage'], 45.5)

    def test_ingest_invalid_data(self):
        """
        Verify that invalid values (e.g., CPU > 100) return 400.
        """
        data = {
            "server": str(self.server.id),
            "cpu_usage": 150.0,
            "ram_usage": 50.0
        }
        
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cpu_usage', response.data)

    def test_ingest_missing_server(self):
        """
        Verify that missing server ID returns 400.
        """
        data = {
            "cpu_usage": 10.0,
            "ram_usage": 20.0
        }
        
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('server', response.data)

    def test_worker_batch_processing(self):
        """
        Verify that the Celery task correctly transfers data from Redis to PostgreSQL.
        """
        from telemetry.tasks import process_telemetry_batch
        from telemetry.models import MetricLog
        from telemetry.ingestion import push_to_redis_queue

        # Manually push data to Redis
        payload = {
            "server": str(self.server.id),
            "cpu_usage": 10.0,
            "ram_usage": 20.0,
            "timestamp": "2026-03-03T20:00:00Z",
            "company": str(self.company.id)
        }
        push_to_redis_queue(payload)
        
        # Assert Redis has it
        self.assertEqual(self.redis_con.llen(TELEMETRY_QUEUE_KEY), 1)
        
        # Trigger the Celery task
        count = process_telemetry_batch()
        
        # Assert outcomes
        self.assertEqual(count, 1)
        self.assertEqual(self.redis_con.llen(TELEMETRY_QUEUE_KEY), 0)
        self.assertTrue(MetricLog.objects.filter(server=self.server).exists())
