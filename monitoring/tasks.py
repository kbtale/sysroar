import logging
from celery import shared_task
from .models import AlertRule, Server
from telemetry.models import MetricLog

logger = logging.getLogger(__name__)

@shared_task(name="monitoring.evaluate_metrics_batch")
def evaluate_metrics_batch(metric_log_ids):
    """
    Evaluates a batch of metric logs against configured alert rules.
    """
    logs = MetricLog.objects.filter(id__in=metric_log_ids).select_related('server')
    if not logs:
        return
    
    # Pre-fetch rules for these servers to avoid N+1
    server_ids = {log.server_id for log in logs}
    rules = AlertRule.objects.filter(server_id__in=server_ids, is_active=True)
    
    # Organize rules by server for quick lookup
    rules_by_server = {}
    for rule in rules:
        if rule.server_id not in rules_by_server:
            rules_by_server[rule.server_id] = []
        rules_by_server[rule.server_id].append(rule)

    for log in logs:
        server_rules = rules_by_server.get(log.server_id, [])
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
