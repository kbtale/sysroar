from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from accounts.models import Company
from .models import Server, AlertRule, ServerAlertState
from .state_machine import AlertStateMachine

class AlertStateMachineTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="State Corp")
        self.server = Server.objects.create(name="SM Server", company=self.company)
        self.state = ServerAlertState.objects.create(
            server=self.server, 
            company=self.company
        )

    def test_initial_breach_fires_immediately(self):
        """
        Verify that a breach with tier 0 fires immediately.
        """
        self.assertEqual(self.state.current_cooldown_tier, 0)
        self.assertTrue(AlertStateMachine.should_fire_alert(self.state))
        self.assertEqual(self.state.current_cooldown_tier, 1)

    def test_cooldown_suppression(self):
        """
        Verify that a second breach within the cooldown period is suppressed.
        """
        # Fire first alert (Tier 0 -> 1)
        AlertStateMachine.should_fire_alert(self.state)
        self.assertEqual(self.state.current_cooldown_tier, 1)
        
        # Immediate second breach should be suppressed (3-min cooldown)
        self.assertFalse(AlertStateMachine.should_fire_alert(self.state))
        self.assertEqual(self.state.current_cooldown_tier, 1) # Tier stays same if suppressed

    def test_cooldown_expiration_progression(self):
        """
        Verify that alerts fire after cooldown expires and tiers advance.
        """
        # Fire first alert (Tier 0 -> 1)
        AlertStateMachine.should_fire_alert(self.state)
        
        # Simulate time passing (3 mins 1 second)
        expired_time = timezone.now() - timedelta(minutes=3, seconds=1)
        self.state.last_alert_sent_at = expired_time
        self.state.save()
        
        # Should fire now and move to Tier 2
        self.assertTrue(AlertStateMachine.should_fire_alert(self.state))
        self.assertEqual(self.state.current_cooldown_tier, 2)

    def test_max_tier_limit(self):
        """
        Verify that the tier does not exceed the maximum.
        """
        self.state.current_cooldown_tier = 5
        self.state.last_alert_sent_at = timezone.now() - timedelta(minutes=61)
        self.state.save()
        
        self.assertTrue(AlertStateMachine.should_fire_alert(self.state))
        self.assertEqual(self.state.current_cooldown_tier, 5)
