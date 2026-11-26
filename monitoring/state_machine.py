from datetime import timedelta
from django.utils import timezone


class AlertStateMachine:
    TIERS = {
        0: 0,
        1: 3,
        2: 5,
        3: 10,
        4: 30,
        5: 60,
    }
    MAX_TIER = 5
    FLAP_WINDOW_MINUTES = 15
    FLAP_TRANSITION_THRESHOLD = 4

    @classmethod
    def evaluate_condition(cls, value: float, operator: str, threshold: float) -> bool:
        if operator == 'gt':
            return value > threshold
        if operator == 'gte':
            return value >= threshold
        if operator == 'lt':
            return value < threshold
        if operator == 'lte':
            return value <= threshold
        return value > threshold

    @classmethod
    def is_recovered(cls, value: float, operator: str, threshold: float, hysteresis_margin: float = 0.0) -> bool:
        margin = max(float(hysteresis_margin or 0.0), 0.0)
        if operator == 'gt':
            return value <= threshold - margin
        if operator == 'gte':
            return value < threshold - margin if margin == 0.0 else value <= threshold - margin
        if operator == 'lt':
            return value >= threshold + margin
        if operator == 'lte':
            return value > threshold + margin if margin == 0.0 else value >= threshold + margin
        return value <= threshold - margin

    @classmethod
    def compute_resolution_threshold(
        cls,
        duration_minutes: int,
        telemetry_cadence: int,
        eval_interval_seconds: int = 30,
    ) -> int:
        step = max(int(eval_interval_seconds), int(telemetry_cadence or 30), 10)
        target_window = max(int(duration_minutes or 0) * 60, step * 2)
        cycles = round(target_window / step)
        return max(2, min(12, cycles))

    @classmethod
    def _record_transition(cls, state, now):
        cutoff = (now - timedelta(minutes=cls.FLAP_WINDOW_MINUTES)).timestamp()
        history = [ts for ts in (state.transition_history or []) if ts >= cutoff]
        history.append(now.timestamp())
        state.transition_history = history
        state.is_flapping = len(history) >= cls.FLAP_TRANSITION_THRESHOLD

    @classmethod
    def _prune_flapping(cls, state, now):
        cutoff = (now - timedelta(minutes=cls.FLAP_WINDOW_MINUTES)).timestamp()
        history = [ts for ts in (state.transition_history or []) if ts >= cutoff]
        state.transition_history = history
        state.is_flapping = len(history) >= cls.FLAP_TRANSITION_THRESHOLD

    @classmethod
    def evaluate_rule_state(cls, state, rule, value: float, now=None, eval_interval_seconds: int = 30):
        now = now or timezone.now()
        cls._prune_flapping(state, now)

        breaching = cls.evaluate_condition(value, rule.operator, rule.threshold_value)
        action = None

        if state.status in ('OK', 'RESOLVED'):
            if breaching:
                if rule.duration_minutes == 0:
                    state.status = 'FIRING'
                    state.pending_since = now
                    state.firing_since = now
                    state.consecutive_healthy_count = 0
                    cls._record_transition(state, now)
                    if not state.is_flapping:
                        state.last_alert_sent_at = now
                        state.current_cooldown_tier = 1
                        action = 'ALERT'
                else:
                    state.status = 'PENDING'
                    state.pending_since = now
                    state.consecutive_healthy_count = 0
            elif state.status == 'RESOLVED':
                state.status = 'OK'
                state.pending_since = None

        elif state.status == 'PENDING':
            if breaching:
                pending_since = state.pending_since or now
                state.pending_since = pending_since
                if now >= pending_since + timedelta(minutes=rule.duration_minutes):
                    state.status = 'FIRING'
                    state.firing_since = now
                    state.consecutive_healthy_count = 0
                    cls._record_transition(state, now)
                    if not state.is_flapping:
                        state.last_alert_sent_at = now
                        state.current_cooldown_tier = 1
                        action = 'ALERT'
            else:
                state.status = 'OK'
                state.pending_since = None
                state.consecutive_healthy_count = 0

        elif state.status == 'FIRING':
            recovered = cls.is_recovered(value, rule.operator, rule.threshold_value, rule.hysteresis_margin)
            if not recovered:
                state.consecutive_healthy_count = 0
                if not state.is_flapping:
                    cooldown_minutes = cls.TIERS.get(state.current_cooldown_tier, cls.TIERS[cls.MAX_TIER])
                    if state.last_alert_sent_at is None or now >= state.last_alert_sent_at + timedelta(
                        minutes=cooldown_minutes
                    ):
                        state.last_alert_sent_at = now
                        if state.current_cooldown_tier < cls.MAX_TIER:
                            state.current_cooldown_tier += 1
                        action = 'ALERT'
            else:
                state.consecutive_healthy_count += 1
                required = cls.compute_resolution_threshold(
                    rule.duration_minutes,
                    rule.server.telemetry_cadence,
                    eval_interval_seconds=eval_interval_seconds,
                )
                if state.consecutive_healthy_count >= required:
                    state.status = 'RESOLVED'
                    state.resolved_at = now
                    state.pending_since = None
                    state.firing_since = None
                    state.consecutive_healthy_count = 0
                    state.current_cooldown_tier = 0
                    cls._record_transition(state, now)
                    if not state.is_flapping:
                        action = 'RESOLUTION'

        state.last_value = value
        state.last_evaluated_at = now
        state.save()
        return action

    @classmethod
    def should_fire_alert(cls, state_instance):
        now = timezone.now()
        current_tier = state_instance.current_cooldown_tier
        last_sent = state_instance.last_alert_sent_at

        if current_tier == 0 or last_sent is None:
            cls._update_state(state_instance, now)
            return True

        cooldown_minutes = cls.TIERS.get(current_tier, cls.TIERS[cls.MAX_TIER])
        if now >= last_sent + timedelta(minutes=cooldown_minutes):
            cls._update_state(state_instance, now)
            return True

        return False

    @classmethod
    def record_healthy_signal(cls, state_instance):
        state_instance.consecutive_healthy_count += 1

        if state_instance.consecutive_healthy_count >= 6 and state_instance.current_cooldown_tier > 0:
            state_instance.current_cooldown_tier = 0
            state_instance.consecutive_healthy_count = 0
            state_instance.save()
            return True

        state_instance.save()
        return False

    @classmethod
    def _update_state(cls, state_instance, timestamp):
        state_instance.last_alert_sent_at = timestamp
        if state_instance.current_cooldown_tier < cls.MAX_TIER:
            state_instance.current_cooldown_tier += 1
        state_instance.save()
