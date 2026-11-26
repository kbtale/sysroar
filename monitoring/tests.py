from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django_redis import get_redis_connection
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient
from accounts.models import Company
from config.celery import app as celery_app
from telemetry.ingestion import TELEMETRY_STREAM_KEY
from telemetry.models import MetricLog
from .models import AlertRule, Server, ServerAlertState, SystemEvent
from .tasks import check_system_health, evaluate_metrics_batch, record_system_event


class MonitoringEvaluationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='Test Corp')
        self.server = Server.unscoped.create(
            name='Test Server',
            company=self.company,
            is_active=True,
        )
        self.rule = AlertRule.unscoped.create(
            server=self.server,
            company=self.company,
            metric_type='cpu',
            threshold_value=90.0,
            is_active=True,
            notification_type='EMAIL',
            notification_target='ops@example.com',
        )

    @patch('monitoring.tasks.NotificationDispatcher.dispatch_alert')
    def test_evaluate_metrics_breach(self, mock_dispatch):
        log = MetricLog.unscoped.create(
            server=self.server,
            company=self.company,
            cpu_usage=95.0,
            ram_usage=50.0,
            timestamp=timezone.now(),
        )
        evaluate_metrics_batch([str(log.id)])

        state = ServerAlertState.unscoped.get(server=self.server)
        self.assertEqual(state.current_cooldown_tier, 1)
        self.assertEqual(state.consecutive_healthy_count, 0)
        self.assertIsNotNone(state.last_alert_sent_at)
        mock_dispatch.assert_called_once()
        dispatched_server, dispatched_rule, context = mock_dispatch.call_args[0]
        self.assertEqual(dispatched_server.id, self.server.id)
        self.assertEqual(dispatched_rule.id, self.rule.id)
        self.assertEqual(context['value'], 95.0)

    @patch('monitoring.tasks.NotificationDispatcher.dispatch_resolution')
    @patch('monitoring.tasks.NotificationDispatcher.dispatch_alert')
    def test_evaluate_metrics_healthy(self, mock_dispatch_alert, mock_dispatch_resolution):
        log = MetricLog.unscoped.create(
            server=self.server,
            company=self.company,
            cpu_usage=80.0,
            ram_usage=50.0,
            timestamp=timezone.now(),
        )
        evaluate_metrics_batch([str(log.id)])

        state = ServerAlertState.unscoped.get(server=self.server)
        self.assertEqual(state.current_cooldown_tier, 0)
        self.assertEqual(state.consecutive_healthy_count, 1)
        self.assertIsNone(state.last_alert_sent_at)
        mock_dispatch_alert.assert_not_called()
        mock_dispatch_resolution.assert_not_called()


class SystemHealthMonitoringTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name='Test Company')
        self._prev_eager = celery_app.conf.task_always_eager
        celery_app.conf.task_always_eager = True

    def tearDown(self):
        celery_app.conf.task_always_eager = self._prev_eager

    def test_auth_failure_logs_event(self):
        self.client.get(
            '/api/monitoring/servers/',
            HTTP_AUTHORIZATION='Token invalid_token',
        )

        events = SystemEvent.objects.filter(event_type='FAILED_AUTHENTICATION')
        self.assertTrue(events.exists())
        self.assertEqual(events.count(), 1)
        self.assertEqual(events.first().context['path'], '/api/monitoring/servers/')

    def test_system_health_alert_threshold(self):
        with self.settings(
            ADMINS=[('Admin', 'admin@example.com')],
            SYSTEM_EVENT_THRESHOLDS={'TEST_EVENT': 3},
            DEFAULT_FROM_EMAIL='noreply@sysroar.com',
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        ):
            for _ in range(3):
                SystemEvent.objects.create(event_type='TEST_EVENT', severity='ERROR')

            check_system_health()

            self.assertEqual(len(mail.outbox), 1)
            self.assertIn('System Health Warning', mail.outbox[0].subject)
            self.assertIn('TEST_EVENT: 3 occurrences', mail.outbox[0].body)

    def test_async_event_recording_task(self):
        record_system_event('MANUAL_TEST', severity='WARNING', context={'foo': 'bar'})

        event = SystemEvent.objects.get(event_type='MANUAL_TEST')
        self.assertEqual(event.severity, 'WARNING')
        self.assertEqual(event.context['foo'], 'bar')


class ServerApiAndHeartbeatTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.client = APIClient()
        self.company_a = Company.objects.create(name='Company A')
        self.company_b = Company.objects.create(name='Company B')
        self.user_a = User.objects.create_user(username='mon_user_a', password='password123', company=self.company_a)
        self.token_a = Token.objects.create(user=self.user_a)
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token_a.key}')

        now = timezone.now()
        self.online_server = Server.unscoped.create(
            name='web-01',
            company=self.company_a,
            ip_address='10.0.0.1',
            os_info='Debian 12',
            last_ping=now,
        )
        self.offline_server = Server.unscoped.create(
            name='db-01',
            company=self.company_a,
            last_ping=now - timedelta(minutes=10),
        )
        self.unknown_server = Server.unscoped.create(
            name='new-01',
            company=self.company_a,
            last_ping=None,
        )
        self.other_company_server = Server.unscoped.create(
            name='other-01',
            company=self.company_b,
            last_ping=now,
        )

        self.redis_con = get_redis_connection('default')
        self.redis_con.delete(TELEMETRY_STREAM_KEY)
        from monitoring.heartbeat import HEARTBEAT_DIRTY_KEY, HEARTBEAT_LAST_SEEN_KEY, HEARTBEAT_OFFLINE_KEY

        self.redis_con.delete(HEARTBEAT_LAST_SEEN_KEY, HEARTBEAT_DIRTY_KEY, HEARTBEAT_OFFLINE_KEY)

    def tearDown(self):
        from monitoring.heartbeat import HEARTBEAT_DIRTY_KEY, HEARTBEAT_LAST_SEEN_KEY, HEARTBEAT_OFFLINE_KEY

        con = get_redis_connection('default')
        con.delete(TELEMETRY_STREAM_KEY, HEARTBEAT_LAST_SEEN_KEY, HEARTBEAT_DIRTY_KEY, HEARTBEAT_OFFLINE_KEY)

    def test_list_servers_returns_real_fields_computed_status_and_enforces_tenancy(self):
        response = self.client.get('/api/monitoring/servers/')
        self.assertEqual(response.status_code, 200)
        results = response.data['results'] if isinstance(response.data, dict) else response.data
        by_id = {item['id']: item for item in results}

        self.assertEqual(set(by_id.keys()), {
            str(self.online_server.id),
            str(self.offline_server.id),
            str(self.unknown_server.id),
        })
        self.assertNotIn(str(self.other_company_server.id), by_id)

        online = by_id[str(self.online_server.id)]
        self.assertEqual(online['name'], 'web-01')
        self.assertEqual(online['ip_address'], '10.0.0.1')
        self.assertEqual(online['os_info'], 'Debian 12')
        self.assertEqual(online['status'], 'online')
        self.assertIsNotNone(online['last_seen'])

        self.assertEqual(by_id[str(self.offline_server.id)]['status'], 'offline')
        self.assertEqual(by_id[str(self.unknown_server.id)]['status'], 'unknown')

        cross_resp = self.client.get(f'/api/monitoring/servers/{self.other_company_server.id}/')
        self.assertEqual(cross_resp.status_code, 404)

    def test_ingest_updates_server_last_seen_ip_and_os_info(self):
        from monitoring.heartbeat import flush_heartbeats_to_db

        ingest_url = reverse('telemetry-ingest')
        response = self.client.post(
            ingest_url,
            {
                'server': str(self.unknown_server.id),
                'cpu_usage': 22.0,
                'ram_usage': 45.0,
                'ip_address': '10.0.0.42',
                'os_info': 'Ubuntu 24.04 LTS',
            },
            format='json',
        )
        self.assertEqual(response.status_code, 202)

        detail_resp = self.client.get(f'/api/monitoring/servers/{self.unknown_server.id}/')
        self.assertEqual(detail_resp.status_code, 200)
        self.assertEqual(detail_resp.data['status'], 'online')
        self.assertEqual(detail_resp.data['ip_address'], '10.0.0.42')
        self.assertEqual(detail_resp.data['os_info'], 'Ubuntu 24.04 LTS')

        self.unknown_server.refresh_from_db()
        self.assertIsNone(self.unknown_server.last_ping)

        flushed = flush_heartbeats_to_db()
        self.assertEqual(flushed, 1)
        self.unknown_server.refresh_from_db()
        self.assertIsNotNone(self.unknown_server.last_ping)
        self.assertEqual(self.unknown_server.ip_address, '10.0.0.42')
        self.assertEqual(self.unknown_server.os_info, 'Ubuntu 24.04 LTS')

    def test_ingest_falls_back_to_remote_addr_when_ip_omitted(self):
        from monitoring.heartbeat import flush_heartbeats_to_db

        ingest_url = reverse('telemetry-ingest')
        response = self.client.post(
            ingest_url,
            {
                'server': str(self.unknown_server.id),
                'cpu_usage': 15.0,
                'ram_usage': 30.0,
            },
            format='json',
            REMOTE_ADDR='192.0.2.15',
        )
        self.assertEqual(response.status_code, 202)
        flush_heartbeats_to_db()
        self.unknown_server.refresh_from_db()
        self.assertIsNotNone(self.unknown_server.last_ping)
        self.assertEqual(self.unknown_server.ip_address, '192.0.2.15')


class HeartbeatAndNoDataAlertTests(TestCase):
    def setUp(self):
        from monitoring.heartbeat import HEARTBEAT_DIRTY_KEY, HEARTBEAT_LAST_SEEN_KEY, HEARTBEAT_OFFLINE_KEY

        self.redis_con = get_redis_connection('default')
        self.redis_con.delete(HEARTBEAT_LAST_SEEN_KEY, HEARTBEAT_DIRTY_KEY, HEARTBEAT_OFFLINE_KEY)
        self.company = Company.objects.create(name='HB Corp')
        self.fast_server = Server.unscoped.create(
            name='hb-fast',
            company=self.company,
            telemetry_cadence=10,
            last_ping=timezone.now() - timedelta(seconds=95),
        )
        self.slow_server = Server.unscoped.create(
            name='hb-slow',
            company=self.company,
            telemetry_cadence=60,
            last_ping=timezone.now() - timedelta(seconds=120),
        )

    def tearDown(self):
        from monitoring.heartbeat import HEARTBEAT_DIRTY_KEY, HEARTBEAT_LAST_SEEN_KEY, HEARTBEAT_OFFLINE_KEY

        self.redis_con.delete(HEARTBEAT_LAST_SEEN_KEY, HEARTBEAT_DIRTY_KEY, HEARTBEAT_OFFLINE_KEY)

    def test_offline_threshold_formula_and_no_data_lifecycle(self):
        from monitoring.heartbeat import check_server_heartbeats, compute_offline_threshold_seconds, record_heartbeat

        self.assertEqual(compute_offline_threshold_seconds(10), 90)
        self.assertEqual(compute_offline_threshold_seconds(30), 90)
        self.assertEqual(compute_offline_threshold_seconds(60), 180)

        first = check_server_heartbeats()
        self.assertEqual(first['newly_offline'], 1)
        self.assertEqual(first['recovered'], 0)
        self.assertEqual(SystemEvent.objects.filter(event_type='NO_DATA').count(), 1)
        self.assertEqual(
            SystemEvent.objects.get(event_type='NO_DATA').context['server_id'],
            str(self.fast_server.id),
        )

        repeat = check_server_heartbeats()
        self.assertEqual(repeat['newly_offline'], 0)
        self.assertEqual(SystemEvent.objects.filter(event_type='NO_DATA').count(), 1)

        record_heartbeat(self.fast_server.id, self.company.id, seen_at=timezone.now())
        recovered = check_server_heartbeats()
        self.assertEqual(recovered['flushed'], 1)
        self.assertEqual(recovered['recovered'], 1)
        self.assertEqual(SystemEvent.objects.filter(event_type='NO_DATA_RESOLVED').count(), 1)
