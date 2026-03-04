from django.utils import timezone
from datetime import timedelta

class AlertStateMachine:
    TIERS = {
        0: 0,       # Initial breach: no cooldown
        1: 3,       # Tier 1: 3 minutes
        2: 5,       # Tier 2: 5 minutes
        3: 10,      # Tier 3: 10 minutes
        4: 30,      # Tier 4: 30 minutes
        5: 60,      # Tier 5: 60 minutes
    }
    MAX_TIER = 5

    @classmethod
    def should_fire_alert(cls, state_instance):
        """
        Determines if a new alert should be dispatched based on cooldown.
        Updates state_instance fields if alert is allowed to fire.
        Returns True if alert should be sent, False if suppressed by cooldown.
        """
        now = timezone.now()
        current_tier = state_instance.current_cooldown_tier
        last_sent = state_instance.last_alert_sent_at

        # Tier 0 (No active alert): Fire immediately
        if current_tier == 0 or last_sent is None:
            cls._update_state(state_instance, now)
            return True

        # Check if cooldown has expired for current tier
        cooldown_minutes = cls.TIERS.get(current_tier, cls.TIERS[cls.MAX_TIER])
        if now >= last_sent + timedelta(minutes=cooldown_minutes):
            cls._update_state(state_instance, now)
            return True

        return False

    @classmethod
    def _update_state(cls, state_instance, timestamp):
        """
        Progresses the state machine to the next tier and updates timestamp.
        """
        state_instance.last_alert_sent_at = timestamp
        if state_instance.current_cooldown_tier < cls.MAX_TIER:
            state_instance.current_cooldown_tier += 1
        state_instance.save()
