import gzip
import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import OperationalError
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from django_redis import get_redis_connection
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from accounts.models import Company
from monitoring.heartbeat import (
    HEARTBEAT_DIRTY_KEY,
    HEARTBEAT_LAST_SEEN_KEY,
    HEARTBEAT_OFFLINE_KEY,
    check_server_heartbeats,
    record_heartbeat,
)
from monitoring.models import AlertRule, AlertState, NotificationOutbox, Server, SystemEvent
from monitoring.tasks import deliver_notification_outbox, evaluate_alert_rules
from telemetry.consumer import IngestConsumer
from telemetry.ingestion import (
    get_stream_metrics,
    push_batch_to_stream,
    read_stream_batch,
)
from telemetry.models import MetricLog


class Phase1ResilienceTests(TransactionTestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.company = Company.objects.create(name='Chaos Tenant A')
        self.other_company = Company.objects.create(name='Chaos Tenant B')
        self.user = self.user_model.objects.create_user(
            username=f'chaos_a_{uuid.uuid4().hex[:6]}',
            email='chaos_a@example.com',
            password='secure-password-123',
            company=self.company,
        )
        self.token = Token.objects.create(user=self.user)
        self.server = Server.unscoped.create(
            name='chaos-node-1',
            company=self.company,
            is_active=True,
            telemetry_cadence=30,
        )
        self.other_server = Server.unscoped.create(
            name='chaos-node-b',
            company=self.other_company,
            is_active=True,
            telemetry_cadence=30,
        )
        self.redis = get_redis_connection('default')
        self.stream_key = f'test:phase1:stream:{uuid.uuid4().hex}'
        self.dlq_key = f'test:phase1:dlq:{uuid.uuid4().hex}'
        self.group_name = f'test-phase1-group-{uuid.uuid4().hex[:8]}'

    def tearDown(self):
        self.redis.delete(self.stream_key, self.dlq_key)
        self.redis.hdel(HEARTBEAT_LAST_SEEN_KEY, str(self.server.id))
        self.redis.srem(HEARTBEAT_DIRTY_KEY, str(self.server.id))
        self.redis.srem(HEARTBEAT_OFFLINE_KEY, str(self.server.id))

    def test_consumer_crash_mid_batch_reclaim_zero_loss_zero_duplicates(self):
        now = timezone.now()
        payloads = [
            {
                'server_id': str(self.server.id),
                'company_id': str(self.company.id),
                'sample_id': str(uuid.uuid4()),
                'cpu_usage': float(i % 100),
                'ram_usage': 50.0,
                'timestamp': (now - timedelta(seconds=200 - i)).isoformat(),
                'received_at': now.isoformat(),
            }
            for i in range(200)
        ]
        push_batch_to_stream(payloads, con=self.redis, stream_key=self.stream_key)

        crashed_entries = read_stream_batch(
            consumer_name='crashed-worker-1',
            count=200,
            block_ms=100,
            con=self.redis,
            stream_key=self.stream_key,
            group_name=self.group_name,
        )
        self.assertEqual(len(crashed_entries), 200)
        self.assertEqual(MetricLog.unscoped.filter(server=self.server).count(), 0)

        recovery_consumer = IngestConsumer(
            consumer_name='recovery-worker-2',
            batch_size=250,
            block_ms=100,
            claim_idle_ms=0,
            stream_key=self.stream_key,
            dlq_key=self.dlq_key,
            group_name=self.group_name,
        )
        stats = recovery_consumer.run_once(reclaim=True, con=self.redis)
        self.assertEqual(stats['persisted'], 200)
        self.assertEqual(stats['acked'], 200)
        self.assertEqual(stats['dlq'], 0)
        self.assertEqual(MetricLog.unscoped.filter(server=self.server).count(), 200)

        metrics = get_stream_metrics(
            con=self.redis,
            stream_key=self.stream_key,
            dlq_key=self.dlq_key,
            group_name=self.group_name,
        )
        self.assertEqual(metrics['pending_count'], 0)
        self.assertEqual(metrics['lag'], 0)

        push_batch_to_stream(payloads[:50], con=self.redis, stream_key=self.stream_key)
        recovery_consumer.run_once(reclaim=True, con=self.redis)
        self.assertEqual(MetricLog.unscoped.filter(server=self.server).count(), 200)

    def test_postgres_outage_recovery_drains_stream_without_loss(self):
        now = timezone.now()
        payloads = [
            {
                'server_id': str(self.server.id),
                'company_id': str(self.company.id),
                'sample_id': str(uuid.uuid4()),
                'cpu_usage': 42.5,
                'ram_usage': 61.0,
                'timestamp': (now - timedelta(seconds=100 - i)).isoformat(),
                'received_at': now.isoformat(),
            }
            for i in range(100)
        ]
        push_batch_to_stream(payloads, con=self.redis, stream_key=self.stream_key)

        consumer = IngestConsumer(
            consumer_name='db-outage-worker',
            batch_size=150,
            block_ms=100,
            claim_idle_ms=0,
            stream_key=self.stream_key,
            dlq_key=self.dlq_key,
            group_name=self.group_name,
        )

        with (
            patch.object(
                MetricLog.unscoped,
                'bulk_create',
                side_effect=OperationalError('database temporarily unavailable'),
            ),
            self.assertRaises(OperationalError),
        ):
            consumer.run_once(reclaim=True, con=self.redis)

        self.assertEqual(MetricLog.unscoped.filter(server=self.server).count(), 0)
        during_outage = get_stream_metrics(
            con=self.redis,
            stream_key=self.stream_key,
            dlq_key=self.dlq_key,
            group_name=self.group_name,
        )
        self.assertEqual(during_outage['pending_count'], 100)

        recovered_stats = consumer.run_once(reclaim=True, con=self.redis)
        self.assertEqual(recovered_stats['persisted'], 100)
        self.assertEqual(recovered_stats['acked'], 100)
        self.assertEqual(MetricLog.unscoped.filter(server=self.server).count(), 100)
        after_recovery = get_stream_metrics(
            con=self.redis,
            stream_key=self.stream_key,
            dlq_key=self.dlq_key,
            group_name=self.group_name,
        )
        self.assertEqual(after_recovery['pending_count'], 0)

    def test_duplicate_gzip_backfill_idempotency_and_cross_tenant_rejection(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        url = reverse('telemetry-ingest-batch')
        now = timezone.now()

        samples = [
            {
                'server': str(self.server.id),
                'sample_id': str(uuid.uuid4()),
                'cpu_usage': 35.0 + i,
                'ram_usage': 45.0,
                'timestamp': (now - timedelta(seconds=30 - i)).isoformat(),
            }
            for i in range(20)
        ]
        compressed = gzip.compress(json.dumps({'samples': samples}).encode('utf-8'))

        with patch('telemetry.views.push_batch_to_stream') as mock_push:
            mock_push.side_effect = lambda items: push_batch_to_stream(
                items,
                con=self.redis,
                stream_key=self.stream_key,
            )
            first = client.post(
                url,
                data=compressed,
                content_type='application/json',
                HTTP_CONTENT_ENCODING='gzip',
            )
            retry = client.post(
                url,
                data=compressed,
                content_type='application/json',
                HTTP_CONTENT_ENCODING='gzip',
            )
            self.assertEqual(first.status_code, 202)
            self.assertEqual(retry.status_code, 202)

            cross_tenant = client.post(
                url,
                data=gzip.compress(
                    json.dumps(
                        {
                            'samples': [
                                {
                                    'server': str(self.other_server.id),
                                    'cpu_usage': 20.0,
                                    'ram_usage': 30.0,
                                    'timestamp': now.isoformat(),
                                }
                            ]
                        }
                    ).encode('utf-8')
                ),
                content_type='application/json',
                HTTP_CONTENT_ENCODING='gzip',
            )
            self.assertEqual(cross_tenant.status_code, 400)

        consumer = IngestConsumer(
            consumer_name='backfill-worker',
            batch_size=100,
            block_ms=100,
            claim_idle_ms=0,
            stream_key=self.stream_key,
            dlq_key=self.dlq_key,
            group_name=self.group_name,
        )
        consumer.run_once(reclaim=True, con=self.redis)
        self.assertEqual(MetricLog.unscoped.filter(server=self.server).count(), 20)
        self.assertEqual(MetricLog.unscoped.filter(server=self.other_server).count(), 0)

    def test_alert_duration_honored_and_no_data_fires_after_agent_stops(self):
        cpu_rule = AlertRule.unscoped.create(
            company=self.company,
            server=self.server,
            metric_type='cpu',
            operator='gt',
            threshold_value=80.0,
            duration_minutes=1,
            severity='critical',
            aggregation='avg',
            hysteresis_margin=5.0,
            notification_type='EMAIL',
            notification_target='oncall@example.com',
            is_active=True,
        )
        no_data_rule = AlertRule.unscoped.create(
            company=self.company,
            server=self.server,
            metric_type='no_data',
            threshold_value=0.0,
            notification_type='EMAIL',
            notification_target='oncall@example.com',
            is_active=True,
        )

        t0 = timezone.now() - timedelta(minutes=5)
        MetricLog.unscoped.create(
            company=self.company,
            server=self.server,
            cpu_usage=92.0,
            ram_usage=50.0,
            timestamp=t0,
        )
        with patch('monitoring.tasks.deliver_notification_outbox.delay'):
            evaluate_alert_rules(now=t0)
            state = AlertState.unscoped.get(rule=cpu_rule)
            self.assertEqual(state.status, 'PENDING')
            self.assertEqual(NotificationOutbox.unscoped.filter(rule=cpu_rule).count(), 0)

            t1 = t0 + timedelta(seconds=30)
            MetricLog.unscoped.create(
                company=self.company,
                server=self.server,
                cpu_usage=94.0,
                ram_usage=50.0,
                timestamp=t1,
            )
            evaluate_alert_rules(now=t1)
            state.refresh_from_db()
            self.assertEqual(state.status, 'PENDING')
            self.assertEqual(NotificationOutbox.unscoped.filter(rule=cpu_rule).count(), 0)

            t2 = t0 + timedelta(seconds=60)
            MetricLog.unscoped.create(
                company=self.company,
                server=self.server,
                cpu_usage=95.0,
                ram_usage=50.0,
                timestamp=t2,
            )
            evaluate_alert_rules(now=t2)
            state.refresh_from_db()
            self.assertEqual(state.status, 'FIRING')
            outbox_qs = NotificationOutbox.unscoped.filter(rule=cpu_rule, event_type='ALERT')
            self.assertEqual(outbox_qs.count(), 1)

        outbox = outbox_qs.first()
        with patch('monitoring.tasks.NotificationDispatcher.dispatch_alert', return_value=True):
            self.assertTrue(deliver_notification_outbox(str(outbox.id)))
        outbox.refresh_from_db()
        self.assertEqual(outbox.status, 'DELIVERED')

        seen_at = timezone.now() - timedelta(seconds=100)
        record_heartbeat(self.server.id, self.company.id, seen_at=seen_at, con=self.redis)
        with patch('monitoring.heartbeat.NotificationDispatcher.dispatch_alert', return_value=True) as mock_no_data:
            hb_stats = check_server_heartbeats(now=timezone.now(), con=self.redis)
        self.assertEqual(hb_stats['newly_offline'], 1)
        mock_no_data.assert_called_once()
        self.assertEqual(mock_no_data.call_args[0][1].id, no_data_rule.id)
        self.assertTrue(
            SystemEvent.objects.filter(
                event_type='NO_DATA',
                context__server_id=str(self.server.id),
            ).exists()
        )
