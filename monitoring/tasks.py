import logging
from django.db import transaction
from celery import shared_task
from .models import AlertRule, Server, ServerAlertState
from .state_machine import AlertStateMachine
from telemetry.models import MetricLog

logger = logging.getLogger(__name__)

@shared_task(name="monitoring.evaluate_metrics_batch")
def evaluate_metrics_batch(metric_log_ids):
    """
    Evaluates a batch of metric logs against configured alert rules.
    """
    logs = MetricLog.unscoped.filter(id__in=metric_log_ids).select_related('server')
    if not logs:
        return
    
    server_ids = {log.server_id for log in logs}
    rules = AlertRule.unscoped.filter(server_id__in=server_ids, is_active=True)
    
    rules_by_server = {}
    for rule in rules:
        if rule.server_id not in rules_by_server:
            rules_by_server[rule.server_id] = []
        rules_by_server[rule.server_id].append(rule)

    for log in logs:
        server_rules = rules_by_server.get(log.server_id, [])
        is_breached = False
        
        for rule in server_rules:
            value = None
            if rule.metric_type == 'cpu':
                value = log.cpu_usage
            elif rule.metric_type == 'ram':
                value = log.ram_usage
            elif rule.metric_type == 'disk':
                value = log.disk_io

            if value is not None and value > rule.threshold_value:
                logger.info(f"Threshold breached: {rule} on {log.server.name} ({rule.metric_type}: {value} > {rule.threshold_value})")
                is_breached = True
                break # One breach is enough to trigger the state machine for this payload

        if is_breached:
            handle_server_breach(log.server_id)
        else:
            handle_server_healthy(log.server_id)

def handle_server_breach(server_id):
    """
    Manages the alert state for a server when a breach is detected.
    Uses row-level locking to prevent concurrent workers from sending duplicate alerts.
    """
    with transaction.atomic():
        # Lock the state row for this server
        state, created = ServerAlertState.unscoped.select_for_update().get_or_create(
            server_id=server_id,
            defaults={'company_id': Server.unscoped.get(id=server_id).company_id}
        )
        
        # Reset consecutive healthy count IMMEDIATELY - an anomaly stops the recovery process
        state.consecutive_healthy_count = 0
        
        if AlertStateMachine.should_fire_alert(state):
            dispatch_alert_notification(state)
        else:
            state.save()

def handle_server_healthy(server_id):
    """
    Increments the healthy counter and checks for alert resolution.
    """
    with transaction.atomic():
        state, created = ServerAlertState.unscoped.select_for_update().get_or_create(
            server_id=server_id,
            defaults={'company_id': Server.unscoped.get(id=server_id).company_id}
        )
        
        if AlertStateMachine.record_healthy_signal(state):
            dispatch_resolution_notification(state)

def dispatch_alert_notification(state):
    """
    Dispatches a breach notification to the configured alerts channels.
    """
    logger.info(f"AUDIT | ALERT | {state.server.name} | Tier {state.current_cooldown_tier}")

def dispatch_resolution_notification(state):
    """
    Dispatches a resolution notification to the configured alerts channels.
    """
    logger.info(f"AUDIT | RESOLVED | {state.server.name}")
