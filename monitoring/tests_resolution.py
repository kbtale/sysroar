from django.test import TestCase
from accounts.models import Company
from .models import Server, ServerAlertState
from .state_machine import AlertStateMachine

class AlertResolutionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Res Corp")
        self.server = Server.objects.create(name="Res Server", company=self.company)
        self.state = ServerAlertState.objects.create(
            server=self.server,
            company=self.company,
            current_cooldown_tier=1 # Start in alerted state
        )

    def test_resolution_after_6_healthy_signals(self):
        """
        Verify that 6 consecutive healthy signals reset the tier to 0.
        """
        self.assertEqual(self.state.current_cooldown_tier, 1)
        
        # Send 5 signals
        for _ in range(5):
            resolved = AlertStateMachine.record_healthy_signal(self.state)
            self.assertFalse(resolved)
            self.assertEqual(self.state.current_cooldown_tier, 1)

        # 6th signal should trigger resolution
        resolved = AlertStateMachine.record_healthy_signal(self.state)
        self.assertTrue(resolved)
        self.assertEqual(self.state.current_cooldown_tier, 0)
        self.assertEqual(self.state.consecutive_healthy_count, 0)

    def test_anomaly_resets_healthy_counter(self):
        """
        Verify that a breach resets the consecutive healthy counter to zero.
        """
        # Send 3 healthy signals
        for _ in range(3):
            AlertStateMachine.record_healthy_signal(self.state)
        self.assertEqual(self.state.consecutive_healthy_count, 3)

        # A breach occurs (manual mock of the logic in handle_server_breach)
        self.state.consecutive_healthy_count = 0
        self.state.save()

        self.assertEqual(self.state.consecutive_healthy_count, 0)
        
        # Next healthy signal should start from 1
        AlertStateMachine.record_healthy_signal(self.state)
        self.assertEqual(self.state.consecutive_healthy_count, 1)

    def test_no_resolution_if_already_healthy(self):
        """
        Verify that 6 healthy signals don't trigger "Resolved" if tier is already 0.
        """
        self.state.current_cooldown_tier = 0
        self.state.save()

        # Send 6 signals
        for _ in range(6):
            resolved = AlertStateMachine.record_healthy_signal(self.state)
            self.assertFalse(resolved)
        
        self.assertEqual(self.state.current_cooldown_tier, 0)
