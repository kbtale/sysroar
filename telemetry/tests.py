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
from telemetry.consumer import IngestConsumer
from telemetry.ingestion import (
    TELEMETRY_DLQ_STREAM_KEY,
    TELEMETRY_STREAM_KEY,
    get_stream_metrics,
    push_to_stream,
    read_stream_batch,
)
from telemetry.models import MetricLog

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
        self.redis_con.delete(TELEMETRY_STREAM_KEY)
        self.redis_con.delete(TELEMETRY_DLQ_STREAM_KEY)

    def tearDown(self):
        self.redis_con.delete(TELEMETRY_STREAM_KEY)
        self.redis_con.delete(TELEMETRY_DLQ_STREAM_KEY)

    def _auth(self, token):
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

    def test_ingest_and_worker_persists_with_server_derived_company_id(self):
        self._auth(self.token_a)
        payload = {
            'server': str(self.server_a.id),
            'cpu_usage': 45.5,
            'ram_usage': 60.1,
            'disk_io': 12.3,
        }

        response = self.client.post(self.ingest_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(self.redis_con.xlen(TELEMETRY_STREAM_KEY), 1)

        entries = self.redis_con.xrange(TELEMETRY_STREAM_KEY)
        queued_item = json.loads(entries[0][1][b'payload'])
        self.assertEqual(queued_item['server_id'], str(self.server_a.id))
        self.assertEqual(queued_item['company_id'], str(self.company_a.id))

        consumer = IngestConsumer(consumer_name='test-consumer', block_ms=50)
        stats = consumer.run_once(reclaim=False)
        self.assertEqual(stats['persisted'], 1)
        self.assertEqual(stats['acked'], 1)
        self.assertEqual(get_stream_metrics()['pending_count'], 0)

        log = MetricLog.unscoped.get(server=self.server_a)
        self.assertEqual(log.company_id, self.company_a.id)
        self.assertEqual(log.cpu_usage, 45.5)
        self.assertEqual(log.ram_usage, 60.1)

    def test_ingest_ignores_forged_client_company(self):
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

        consumer = IngestConsumer(consumer_name='test-consumer', block_ms=50)
        stats = consumer.run_once(reclaim=False)
        self.assertEqual(stats['persisted'], 1)

        log = MetricLog.unscoped.get(server=self.server_a)
        self.assertEqual(log.company_id, self.company_a.id)
        self.assertNotEqual(log.company_id, self.company_b.id)

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
        self.assertEqual(self.redis_con.xlen(TELEMETRY_STREAM_KEY), 0)

    def test_ingest_rejects_user_without_company(self):
        self._auth(self.token_no_company)
        payload = {
            'server': str(self.server_a.id),
            'cpu_usage': 50.0,
            'ram_usage': 50.0,
        }

        response = self.client.post(self.ingest_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.redis_con.xlen(TELEMETRY_STREAM_KEY), 0)

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

        etag = own_resp['ETag']
        not_modified = self.client.get(
            self.config_url,
            HTTP_X_SERVER_ID=str(self.server_a.id),
            HTTP_IF_NONE_MATCH=etag,
        )
        self.assertEqual(not_modified.status_code, status.HTTP_304_NOT_MODIFIED)

    def test_inventory_endpoint_updates_host_metadata_and_blocks_cross_tenant(self):
        self._auth(self.token_a)
        inventory_url = reverse('telemetry-inventory')

        resp = self.client.post(
            inventory_url,
            {
                'server': str(self.server_a.id),
                'hostname': 'prod-web-01',
                'os_info': 'Ubuntu 24.04.1 LTS',
                'kernel': '6.8.0-45-generic',
                'cpu_model': 'AMD EPYC 7763',
                'cpu_cores': 8,
                'total_ram_bytes': 17179869184,
                'ip_address': '10.10.0.5',
                'agent_version': '0.1.0',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.server_a.refresh_from_db()
        self.assertEqual(self.server_a.hostname, 'prod-web-01')
        self.assertEqual(self.server_a.kernel, '6.8.0-45-generic')
        self.assertEqual(self.server_a.cpu_cores, 8)
        self.assertEqual(self.server_a.agent_version, '0.1.0')

        cross = self.client.post(
            inventory_url,
            {
                'server': str(self.server_b.id),
                'hostname': 'pwned-host',
            },
            format='json',
        )
        self.assertEqual(cross.status_code, status.HTTP_400_BAD_REQUEST)
        self.server_b.refresh_from_db()
        self.assertIsNone(self.server_b.hostname)


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
        self.redis_con.delete(TELEMETRY_STREAM_KEY)

    def tearDown(self):
        from django.core.cache import cache

        cache.clear()
        self.redis_con.delete(TELEMETRY_STREAM_KEY)

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


class TimescaleDbHypertableTests(TransactionTestCase):
    def test_metriclog_is_hypertable_with_policies_and_continuous_aggregates(self):
        from django.conf import settings
        from django.db import connection
        from telemetry import tasks as telemetry_tasks

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT hypertable_name FROM timescaledb_information.hypertables "
                "WHERE hypertable_name = 'telemetry_metriclog'"
            )
            self.assertEqual(cursor.fetchall(), [('telemetry_metriclog',)])

            cursor.execute(
                "SELECT proc_name FROM timescaledb_information.jobs "
                "WHERE hypertable_name = 'telemetry_metriclog'"
            )
            jobs = {row[0] for row in cursor.fetchall()}
            self.assertIn('policy_compression', jobs)
            self.assertIn('policy_retention', jobs)

            cursor.execute(
                "SELECT view_name FROM timescaledb_information.continuous_aggregates "
                "WHERE hypertable_name = 'telemetry_metriclog'"
            )
            caggs = {row[0] for row in cursor.fetchall()}
            self.assertEqual(caggs, {'telemetry_metric_1m', 'telemetry_metric_1h', 'telemetry_metric_1d'})

        self.assertFalse(hasattr(telemetry_tasks, 'rollup_telemetry_data'))
        self.assertFalse(hasattr(telemetry_tasks, 'purge_old_telemetry'))
        self.assertNotIn('hourly-telemetry-rollup', settings.CELERY_BEAT_SCHEDULE)
        self.assertNotIn('nightly-telemetry-purge', settings.CELERY_BEAT_SCHEDULE)

    def test_duplicate_server_timestamp_deduplicated_and_queries_tenant_scoped(self):
        from datetime import timedelta
        from django.db import connection
        from django.utils import timezone
        from telemetry.queries import query_metric_aggregates, query_metric_percentiles

        company_a = Company.objects.create(name='TS Co A', retention_days=7)
        company_b = Company.objects.create(name='TS Co B', retention_days=14)
        server_a = Server.unscoped.create(name='ts-a', company=company_a)
        server_b = Server.unscoped.create(name='ts-b', company=company_b)

        base_ts = timezone.now().replace(second=0, microsecond=0) - timedelta(minutes=5)
        rows = [
            MetricLog(company=company_a, server=server_a, timestamp=base_ts, cpu_usage=20.0, ram_usage=40.0),
            MetricLog(company=company_a, server=server_a, timestamp=base_ts, cpu_usage=99.0, ram_usage=99.0),
            MetricLog(
                company=company_a,
                server=server_a,
                timestamp=base_ts + timedelta(seconds=10),
                cpu_usage=80.0,
                ram_usage=60.0,
            ),
            MetricLog(company=company_b, server=server_b, timestamp=base_ts, cpu_usage=55.0, ram_usage=55.0),
        ]
        MetricLog.unscoped.bulk_create(rows, ignore_conflicts=True)

        self.assertEqual(MetricLog.unscoped.filter(server=server_a).count(), 2)

        with connection.cursor() as cursor:
            cursor.execute(
                "CALL refresh_continuous_aggregate('telemetry_metric_1m', %s, %s);",
                [base_ts - timedelta(minutes=5), timezone.now() + timedelta(minutes=1)],
            )

        window_start = base_ts - timedelta(minutes=1)
        aggs_a = query_metric_aggregates(company_a.id, server_a.id, bucket='1m', start=window_start)
        self.assertEqual(len(aggs_a), 1)
        self.assertEqual(aggs_a[0]['sample_count'], 2)
        self.assertAlmostEqual(aggs_a[0]['avg_cpu'], 50.0)
        self.assertAlmostEqual(aggs_a[0]['min_cpu'], 20.0)
        self.assertAlmostEqual(aggs_a[0]['max_cpu'], 80.0)

        cross_aggs = query_metric_aggregates(company_a.id, server_b.id, bucket='1m', start=window_start)
        self.assertEqual(cross_aggs, [])

        pcts_a = query_metric_percentiles(company_a.id, server_a.id, bucket='1m', start=window_start)
        self.assertEqual(len(pcts_a), 1)
        self.assertAlmostEqual(pcts_a[0]['p95_cpu'], 77.0)

        cross_pcts = query_metric_percentiles(company_a.id, server_b.id, bucket='1m', start=window_start)
        self.assertEqual(cross_pcts, [])


class RedisStreamsIngestionV2Tests(TransactionTestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Stream Co')
        self.server = Server.unscoped.create(name='stream-01', company=self.company)
        self.redis_con = get_redis_connection('default')
        self.redis_con.delete(TELEMETRY_STREAM_KEY)
        self.redis_con.delete(TELEMETRY_DLQ_STREAM_KEY)

    def tearDown(self):
        self.redis_con.delete(TELEMETRY_STREAM_KEY)
        self.redis_con.delete(TELEMETRY_DLQ_STREAM_KEY)

    def test_xautoclaim_recovers_pending_entries_from_crashed_consumer(self):
        from django.utils import timezone

        ts = timezone.now()
        push_to_stream({
            'server_id': str(self.server.id),
            'company_id': str(self.company.id),
            'timestamp': ts.isoformat(),
            'cpu_usage': 33.0,
            'ram_usage': 44.0,
        })

        stolen = read_stream_batch(consumer_name='crashed-worker', count=10, block_ms=50)
        self.assertEqual(len(stolen), 1)
        self.assertEqual(MetricLog.unscoped.filter(server=self.server).count(), 0)
        self.assertEqual(get_stream_metrics()['pending_count'], 1)

        recovery = IngestConsumer(consumer_name='recovery-worker', claim_idle_ms=0, block_ms=50)
        stats = recovery.run_once(reclaim=True)
        self.assertEqual(stats['persisted'], 1)
        self.assertEqual(stats['acked'], 1)
        self.assertEqual(get_stream_metrics()['pending_count'], 0)
        self.assertEqual(MetricLog.unscoped.filter(server=self.server).count(), 1)

    def test_poison_record_moves_to_dlq_after_max_deliveries(self):
        from django.utils import timezone

        self.redis_con.xadd(TELEMETRY_STREAM_KEY, {'payload': '{invalid-json'})
        push_to_stream({
            'server_id': str(self.server.id),
            'company_id': str(self.company.id),
            'timestamp': timezone.now().isoformat(),
            'cpu_usage': 18.0,
            'ram_usage': 25.0,
        })

        consumer = IngestConsumer(consumer_name='dlq-worker', claim_idle_ms=0, block_ms=50, max_deliveries=2)
        first = consumer.run_once(reclaim=True)
        self.assertEqual(first['persisted'], 1)
        self.assertEqual(first['retried'], 1)
        self.assertEqual(first['dlq'], 0)
        self.assertEqual(self.redis_con.xlen(TELEMETRY_DLQ_STREAM_KEY), 0)

        second = consumer.run_once(reclaim=True)
        self.assertEqual(second['dlq'], 1)
        self.assertEqual(second['acked'], 1)
        self.assertEqual(self.redis_con.xlen(TELEMETRY_DLQ_STREAM_KEY), 1)
        self.assertEqual(get_stream_metrics()['pending_count'], 0)

    def test_deleted_server_fk_isolated_from_healthy_batch_records(self):
        import uuid
        from datetime import timedelta
        from django.utils import timezone

        now = timezone.now()
        push_to_stream({
            'server_id': str(uuid.uuid4()),
            'company_id': str(self.company.id),
            'timestamp': now.isoformat(),
            'cpu_usage': 10.0,
            'ram_usage': 20.0,
        })
        push_to_stream({
            'server_id': str(self.server.id),
            'company_id': str(self.company.id),
            'timestamp': (now + timedelta(seconds=1)).isoformat(),
            'cpu_usage': 50.0,
            'ram_usage': 60.0,
        })

        consumer = IngestConsumer(consumer_name='fk-worker', claim_idle_ms=0, block_ms=50, max_deliveries=1)
        stats = consumer.run_once(reclaim=True)
        self.assertEqual(stats['persisted'], 1)
        self.assertEqual(stats['dlq'], 1)
        self.assertEqual(stats['acked'], 2)
        self.assertEqual(MetricLog.unscoped.filter(server=self.server).count(), 1)
        self.assertEqual(self.redis_con.xlen(TELEMETRY_DLQ_STREAM_KEY), 1)

    def test_beat_poller_removed_and_compose_has_ingest_consumer(self):
        from django.conf import settings

        self.assertNotIn('process-telemetry-every-5-seconds', settings.CELERY_BEAT_SCHEDULE)
        self.assertTrue(settings.CELERY_TASK_IGNORE_RESULT)
        compose = (settings.BASE_DIR / 'docker-compose.yml').read_text(encoding='utf-8')
        self.assertIn('ingest_consumer:', compose)
        self.assertIn('run_ingest_consumer', compose)


class BatchAndIdempotencyTests(APITestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.company_a = Company.objects.create(name='Batch Co A')
        self.company_b = Company.objects.create(name='Batch Co B')
        self.user_a = User.objects.create_user(username='batch_user_a', password='password123', company=self.company_a)
        self.token_a = Token.objects.create(user=self.user_a)
        self.server_a = Server.unscoped.create(name='batch-a', company=self.company_a)
        self.server_b = Server.unscoped.create(name='batch-b', company=self.company_b)
        self.batch_url = reverse('telemetry-ingest-batch')
        self.ingest_url = reverse('telemetry-ingest')
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token_a.key}')
        self.redis_con = get_redis_connection('default')
        self.redis_con.delete(TELEMETRY_STREAM_KEY)
        self.redis_con.delete(TELEMETRY_DLQ_STREAM_KEY)

    def tearDown(self):
        from django.core.cache import cache

        cache.clear()
        self.redis_con.delete(TELEMETRY_STREAM_KEY)
        self.redis_con.delete(TELEMETRY_DLQ_STREAM_KEY)

    @patch('monitoring.tasks.evaluate_metrics_batch.delay')
    def test_gzip_batch_ingest_stores_received_at_and_deduplicates_replays(self, mock_evaluate):
        import gzip
        import uuid
        from datetime import timedelta
        from django.utils import timezone

        t1 = (timezone.now() - timedelta(seconds=30)).replace(microsecond=0)
        t2 = (timezone.now() - timedelta(seconds=10)).replace(microsecond=0)
        body = {
            'samples': [
                {
                    'server': str(self.server_a.id),
                    'sample_id': str(uuid.uuid4()),
                    'timestamp': t1.isoformat(),
                    'cpu_usage': 25.0,
                    'ram_usage': 40.0,
                    'load_1m': 0.75,
                    'disk_usage': 52.0,
                },
                {
                    'server': str(self.server_a.id),
                    'sample_id': str(uuid.uuid4()),
                    'timestamp': t1.isoformat(),
                    'cpu_usage': 99.0,
                    'ram_usage': 99.0,
                },
                {
                    'server': str(self.server_a.id),
                    'sample_id': str(uuid.uuid4()),
                    'timestamp': t2.isoformat(),
                    'cpu_usage': 35.0,
                    'ram_usage': 45.0,
                    'net_rx_bps': 1024.0,
                    'net_tx_bps': 512.0,
                },
            ]
        }
        compressed = gzip.compress(json.dumps(body).encode('utf-8'))

        resp = self.client.post(
            self.batch_url,
            data=compressed,
            content_type='application/json',
            HTTP_CONTENT_ENCODING='gzip',
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.data['accepted'], 3)

        consumer = IngestConsumer(consumer_name='batch-test', block_ms=50)
        consumer.run_once(reclaim=False)
        self.assertEqual(MetricLog.unscoped.filter(server=self.server_a).count(), 2)
        first_log = MetricLog.unscoped.get(server=self.server_a, timestamp=t1)
        self.assertIsNotNone(first_log.received_at)
        self.assertEqual(first_log.load_1m, 0.75)

        replay = self.client.post(
            self.batch_url,
            data=compressed,
            content_type='application/json',
            HTTP_CONTENT_ENCODING='gzip',
        )
        self.assertEqual(replay.status_code, status.HTTP_202_ACCEPTED)
        consumer.run_once(reclaim=False)
        self.assertEqual(MetricLog.unscoped.filter(server=self.server_a).count(), 2)

    def test_gzip_bomb_rejected_with_413(self):
        import gzip
        from django.test import override_settings

        bomb_bytes = b'{"samples":[' + (b' ' * (128 * 1024)) + b']}'
        compressed = gzip.compress(bomb_bytes)
        with override_settings(TELEMETRY_MAX_DECOMPRESSED_BYTES=4096):
            resp = self.client.post(
                self.batch_url,
                data=compressed,
                content_type='application/json',
                HTTP_CONTENT_ENCODING='gzip',
            )
        self.assertEqual(resp.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        self.assertEqual(self.redis_con.xlen(TELEMETRY_STREAM_KEY), 0)

    def test_future_timestamps_beyond_5_minutes_rejected(self):
        from datetime import timedelta
        from django.utils import timezone

        too_far = (timezone.now() + timedelta(minutes=6)).isoformat()
        single_resp = self.client.post(
            self.ingest_url,
            {'server': str(self.server_a.id), 'timestamp': too_far, 'cpu_usage': 10.0, 'ram_usage': 20.0},
            format='json',
        )
        self.assertEqual(single_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('timestamp', single_resp.data)

        batch_resp = self.client.post(
            self.batch_url,
            {
                'samples': [
                    {'server': str(self.server_a.id), 'timestamp': too_far, 'cpu_usage': 10.0, 'ram_usage': 20.0}
                ]
            },
            format='json',
        )
        self.assertEqual(batch_resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.redis_con.xlen(TELEMETRY_STREAM_KEY), 0)

    def test_mixed_cross_tenant_batch_and_oversize_batch_rejected_atomically(self):
        from django.test import override_settings

        mixed = self.client.post(
            self.batch_url,
            {
                'samples': [
                    {'server': str(self.server_a.id), 'cpu_usage': 10.0, 'ram_usage': 20.0},
                    {'server': str(self.server_b.id), 'cpu_usage': 10.0, 'ram_usage': 20.0},
                ]
            },
            format='json',
        )
        self.assertEqual(mixed.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.redis_con.xlen(TELEMETRY_STREAM_KEY), 0)

        with override_settings(TELEMETRY_MAX_BATCH_SIZE=2):
            oversize = self.client.post(
                self.batch_url,
                {
                    'samples': [
                        {'server': str(self.server_a.id), 'cpu_usage': 10.0, 'ram_usage': 20.0},
                        {'server': str(self.server_a.id), 'cpu_usage': 11.0, 'ram_usage': 21.0},
                        {'server': str(self.server_a.id), 'cpu_usage': 12.0, 'ram_usage': 22.0},
                    ]
                },
                format='json',
            )
        self.assertEqual(oversize.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.redis_con.xlen(TELEMETRY_STREAM_KEY), 0)


class BroadcastAfterCommitTests(TransactionTestCase):
    def setUp(self):
        self.company_a = Company.objects.create(name='Bcast Co A')
        self.company_b = Company.objects.create(name='Bcast Co B')
        self.user_a = User.objects.create_user(username='bcast_a', password='password123', company=self.company_a)
        self.user_b = User.objects.create_user(username='bcast_b', password='password123', company=self.company_b)
        self.server_a1 = Server.unscoped.create(name='bc-a1', company=self.company_a)
        self.server_a2 = Server.unscoped.create(name='bc-a2', company=self.company_a)
        self.server_b1 = Server.unscoped.create(name='bc-b1', company=self.company_b)
        self.redis_con = get_redis_connection('default')
        self.redis_con.delete(TELEMETRY_STREAM_KEY)
        self.redis_con.delete(TELEMETRY_DLQ_STREAM_KEY)

    def tearDown(self):
        from django.db import connections

        connections.close_all()
        self.redis_con.delete(TELEMETRY_STREAM_KEY)
        self.redis_con.delete(TELEMETRY_DLQ_STREAM_KEY)

    @patch('monitoring.tasks.evaluate_metrics_batch.delay')
    def test_one_group_send_per_company_per_batch_after_commit(self, mock_evaluate):
        from datetime import timedelta
        from unittest.mock import AsyncMock
        from django.utils import timezone

        now = timezone.now()
        samples = [
            (self.server_a1, self.company_a, now, 10.0),
            (self.server_a1, self.company_a, now + timedelta(seconds=1), 15.0),
            (self.server_a2, self.company_a, now, 20.0),
            (self.server_b1, self.company_b, now, 30.0),
            (self.server_b1, self.company_b, now + timedelta(seconds=1), 35.0),
        ]
        for srv, comp, ts, cpu in samples:
            push_to_stream({
                'server_id': str(srv.id),
                'company_id': str(comp.id),
                'timestamp': ts.isoformat(),
                'cpu_usage': cpu,
                'ram_usage': 40.0,
            })

        mock_layer = AsyncMock()
        with patch('telemetry.consumer.get_channel_layer', return_value=mock_layer):
            consumer = IngestConsumer(consumer_name='bcast-worker', block_ms=50)
            stats = consumer.run_once(reclaim=False)

        self.assertEqual(stats['persisted'], 5)
        self.assertEqual(mock_layer.group_send.await_count, 2)

        by_group = {call.args[0]: call.args[1] for call in mock_layer.group_send.await_args_list}
        self.assertEqual(len(by_group[f'company_{self.company_a.id}']['samples']), 3)
        self.assertEqual(len(by_group[f'company_{self.company_b.id}']['samples']), 2)

    def test_failed_commit_emits_zero_broadcasts(self):
        from unittest.mock import AsyncMock
        from django.db import OperationalError
        from django.utils import timezone

        push_to_stream({
            'server_id': str(self.server_a1.id),
            'company_id': str(self.company_a.id),
            'timestamp': timezone.now().isoformat(),
            'cpu_usage': 50.0,
            'ram_usage': 50.0,
        })

        mock_layer = AsyncMock()
        with (
            patch('telemetry.consumer.get_channel_layer', return_value=mock_layer),
            patch('telemetry.consumer.MetricLog.unscoped.bulk_create', side_effect=OperationalError('db down')),
        ):
            consumer = IngestConsumer(consumer_name='fail-worker', block_ms=50)
            with self.assertRaises(OperationalError):
                consumer.run_once(reclaim=False)

        self.assertEqual(mock_layer.group_send.await_count, 0)

    @patch('monitoring.tasks.evaluate_metrics_batch.delay')
    async def test_multiplexed_company_ws_and_server_ws_enforce_tenant_isolation(self, mock_evaluate):
        from asgiref.sync import sync_to_async
        from channels.testing import WebsocketCommunicator
        from django.utils import timezone
        from accounts.authentication import ticket_manager
        from config.asgi import application

        ticket_a_company = await sync_to_async(ticket_manager.create_ticket)(str(self.user_a.id))
        ticket_a_server = await sync_to_async(ticket_manager.create_ticket)(str(self.user_a.id))
        ticket_b_company = await sync_to_async(ticket_manager.create_ticket)(str(self.user_b.id))

        ws_a = WebsocketCommunicator(
            application,
            f'/ws/telemetry/?ticket={ticket_a_company}',
            headers=[(b'origin', b'http://localhost:5173')],
        )
        ws_a_srv = WebsocketCommunicator(
            application,
            f'/ws/telemetry/{self.server_a1.id}/?ticket={ticket_a_server}',
            headers=[(b'origin', b'http://localhost:5173')],
        )
        ws_b = WebsocketCommunicator(
            application,
            f'/ws/telemetry/?ticket={ticket_b_company}',
            headers=[(b'origin', b'http://localhost:5173')],
        )

        try:
            self.assertTrue((await ws_a.connect(timeout=10))[0])
            self.assertTrue((await ws_a_srv.connect(timeout=10))[0])
            self.assertTrue((await ws_b.connect(timeout=10))[0])

            now = timezone.now()
            await sync_to_async(push_to_stream)({
                'server_id': str(self.server_a1.id),
                'company_id': str(self.company_a.id),
                'timestamp': now.isoformat(),
                'cpu_usage': 42.0,
                'ram_usage': 50.0,
            })
            await sync_to_async(push_to_stream)({
                'server_id': str(self.server_b1.id),
                'company_id': str(self.company_b.id),
                'timestamp': now.isoformat(),
                'cpu_usage': 88.0,
                'ram_usage': 60.0,
            })

            consumer = IngestConsumer(consumer_name='ws-bcast-worker', block_ms=50)
            await sync_to_async(consumer.run_once)(reclaim=False)

            msg_a = await ws_a.receive_json_from(timeout=5)
            self.assertEqual(msg_a['type'], 'telemetry_batch')
            self.assertEqual([s['server_id'] for s in msg_a['samples']], [str(self.server_a1.id)])
            self.assertTrue(await ws_a.receive_nothing(timeout=0.3))

            msg_a_srv = await ws_a_srv.receive_json_from(timeout=5)
            self.assertEqual(msg_a_srv['server_id'], str(self.server_a1.id))
            self.assertEqual(msg_a_srv['cpu_usage'], 42.0)

            msg_b = await ws_b.receive_json_from(timeout=5)
            self.assertEqual(msg_b['type'], 'telemetry_batch')
            self.assertEqual([s['server_id'] for s in msg_b['samples']], [str(self.server_b1.id)])
            self.assertTrue(await ws_b.receive_nothing(timeout=0.3))
        finally:
            await ws_a.disconnect()
            await ws_a_srv.disconnect()
            await ws_b.disconnect()
