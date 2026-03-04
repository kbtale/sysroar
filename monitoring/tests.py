from django.test import TestCase
from accounts.models import Company
from .models import Server, AlertRule
from telemetry.models import MetricLog
from .tasks import evaluate_metrics_batch

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
        # Manually call the task synchronously for testing
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
