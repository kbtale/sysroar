import logging
from django.db import transaction, DatabaseError
from celery import shared_task
from .models import AlertRule, Server, ServerAlertState
from .state_machine import AlertStateMachine
from telemetry.models import MetricLog
from telemetry.notifications.dispatcher import NotificationDispatcher

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
        breached_rules_with_context = []
        
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
                breached_rules_with_context.append({
                    'rule': rule,
                    'context': {
                        'value': value,
                        'timestamp': log.timestamp.isoformat() if log.timestamp else None
                    }
                })

        if breached_rules_with_context:
            handle_server_breach(log.server_id, breached_rules_with_context)
        else:
            handle_server_healthy(log.server_id)

def handle_server_breach(server_id, breached_rules_with_context):
    """
    Manages the alert state for a server when a breach is detected.
    Uses row-level locking to prevent concurrent workers from sending duplicate alerts.
    """
    try:
        with transaction.atomic():
            # Lock the state row for this server
            server = Server.unscoped.get(id=server_id)
            state, created = ServerAlertState.unscoped.select_for_update().get_or_create(
                server_id=server_id,
                defaults={'company_id': server.company_id}
            )
            
            # Reset consecutive healthy count - an anomaly stops the recovery process
            state.consecutive_healthy_count = 0
            
            if AlertStateMachine.should_fire_alert(state):
                dispatch_alert_notifications(server, breached_rules_with_context)
            else:
                state.save()
    except DatabaseError as e:
        logger.error(f"POSTGRES_TRANSACTION_ROLLBACK | Failed to update alert state for server {server_id}: {str(e)}", exc_info=True)
        raise

def handle_server_healthy(server_id):
    """
    Increments the healthy counter and checks for alert resolution.
    """
    try:
        with transaction.atomic():
            server = Server.unscoped.get(id=server_id)
            state, created = ServerAlertState.unscoped.select_for_update().get_or_create(
                server_id=server_id,
                defaults={'company_id': server.company_id}
            )
            
            if AlertStateMachine.record_healthy_signal(state):
                # When resolved, notify ALL active rules for this server
                rules = AlertRule.unscoped.filter(server=server, is_active=True)
                dispatch_resolution_notifications(server, rules)
    except DatabaseError as e:
        logger.error(f"POSTGRES_TRANSACTION_ROLLBACK | Failed to record healthy signal for server {server_id}: {str(e)}", exc_info=True)
        raise

def dispatch_alert_notifications(server, breached_rules_with_context):
    """
    Dispatches breach notifications using the Strategy Pattern dispatcher.
    """
    for item in breached_rules_with_context:
        rule = item['rule']
        context = item['context']
        NotificationDispatcher.dispatch_alert(server, rule, context)
    
    logger.info(f"AUDIT | ALERT | {server.name} | Total Rules: {len(breached_rules_with_context)}")

def dispatch_resolution_notifications(server, rules):
    """
    Dispatches resolution notifications for all configured rules on the server.
    """
    context = {
        'timestamp': timezone.now().isoformat()
    }
    for rule in rules:
        NotificationDispatcher.dispatch_resolution(server, rule, context)
    
    logger.info(f"AUDIT | RESOLVED | {server.name} | Notified {rules.count()} channels")
