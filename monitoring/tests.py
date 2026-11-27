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


class AlertEngineV2Tests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name='AlertV2 Corp')
        self.server = Server.unscoped.create(name='v2-srv-01', company=self.company, telemetry_cadence=30)
        self.idle_server = Server.unscoped.create(name='v2-idle-01', company=self.company, telemetry_cadence=30)

    def _add_metric(self, ts, cpu, ram=40.0):
        return MetricLog.unscoped.create(
            company=self.company,
            server=self.server,
            timestamp=ts,
            cpu_usage=cpu,
            ram_usage=ram,
        )

    @patch('monitoring.tasks.deliver_notification_outbox.delay')
    def test_duration_honored_and_transient_spike_suppressed(self, mock_deliver):
        from monitoring.models import AlertState, NotificationOutbox
        from monitoring.tasks import evaluate_alert_rules

        rule = AlertRule.unscoped.create(
            company=self.company,
            server=self.server,
            metric_type='cpu',
            operator='gt',
            severity='warning',
            aggregation='avg',
            threshold_value=80.0,
            duration_minutes=5,
            notification_type='EMAIL',
            notification_target='ops@example.com',
        )

        t0 = timezone.now() - timedelta(minutes=10)
        self._add_metric(t0, 92.0)
        res1 = evaluate_alert_rules(now=t0 + timedelta(seconds=10))
        self.assertEqual(res1['enqueued'], 0)
        state = AlertState.unscoped.get(rule=rule)
        self.assertEqual(state.status, 'PENDING')

        t1 = t0 + timedelta(minutes=2)
        MetricLog.unscoped.filter(server=self.server).delete()
        self._add_metric(t1, 30.0)
        evaluate_alert_rules(now=t1 + timedelta(seconds=10))
        state.refresh_from_db()
        self.assertEqual(state.status, 'OK')
        self.assertEqual(NotificationOutbox.unscoped.count(), 0)

        t2 = t1 + timedelta(minutes=1)
        MetricLog.unscoped.filter(server=self.server).delete()
        self._add_metric(t2, 95.0)
        evaluate_alert_rules(now=t2 + timedelta(seconds=5))
        state.refresh_from_db()
        self.assertEqual(state.status, 'PENDING')

        t3 = t2 + timedelta(minutes=5, seconds=10)
        self._add_metric(t3, 96.0)
        res_fire = evaluate_alert_rules(now=t3 + timedelta(seconds=5))
        self.assertEqual(res_fire['enqueued'], 1)
        state.refresh_from_db()
        self.assertEqual(state.status, 'FIRING')
        self.assertEqual(NotificationOutbox.unscoped.filter(rule=rule, event_type='ALERT').count(), 1)
        self.assertEqual(AlertState.unscoped.filter(rule__server=self.idle_server).count(), 0)

    @patch('monitoring.tasks.deliver_notification_outbox.delay')
    def test_multiple_rules_per_metric_and_per_rule_resolution_isolation(self, mock_deliver):
        from monitoring.models import AlertState, NotificationOutbox
        from monitoring.tasks import evaluate_alert_rules

        warn_cpu = AlertRule.unscoped.create(
            company=self.company,
            server=self.server,
            metric_type='cpu',
            operator='gte',
            severity='warning',
            aggregation='max',
            threshold_value=80.0,
            hysteresis_margin=5.0,
            duration_minutes=0,
            notification_type='EMAIL',
            notification_target='warn@example.com',
        )
        crit_cpu = AlertRule.unscoped.create(
            company=self.company,
            server=self.server,
            metric_type='cpu',
            operator='gt',
            severity='critical',
            aggregation='max',
            threshold_value=95.0,
            duration_minutes=0,
            notification_type='EMAIL',
            notification_target='crit@example.com',
        )
        ram_rule = AlertRule.unscoped.create(
            company=self.company,
            server=self.server,
            metric_type='ram',
            operator='gt',
            severity='warning',
            aggregation='avg',
            threshold_value=90.0,
            duration_minutes=0,
            notification_type='EMAIL',
            notification_target='ram@example.com',
        )

        t0 = timezone.now() - timedelta(minutes=5)
        self._add_metric(t0, 85.0)
        evaluate_alert_rules(now=t0 + timedelta(seconds=5))

        self.assertEqual(AlertState.unscoped.get(rule=warn_cpu).status, 'FIRING')
        self.assertEqual(AlertState.unscoped.get(rule=crit_cpu).status, 'OK')
        self.assertEqual(AlertState.unscoped.get(rule=ram_rule).status, 'OK')

        t1 = t0 + timedelta(minutes=1)
        MetricLog.unscoped.filter(server=self.server).delete()
        self._add_metric(t1, 78.0)
        evaluate_alert_rules(now=t1 + timedelta(seconds=5))
        self.assertEqual(AlertState.unscoped.get(rule=warn_cpu).status, 'FIRING')
        self.assertEqual(AlertState.unscoped.get(rule=warn_cpu).consecutive_healthy_count, 0)

        t2 = t1 + timedelta(minutes=1)
        MetricLog.unscoped.filter(server=self.server).delete()
        self._add_metric(t2, 70.0)
        evaluate_alert_rules(now=t2 + timedelta(seconds=5))
        evaluate_alert_rules(now=t2 + timedelta(seconds=35))

        self.assertEqual(AlertState.unscoped.get(rule=warn_cpu).status, 'RESOLVED')
        resolutions = list(
            NotificationOutbox.unscoped.filter(event_type='RESOLUTION').values_list('rule_id', flat=True)
        )
        self.assertEqual(resolutions, [warn_cpu.id])

    def test_flap_detection_and_lt_lte_operators_and_outbox_backoff(self):
        from monitoring.models import AlertState, NotificationOutbox
        from monitoring.state_machine import AlertStateMachine
        from monitoring.tasks import deliver_notification_outbox

        self.assertTrue(AlertStateMachine.evaluate_condition(5.0, 'lt', 10.0))
        self.assertTrue(AlertStateMachine.evaluate_condition(10.0, 'lte', 10.0))
        self.assertFalse(AlertStateMachine.evaluate_condition(11.0, 'lte', 10.0))
        self.assertTrue(AlertStateMachine.is_recovered(15.0, 'lt', 10.0, hysteresis_margin=5.0))
        self.assertFalse(AlertStateMachine.is_recovered(12.0, 'lt', 10.0, hysteresis_margin=5.0))

        rule = AlertRule.unscoped.create(
            company=self.company,
            server=self.server,
            metric_type='cpu',
            operator='gt',
            threshold_value=50.0,
            duration_minutes=0,
            notification_type='EMAIL',
            notification_target='ops@example.com',
        )
        state = AlertState.unscoped.create(company=self.company, rule=rule)
        now = timezone.now()
        actions = []
        for idx in range(5):
            t = now + timedelta(seconds=idx * 60)
            actions.append(AlertStateMachine.evaluate_rule_state(state, rule, 80.0, now=t))
            actions.append(AlertStateMachine.evaluate_rule_state(state, rule, 10.0, now=t + timedelta(seconds=10)))
            actions.append(AlertStateMachine.evaluate_rule_state(state, rule, 10.0, now=t + timedelta(seconds=20)))

        state.refresh_from_db()
        self.assertTrue(state.is_flapping)
        self.assertLess(len([a for a in actions if a is not None]), 5)

        outbox = NotificationOutbox.unscoped.create(
            company=self.company,
            server=self.server,
            rule=rule,
            event_type='ALERT',
            payload={'value': 91.0, 'timestamp': now.isoformat()},
            max_attempts=3,
        )
        with (
            patch('monitoring.tasks.NotificationDispatcher.dispatch_alert', return_value=False),
            patch('monitoring.tasks.deliver_notification_outbox.apply_async'),
        ):
            self.assertFalse(deliver_notification_outbox(str(outbox.id)))
            outbox.refresh_from_db()
            self.assertEqual(outbox.status, 'PENDING')
            self.assertEqual(outbox.attempts, 1)
            self.assertGreater(outbox.next_attempt_at, now)

        with patch('monitoring.tasks.NotificationDispatcher.dispatch_alert', return_value=True):
            self.assertTrue(deliver_notification_outbox(str(outbox.id)))
            outbox.refresh_from_db()
            self.assertEqual(outbox.status, 'DELIVERED')
            self.assertIsNotNone(outbox.delivered_at)


class SelfObservabilityTests(TestCase):
    def test_healthz_returns_ok_anonymously(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_readyz_returns_ready_when_dependencies_healthy(self):
        response = self.client.get('/readyz')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['status'], 'ready')
        self.assertEqual(
            body['checks'],
            {'database': True, 'redis': True, 'ingest_lag': True},
        )

    def test_readyz_returns_503_on_database_error_without_leaking_details(self):
        with patch('monitoring.health.connection.cursor', side_effect=RuntimeError('secret-pg-password')):
            response = self.client.get('/readyz')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret-pg-password', response.content.decode('utf-8'))
        body = response.json()
        self.assertEqual(body['status'], 'degraded')
        self.assertFalse(body['checks']['database'])

    def test_readyz_returns_503_on_redis_error(self):
        with patch('monitoring.health.get_redis_connection', side_effect=RuntimeError('redis-down-host')):
            response = self.client.get('/readyz')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('redis-down-host', response.content.decode('utf-8'))
        body = response.json()
        self.assertEqual(body['status'], 'degraded')
        self.assertFalse(body['checks']['redis'])
        self.assertFalse(body['checks']['ingest_lag'])

    def test_readyz_returns_503_when_stream_lag_exceeds_threshold(self):
        from django.test import override_settings

        fake_metrics = {'stream_length': 500, 'dlq_length': 0, 'pending_count': 10, 'lag': 250}
        with (
            override_settings(READY_MAX_STREAM_LAG=100),
            patch('monitoring.health.get_stream_metrics', return_value=fake_metrics),
        ):
            response = self.client.get('/readyz')
        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertEqual(body['status'], 'degraded')
        self.assertTrue(body['checks']['database'])
        self.assertTrue(body['checks']['redis'])
        self.assertFalse(body['checks']['ingest_lag'])

    def test_metrics_disabled_by_default_when_token_unset(self):
        from django.test import override_settings

        with override_settings(METRICS_AUTH_TOKEN=''):
            response = self.client.get('/metrics')
        self.assertEqual(response.status_code, 403)

    def test_metrics_requires_valid_bearer_token_and_exposes_prometheus_series(self):
        from django.test import override_settings
        from monitoring.tasks import evaluate_alert_rules

        evaluate_alert_rules()
        with override_settings(METRICS_AUTH_TOKEN='prom-secret-token'):
            no_auth = self.client.get('/metrics')
            self.assertEqual(no_auth.status_code, 401)
            self.assertEqual(no_auth['WWW-Authenticate'], 'Bearer')

            wrong_auth = self.client.get('/metrics', HTTP_AUTHORIZATION='Bearer wrong-token')
            self.assertEqual(wrong_auth.status_code, 401)

            ok = self.client.get('/metrics', HTTP_AUTHORIZATION='Bearer prom-secret-token')
            self.assertEqual(ok.status_code, 200)
            body = ok.content.decode('utf-8')
            self.assertIn('sysroar_ingest_samples_total', body)
            self.assertIn('sysroar_ingest_persisted_total', body)
            self.assertIn('sysroar_ingest_stream_lag', body)
            self.assertIn('sysroar_ingest_dlq_length', body)
            self.assertIn('sysroar_alert_eval_duration_seconds_count', body)
            self.assertIn('sysroar_notification_outbox_pending', body)
            self.assertIn('sysroar_notification_outbox_failed_total', body)


class AgentKeyAndEnrollmentTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.company_a = Company.objects.create(name='Tenant Alpha')
        self.company_b = Company.objects.create(name='Tenant Beta')
        self.user_a = user_model.objects.create_user(
            username='alpha_admin',
            email='alpha@example.com',
            password='secure-password-123',
            company=self.company_a,
            role='admin',
        )
        self.user_b = user_model.objects.create_user(
            username='beta_admin',
            email='beta@example.com',
            password='secure-password-123',
            company=self.company_b,
            role='admin',
        )
        self.token_a = Token.objects.create(user=self.user_a)
        self.token_b = Token.objects.create(user=self.user_b)
        self.server_a1 = Server.unscoped.create(name='alpha-1', company=self.company_a, is_active=True)
        self.server_a2 = Server.unscoped.create(name='alpha-2', company=self.company_a, is_active=True)
        self.server_b1 = Server.unscoped.create(name='beta-1', company=self.company_b, is_active=True)
        self.client_a = APIClient()
        self.client_a.credentials(HTTP_AUTHORIZATION=f'Token {self.token_a.key}')
        self.client_b = APIClient()
        self.client_b.credentials(HTTP_AUTHORIZATION=f'Token {self.token_b.key}')

    def test_enrollment_flow_issues_one_time_key_and_enforces_max_uses(self):
        create_resp = self.client_a.post(
            '/api/monitoring/enrollment-tokens/',
            {'name': 'single-use', 'max_uses': 1, 'expires_in_hours': 1},
            format='json',
        )
        self.assertEqual(create_resp.status_code, 201)
        raw_token = create_resp.data['token']
        self.assertTrue(raw_token.startswith('sre_'))

        list_resp = self.client_a.get('/api/monitoring/enrollment-tokens/')
        self.assertEqual(list_resp.status_code, 200)
        self.assertNotIn('token', list_resp.data['results'][0])
        self.assertNotIn('token_hash', list_resp.data['results'][0])

        anon = APIClient()
        enroll = anon.post(
            reverse('telemetry-enroll'),
            {
                'enrollment_token': raw_token,
                'name': 'enrolled-web-01',
                'hostname': 'web-01.internal',
                'agent_version': '0.1.0',
            },
            format='json',
        )
        self.assertEqual(enroll.status_code, 201)
        self.assertTrue(enroll.data['agent_key'].startswith('srk_'))
        enrolled_server = Server.unscoped.get(id=enroll.data['server_id'])
        self.assertEqual(enrolled_server.company_id, self.company_a.id)

        second_use = anon.post(
            reverse('telemetry-enroll'),
            {'enrollment_token': raw_token, 'name': 'replay-node'},
            format='json',
        )
        self.assertEqual(second_use.status_code, 401)

    def test_agent_key_scoped_to_own_server_and_blocked_from_monitoring_api(self):
        from .models import AgentKey

        key_obj, raw_key = AgentKey.generate(server=self.server_a1, created_by=self.user_a)
        agent_client = APIClient()
        agent_client.credentials(HTTP_AUTHORIZATION=f'AgentKey {raw_key}')

        self.assertEqual(agent_client.get('/api/monitoring/servers/').status_code, 401)
        self.assertEqual(agent_client.get('/api/monitoring/agent-keys/').status_code, 401)
        self.assertEqual(agent_client.get('/api/monitoring/enrollment-tokens/').status_code, 401)
        self.assertEqual(agent_client.post('/api/accounts/auth/ticket/').status_code, 401)

        with patch('telemetry.views.push_to_stream'):
            ok_ingest = agent_client.post(
                reverse('telemetry-ingest'),
                {'server': str(self.server_a1.id), 'cpu_usage': 22.0, 'ram_usage': 41.0},
                format='json',
            )
            self.assertEqual(ok_ingest.status_code, 202)

            same_tenant_other = agent_client.post(
                reverse('telemetry-ingest'),
                {'server': str(self.server_a2.id), 'cpu_usage': 22.0, 'ram_usage': 41.0},
                format='json',
            )
            self.assertEqual(same_tenant_other.status_code, 400)

            cross_tenant = agent_client.post(
                reverse('telemetry-ingest'),
                {'server': str(self.server_b1.id), 'cpu_usage': 22.0, 'ram_usage': 41.0},
                format='json',
            )
            self.assertEqual(cross_tenant.status_code, 400)

        ok_config = agent_client.get(reverse('telemetry-config'), HTTP_X_SERVER_ID=str(self.server_a1.id))
        self.assertEqual(ok_config.status_code, 200)

        other_config = agent_client.get(reverse('telemetry-config'), HTTP_X_SERVER_ID=str(self.server_a2.id))
        self.assertEqual(other_config.status_code, 403)

        ok_inventory = agent_client.post(
            reverse('telemetry-inventory'),
            {'server': str(self.server_a1.id), 'hostname': 'alpha-1.local'},
            format='json',
        )
        self.assertEqual(ok_inventory.status_code, 200)

        other_inventory = agent_client.post(
            reverse('telemetry-inventory'),
            {'server': str(self.server_a2.id), 'hostname': 'spoofed'},
            format='json',
        )
        self.assertEqual(other_inventory.status_code, 400)

        key_obj.revoke()
        revoked_cfg = agent_client.get(reverse('telemetry-config'), HTTP_X_SERVER_ID=str(self.server_a1.id))
        self.assertEqual(revoked_cfg.status_code, 401)

    def test_key_rotation_and_cross_tenant_management_isolation(self):
        create_resp = self.client_a.post(
            '/api/monitoring/agent-keys/',
            {'server': str(self.server_a1.id)},
            format='json',
        )
        self.assertEqual(create_resp.status_code, 201)
        old_key = create_resp.data['key']
        key_id = create_resp.data['id']

        self.assertEqual(self.client_b.get(f'/api/monitoring/agent-keys/{key_id}/').status_code, 404)
        self.assertEqual(self.client_b.post(f'/api/monitoring/agent-keys/{key_id}/revoke/').status_code, 404)
        cross_create = self.client_b.post(
            '/api/monitoring/agent-keys/',
            {'server': str(self.server_a1.id)},
            format='json',
        )
        self.assertEqual(cross_create.status_code, 404)
        cross_rotate = self.client_b.post(
            '/api/monitoring/agent-keys/rotate/',
            {'server': str(self.server_a1.id)},
            format='json',
        )
        self.assertEqual(cross_rotate.status_code, 404)

        rotate_resp = self.client_a.post(
            '/api/monitoring/agent-keys/rotate/',
            {'server': str(self.server_a1.id)},
            format='json',
        )
        self.assertEqual(rotate_resp.status_code, 201)
        new_key = rotate_resp.data['key']
        self.assertNotEqual(old_key, new_key)

        old_agent = APIClient()
        old_agent.credentials(HTTP_AUTHORIZATION=f'AgentKey {old_key}')
        self.assertEqual(old_agent.get(reverse('telemetry-config')).status_code, 401)

        new_agent = APIClient()
        new_agent.credentials(HTTP_AUTHORIZATION=f'AgentKey {new_key}')
        self.assertEqual(new_agent.get(reverse('telemetry-config')).status_code, 200)


class WebhookSsrfAndHmacTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.company_a = Company.objects.create(name='Webhook Tenant A')
        self.company_b = Company.objects.create(name='Webhook Tenant B')
        self.user_a = user_model.objects.create_user(
            username='wh_user_a',
            email='wha@example.com',
            password='VeryStrongPassword!99',
            company=self.company_a,
            role='member',
        )
        self.user_b = user_model.objects.create_user(
            username='wh_user_b',
            email='whb@example.com',
            password='VeryStrongPassword!99',
            company=self.company_b,
            role='member',
        )
        self.server_a = Server.unscoped.create(name='wh-node-a', company=self.company_a)
        self.client_a = APIClient()
        self.client_a.force_authenticate(user=self.user_a)
        self.client_b = APIClient()
        self.client_b.force_authenticate(user=self.user_b)

    def test_ssrf_guard_blocks_private_loopback_metadata_and_non_http_schemes(self):
        from telemetry.notifications.ssrf import SSRFBlockedError, validate_webhook_url

        blocked_urls = [
            'http://127.0.0.1/hook',
            'http://127.0.0.1:8000/admin/',
            'http://[::1]/hook',
            'http://10.0.0.1/internal',
            'http://172.16.0.1/internal',
            'http://192.168.1.1/router',
            'http://169.254.169.254/latest/meta-data/',
            'http://100.64.0.1/cgnat',
            'http://0.0.0.0/zero',
            'http://[::ffff:127.0.0.1]/mapped',
            'file:///etc/passwd',
            'gopher://127.0.0.1:6379/_INFO',
            'https://user:pass@93.184.216.34/hook',
        ]
        for bad_url in blocked_urls:
            with self.subTest(url=bad_url):
                with self.assertRaises(SSRFBlockedError):
                    validate_webhook_url(bad_url)

        with patch(
            'telemetry.notifications.ssrf.socket.getaddrinfo',
            return_value=[(2, 1, 6, '', ('169.254.169.254', 80))],
        ):
            with self.assertRaises(SSRFBlockedError):
                validate_webhook_url('http://rebind.attacker.example/hook')

        api_blocked = self.client_a.post(
            '/api/monitoring/rules/',
            {
                'server': str(self.server_a.id),
                'metric_type': 'cpu',
                'threshold_value': 90.0,
                'notification_type': 'WEBHOOK',
                'notification_target': 'http://169.254.169.254/latest/meta-data/',
            },
            format='json',
        )
        self.assertEqual(api_blocked.status_code, 400)

    def test_webhook_hmac_signature_and_test_endpoint_with_cross_tenant_isolation(self):
        from unittest.mock import MagicMock
        from telemetry.notifications.webhook import WebhookStrategy, verify_webhook_signature

        public_addr = [(2, 1, 6, '', ('93.184.216.34', 443))]
        with patch('telemetry.notifications.ssrf.socket.getaddrinfo', return_value=public_addr):
            create_resp = self.client_a.post(
                '/api/monitoring/rules/',
                {
                    'server': str(self.server_a.id),
                    'metric_type': 'cpu',
                    'threshold_value': 85.0,
                    'notification_type': 'WEBHOOK',
                    'notification_target': 'https://hooks.example.com/alerts',
                },
                format='json',
            )
        self.assertEqual(create_resp.status_code, 201)
        rule_id = create_resp.data['id']
        secret = create_resp.data['webhook_secret']
        self.assertTrue(secret.startswith('whsec_'))
        self.assertTrue(create_resp.data['has_webhook_secret'])

        get_resp = self.client_a.get(f'/api/monitoring/rules/{rule_id}/')
        self.assertEqual(get_resp.status_code, 200)
        self.assertNotIn('webhook_secret', get_resp.data)
        self.assertTrue(get_resp.data['has_webhook_secret'])

        cross_test = self.client_b.post(f'/api/monitoring/rules/{rule_id}/test-webhook/')
        self.assertEqual(cross_test.status_code, 404)

        captured = {}
        fake_response = MagicMock(status_code=200)
        fake_response.raise_for_status = MagicMock()

        def fake_post(url, data, headers, timeout=(3.0, 5.0)):
            captured['url'] = url
            captured['body'] = data
            captured['headers'] = headers
            return fake_response

        with patch('telemetry.notifications.webhook.send_safe_webhook_post', side_effect=fake_post):
            test_resp = self.client_a.post(f'/api/monitoring/rules/{rule_id}/test-webhook/')
        self.assertEqual(test_resp.status_code, 200)
        self.assertTrue(test_resp.data['delivered'])
        self.assertEqual(captured['headers']['X-SysRoar-Event'], 'webhook_test')
        self.assertTrue(
            verify_webhook_signature(
                secret=secret,
                timestamp=captured['headers']['X-SysRoar-Timestamp'],
                raw_body=captured['body'],
                signature_header=captured['headers']['X-SysRoar-Signature-256'],
            )
        )
        self.assertFalse(
            verify_webhook_signature(
                secret='wrong-secret',
                timestamp=captured['headers']['X-SysRoar-Timestamp'],
                raw_body=captured['body'],
                signature_header=captured['headers']['X-SysRoar-Signature-256'],
            )
        )

        redirect_resp = MagicMock(status_code=302)
        rule = AlertRule.unscoped.get(id=rule_id)
        with (
            patch('telemetry.notifications.webhook.send_safe_webhook_post', return_value=redirect_resp),
            patch('monitoring.tasks.record_system_event.delay'),
        ):
            self.assertFalse(
                WebhookStrategy().send_alert(
                    self.server_a,
                    rule,
                    {'value': 95.0, 'timestamp': timezone.now().isoformat()},
                )
            )
