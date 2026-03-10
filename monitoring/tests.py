from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from django.core import mail
from accounts.models import Company
from .models import Server, AlertRule, SystemEvent
from telemetry.models import MetricLog
from .tasks import evaluate_metrics_batch, check_system_health, record_system_event

class MonitoringEvaluationTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Test Corp")
        self.server = Server.objects.create(
            name="Test Server", 
            company=self.company, 
            is_active=True
        )
        self.rule = AlertRule.objects.create(
            server=self.server,
            company=self.company,
            metric_type='cpu',
            threshold_value=90.0,
            is_active=True
        )

    def test_evaluate_metrics_breach(self):
        """
        Verify that a breach is correctly identified when threshold is exceeded.
        """
        from django.utils import timezone
        log = MetricLog.objects.create(
            server=self.server,
            company=self.company,
            cpu_usage=95.0,
            ram_usage=50.0,
            timestamp=timezone.now()
        )
        evaluate_metrics_batch([str(log.id)])

    def test_evaluate_metrics_healthy(self):
        """
        Verify that no breach is flagged when metrics are below threshold.
        """
        from django.utils import timezone
        log = MetricLog.objects.create(
            server=self.server,
            company=self.company,
            cpu_usage=80.0,
            ram_usage=50.0,
            timestamp=timezone.now()
        )
        evaluate_metrics_batch([str(log.id)])

@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class SystemHealthMonitoringTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Test Company")

    def test_auth_failure_logs_event(self):
        """
        Verify that a failed authentication attempt triggers a SystemEvent record.
        """
        # Attempt to access a protected endpoint with an invalid token
        self.client.get(
            '/api/monitoring/servers/', 
            HTTP_AUTHORIZATION='Token invalid_token'
        )
        
        events = SystemEvent.objects.filter(event_type='FAILED_AUTHENTICATION')
        self.assertTrue(events.exists(), "FAILED_AUTHENTICATION event not found in database")
        self.assertEqual(events.count(), 1)
        # Check metadata
        self.assertEqual(events.first().context['path'], '/api/monitoring/servers/')

    def test_system_health_alert_threshold(self):
        """
        Verify that check_system_health sends an email when thresholds are exceeded.
        """
        # Set a low threshold for testing
        with self.settings(
            ADMINS=[('Admin', 'admin@example.com')],
            SYSTEM_EVENT_THRESHOLDS={'TEST_EVENT': 3},
            DEFAULT_FROM_EMAIL='noreply@sysroar.com'
        ):
            # Create 3 events
            for _ in range(3):
                SystemEvent.objects.create(event_type='TEST_EVENT', severity='ERROR')
            
            # Run the health check
            check_system_health()
            
            # Verify email sent
            self.assertEqual(len(mail.outbox), 1)
            self.assertIn("System Health Warning", mail.outbox[0].subject)
            self.assertIn("TEST_EVENT: 3 occurrences", mail.outbox[0].body)

    def test_async_event_recording_task(self):
        """
        Directly test the record_system_event task.
        """
        record_system_event('MANUAL_TEST', severity='WARNING', context={'foo': 'bar'})
        
        event = SystemEvent.objects.get(event_type='MANUAL_TEST')
        self.assertEqual(event.severity, 'WARNING')
        self.assertEqual(event.context['foo'], 'bar')
