from collections import defaultdict
import logging
import time
from datetime import timedelta
from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db import DatabaseError, transaction
from django.db.models import Avg, Count, Max, Min
from django.utils import timezone
from telemetry.models import MetricLog
from telemetry.notifications.dispatcher import NotificationDispatcher
from .metrics import ALERT_EVAL_DURATION_SECONDS, NOTIFICATION_OUTBOX_FAILED_TOTAL
from .models import (
    AlertRule,
    AlertSilence,
    AlertState,
    Incident,
    MaintenanceWindow,
    NotificationOutbox,
    Server,
    ServerAlertState,
    SystemEvent,
    UptimeCheck,
    UptimeCheckResult,
)
from .state_machine import AlertStateMachine

logger = logging.getLogger(__name__)

_METRIC_COLUMN_MAP = {
    'cpu': 'cpu_usage',
    'ram': 'ram_usage',
    'disk': 'disk_usage',
    'disk_io': 'disk_io',
    'swap': 'swap_usage',
    'load': 'load_1m',
}

_AGG_FUNC_MAP = {
    'avg': Avg,
    'max': Max,
    'min': Min,
}


def _aggregate_rule_window(rule, now):
    column = _METRIC_COLUMN_MAP.get(rule.metric_type)
    if not column:
        return None
    agg_cls = _AGG_FUNC_MAP.get(rule.aggregation, Avg)
    window_seconds = max(int(rule.duration_minutes or 0) * 60, int(rule.server.telemetry_cadence or 30) * 2, 60)
    window_start = now - timedelta(seconds=window_seconds)
    result = MetricLog.unscoped.filter(
        company_id=rule.company_id,
        server_id=rule.server_id,
        timestamp__gte=window_start,
        timestamp__lte=now,
    ).aggregate(val=agg_cls(column))
    return result.get('val')


def _compute_backoff_seconds(attempts: int) -> int:
    return min(30 * (2 ** max(attempts - 1, 0)), 900)


@shared_task(name='monitoring.evaluate_alert_rules', ignore_result=True)
def evaluate_alert_rules(now=None, eval_interval_seconds: int = 30):
    started_at = time.monotonic()
    try:
        now = now or timezone.now()
        active_rules = list(
            AlertRule.unscoped.filter(is_active=True, server__is_active=True)
            .exclude(metric_type='no_data')
            .select_related('server')
        )
        if not active_rules:
            return {'evaluated': 0, 'enqueued': 0}

        evaluated = 0
        enqueued = 0
        pending_alert_groups = defaultdict(list)

        for rule in active_rules:
            agg_value = _aggregate_rule_window(rule, now)
            if agg_value is None:
                continue
            evaluated += 1
            try:
                with transaction.atomic():
                    state, _ = AlertState.unscoped.select_for_update().get_or_create(
                        rule=rule,
                        defaults={'company_id': rule.company_id},
                    )
                    action = AlertStateMachine.evaluate_rule_state(
                        state,
                        rule,
                        float(agg_value),
                        now=now,
                        eval_interval_seconds=eval_interval_seconds,
                    )
                    if action == 'ALERT':
                        if MaintenanceWindow.is_in_maintenance(
                            company_id=rule.company_id,
                            server=rule.server,
                            tags=rule.server.tags,
                            now=now,
                        ):
                            continue
                        open_incident = Incident.unscoped.filter(
                            company_id=rule.company_id,
                            server=rule.server,
                            rule=rule,
                            status__in=('open', 'acknowledged'),
                        ).first()
                        if open_incident is None:
                            Incident.unscoped.create(
                                company_id=rule.company_id,
                                server=rule.server,
                                rule=rule,
                                title=(
                                    f'{rule.server.name}: {rule.get_metric_type_display()} '
                                    f'{rule.get_operator_display()} {rule.threshold_value}'
                                ),
                                severity=rule.severity,
                                status='open',
                                trigger_value=round(float(agg_value), 2),
                                opened_at=now,
                            )
                        if AlertSilence.is_silenced(
                            company_id=rule.company_id,
                            server_id=rule.server_id,
                            rule_id=rule.id,
                            now=now,
                        ):
                            continue
                        group_key = (
                            str(rule.company_id),
                            rule.notification_type,
                            rule.notification_target,
                        )
                        pending_alert_groups[group_key].append((rule, round(float(agg_value), 2)))
                    elif action == 'RESOLUTION':
                        Incident.unscoped.filter(
                            company_id=rule.company_id,
                            server=rule.server,
                            rule=rule,
                            status__in=('open', 'acknowledged'),
                        ).update(status='resolved', resolved_at=now)
                        outbox = NotificationOutbox.unscoped.create(
                            company_id=rule.company_id,
                            server=rule.server,
                            rule=rule,
                            event_type='RESOLUTION',
                            payload={
                                'value': round(float(agg_value), 2),
                                'severity': rule.severity,
                                'operator': rule.get_operator_display(),
                                'threshold': rule.threshold_value,
                                'timestamp': now.isoformat(),
                            },
                        )
                        enqueued += 1
                        outbox_id = str(outbox.id)
                        transaction.on_commit(lambda oid=outbox_id: deliver_notification_outbox.delay(oid))
            except DatabaseError as exc:
                logger.error(
                    f'POSTGRES_TRANSACTION_ROLLBACK | Failed evaluating rule {rule.id}: {exc}',
                    exc_info=True,
                )
                record_system_event.delay(
                    event_type='POSTGRES_TRANSACTION_ROLLBACK',
                    severity='CRITICAL',
                    context={'rule_id': str(rule.id), 'error': str(exc)},
                )

        for items in pending_alert_groups.values():
            primary_rule, primary_val = items[0]
            if len(items) == 1:
                payload = {
                    'value': primary_val,
                    'severity': primary_rule.severity,
                    'operator': primary_rule.get_operator_display(),
                    'threshold': primary_rule.threshold_value,
                    'timestamp': now.isoformat(),
                }
            else:
                summaries = [
                    {
                        'server': r.server.name,
                        'metric': r.get_metric_type_display(),
                        'value': val,
                        'threshold': r.threshold_value,
                        'severity': r.severity,
                    }
                    for r, val in items
                ]
                joined = ', '.join(f'{s["server"]} {s["metric"]}={s["value"]}' for s in summaries[:5])
                payload = {
                    'value': f'{len(items)} grouped alerts: {joined}',
                    'severity': 'critical' if any(r.severity == 'critical' for r, _ in items) else 'warning',
                    'operator': primary_rule.get_operator_display(),
                    'threshold': primary_rule.threshold_value,
                    'grouped_count': len(items),
                    'grouped_alerts': summaries,
                    'timestamp': now.isoformat(),
                }
            with transaction.atomic():
                outbox = NotificationOutbox.unscoped.create(
                    company_id=primary_rule.company_id,
                    server=primary_rule.server,
                    rule=primary_rule,
                    event_type='ALERT',
                    payload=payload,
                )
                enqueued += 1
                outbox_id = str(outbox.id)
                transaction.on_commit(lambda oid=outbox_id: deliver_notification_outbox.delay(oid))

        return {'evaluated': evaluated, 'enqueued': enqueued}
    finally:
        ALERT_EVAL_DURATION_SECONDS.observe(time.monotonic() - started_at)


@shared_task(name='monitoring.deliver_notification_outbox', ignore_result=True)
def deliver_notification_outbox(outbox_id: str):
    now = timezone.now()
    with transaction.atomic():
        outbox = (
            NotificationOutbox.unscoped.select_for_update()
            .select_related('server', 'rule')
            .filter(id=outbox_id, status='PENDING')
            .first()
        )
        if outbox is None:
            return False
        server = outbox.server
        rule = outbox.rule
        event_type = outbox.event_type
        payload = dict(outbox.payload or {})

    success = False
    error_msg = ''
    try:
        if event_type == 'ALERT':
            success = NotificationDispatcher.dispatch_alert(server, rule, payload)
        else:
            success = NotificationDispatcher.dispatch_resolution(server, rule, payload)
        if not success:
            error_msg = 'Notification strategy returned False'
    except Exception as exc:
        error_msg = str(exc)
        logger.error(f'Outbox {outbox_id} delivery exception: {exc}', exc_info=True)

    with transaction.atomic():
        outbox = NotificationOutbox.unscoped.select_for_update().filter(id=outbox_id).first()
        if outbox is None or outbox.status != 'PENDING':
            return success
        outbox.attempts += 1
        if success:
            outbox.status = 'DELIVERED'
            outbox.delivered_at = timezone.now()
            outbox.last_error = ''
            outbox.save()
            return True

        outbox.last_error = error_msg[:1000]
        NOTIFICATION_OUTBOX_FAILED_TOTAL.inc(1)
        if outbox.attempts >= outbox.max_attempts:
            outbox.status = 'FAILED'
            outbox.save()
            record_system_event.delay(
                event_type='NOTIFICATION_OUTBOX_EXHAUSTED',
                severity='ERROR',
                context={'outbox_id': str(outbox.id), 'rule_id': str(outbox.rule_id), 'error': outbox.last_error},
            )
            return False

        backoff = _compute_backoff_seconds(outbox.attempts)
        outbox.next_attempt_at = now + timedelta(seconds=backoff)
        outbox.save()
        transaction.on_commit(
            lambda oid=str(outbox.id), cd=backoff: deliver_notification_outbox.apply_async(args=[oid], countdown=cd)
        )
        return False


@shared_task(name='monitoring.retry_pending_outbox', ignore_result=True)
def retry_pending_outbox():
    now = timezone.now()
    due_ids = list(
        NotificationOutbox.unscoped.filter(status='PENDING', next_attempt_at__lte=now)
        .values_list('id', flat=True)[:200]
    )
    for outbox_id in due_ids:
        deliver_notification_outbox.delay(str(outbox_id))
    return len(due_ids)


@shared_task(name='monitoring.evaluate_metrics_batch', ignore_result=True)
def evaluate_metrics_batch(metric_log_ids):
    logs = MetricLog.unscoped.filter(id__in=metric_log_ids).select_related('server').order_by('timestamp')
    if not logs:
        return

    server_ids = {log.server_id for log in logs}
    rules = AlertRule.unscoped.filter(server_id__in=server_ids, is_active=True)

    rules_by_server = {}
    for rule in rules:
        rules_by_server.setdefault(rule.server_id, []).append(rule)

    for log in logs:
        server_rules = rules_by_server.get(log.server_id, [])
        if not server_rules:
            continue
        breached_rules_with_context = []

        for rule in server_rules:
            col = _METRIC_COLUMN_MAP.get(rule.metric_type)
            value = getattr(log, col, None) if col else None
            if value is not None and AlertStateMachine.evaluate_condition(value, rule.operator, rule.threshold_value):
                breached_rules_with_context.append({
                    'rule': rule,
                    'context': {
                        'value': value,
                        'timestamp': log.timestamp.isoformat() if log.timestamp else None,
                    },
                })

        if breached_rules_with_context:
            handle_server_breach(log.server_id, breached_rules_with_context)
        else:
            handle_server_healthy(log.server_id)


def handle_server_breach(server_id, breached_rules_with_context):
    try:
        with transaction.atomic():
            server = Server.unscoped.get(id=server_id)
            state, _ = ServerAlertState.unscoped.select_for_update().get_or_create(
                server_id=server_id,
                defaults={'company_id': server.company_id},
            )
            state.consecutive_healthy_count = 0
            if AlertStateMachine.should_fire_alert(state):
                dispatch_alert_notifications(server, breached_rules_with_context)
            else:
                state.save()
    except DatabaseError as e:
        logger.error(
            f'POSTGRES_TRANSACTION_ROLLBACK | Failed to update alert state for server {server_id}: {str(e)}',
            exc_info=True,
        )
        record_system_event.delay(
            event_type='POSTGRES_TRANSACTION_ROLLBACK',
            severity='CRITICAL',
            context={'server_id': server_id, 'operation': 'handle_server_breach', 'error': str(e)},
        )
        raise


def handle_server_healthy(server_id):
    try:
        with transaction.atomic():
            server = Server.unscoped.get(id=server_id)
            state, _ = ServerAlertState.unscoped.select_for_update().get_or_create(
                server_id=server_id,
                defaults={'company_id': server.company_id},
            )
            if AlertStateMachine.record_healthy_signal(state):
                rules = AlertRule.unscoped.filter(server=server, is_active=True)
                dispatch_resolution_notifications(server, rules)
    except DatabaseError as e:
        logger.error(
            f'POSTGRES_TRANSACTION_ROLLBACK | Failed to record healthy signal for server {server_id}: {str(e)}',
            exc_info=True,
        )
        record_system_event.delay(
            event_type='POSTGRES_TRANSACTION_ROLLBACK',
            severity='CRITICAL',
            context={'server_id': server_id, 'operation': 'handle_server_healthy', 'error': str(e)},
        )
        raise


def dispatch_alert_notifications(server, breached_rules_with_context):
    for item in breached_rules_with_context:
        NotificationDispatcher.dispatch_alert(server, item['rule'], item['context'])
    logger.info(f'AUDIT | ALERT | {server.name} | Total Rules: {len(breached_rules_with_context)}')


def dispatch_resolution_notifications(server, rules):
    context = {'timestamp': timezone.now().isoformat()}
    for rule in rules:
        NotificationDispatcher.dispatch_resolution(server, rule, context)
    logger.info(f'AUDIT | RESOLVED | {server.name} | Notified {rules.count()} channels')


@shared_task(name='monitoring.record_system_event', ignore_result=True)
def record_system_event(event_type, severity='ERROR', context=None):
    if context is None:
        context = {}
    SystemEvent.objects.create(
        event_type=event_type,
        severity=severity,
        context=context,
    )


@shared_task(name='monitoring.check_system_health', ignore_result=True)
def check_system_health():
    if not getattr(settings, 'ADMINS', None) or not getattr(settings, 'SYSTEM_EVENT_THRESHOLDS', None):
        return

    time_threshold = timezone.now() - timedelta(minutes=15)
    event_counts = (
        SystemEvent.objects.filter(timestamp__gte=time_threshold)
        .values('event_type')
        .annotate(count=Count('id'))
    )

    alerts_to_send = []
    for event in event_counts:
        event_type = event['event_type']
        count = event['count']
        threshold = settings.SYSTEM_EVENT_THRESHOLDS.get(event_type, float('inf'))
        if count >= threshold:
            alerts_to_send.append(f'- {event_type}: {count} occurrences (Threshold: {threshold})')

    if alerts_to_send:
        subject = '[SysRoar Alert] System Health Warning - Anomalies Detected'
        message = (
            'The following internal system events have exceeded their configured '
            'thresholds in the last 15 minutes:\n\n'
        )
        message += '\n'.join(alerts_to_send)
        message += '\n\nPlease check the server logs and SystemEvent dashboard for more details.'

        recipient_list = [admin[1] for admin in settings.ADMINS]
        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                recipient_list,
                fail_silently=False,
            )
            logger.info('Dispatched system health alert to admins.')
        except Exception as e:
            logger.error(f'Failed to dispatch system health alert: {e}')


@shared_task(name='monitoring.purge_old_system_events', ignore_result=True)
def purge_old_system_events():
    retention_days = 30
    cutoff_date = timezone.now() - timedelta(days=retention_days)
    deleted_count, _ = SystemEvent.objects.filter(timestamp__lt=cutoff_date).delete()
    logger.info(f'Purged {deleted_count} outdated SystemEvent records.')


@shared_task(name='monitoring.flush_heartbeats', ignore_result=True)
def flush_heartbeats():
    from monitoring.heartbeat import flush_heartbeats_to_db

    return flush_heartbeats_to_db()


@shared_task(name='monitoring.check_heartbeats', ignore_result=True)
def check_heartbeats():
    from monitoring.heartbeat import check_server_heartbeats

    return check_server_heartbeats()


@shared_task(name='monitoring.run_due_uptime_checks', ignore_result=True)
def run_due_uptime_checks():
    from monitoring.models import UptimeCheck
    from monitoring.uptime import execute_uptime_check

    now = timezone.now()
    executed = 0
    for check_obj in UptimeCheck.unscoped.filter(is_active=True).select_related('channel'):
        if check_obj.last_checked_at is not None:
            elapsed = (now - check_obj.last_checked_at).total_seconds()
            if elapsed < max(30, check_obj.interval_seconds or 60):
                continue
        execute_uptime_check(check_obj, now=now)
        executed += 1
    return {'executed': executed}


@shared_task(name='monitoring.send_daily_digests', ignore_result=True)
def send_daily_digests(now=None):
    from accounts.models import Company, User

    now = now or timezone.now()
    today = now.date()
    since = now - timedelta(hours=24)
    sent = 0

    companies = Company.objects.filter(digest_enabled=True, digest_hour_utc=now.hour).exclude(
        last_digest_sent_on=today
    )
    for company in companies:
        recipients = []
        if company.digest_email:
            recipients = [company.digest_email]
        else:
            recipients = list(
                User.objects.filter(
                    company=company,
                    is_active=True,
                    role__in=(User.ROLE_OWNER, User.ROLE_ADMIN),
                )
                .exclude(email='')
                .values_list('email', flat=True)
            )
        if not recipients:
            continue

        total_servers = Server.unscoped.filter(company=company, is_active=True).count()
        online_servers = Server.unscoped.filter(
            company=company,
            is_active=True,
            last_ping__gte=now - timedelta(minutes=5),
        ).count()
        open_incidents = Incident.unscoped.filter(company=company, status__in=('open', 'acknowledged')).count()
        opened_24h = Incident.unscoped.filter(company=company, opened_at__gte=since).count()
        resolved_24h = Incident.unscoped.filter(company=company, resolved_at__gte=since).count()

        total_checks = UptimeCheck.unscoped.filter(company=company, is_active=True).count()
        results_24h = UptimeCheckResult.unscoped.filter(company=company, checked_at__gte=since)
        res_total = results_24h.count()
        if res_total:
            res_up = results_24h.filter(status='up').count()
            uptime_pct = f'{(res_up / res_total) * 100.0:.2f}%'
        else:
            uptime_pct = 'N/A'

        body = (
            f'SysRoar Daily Digest for {company.name} ({today.isoformat()})\n\n'
            f'Fleet: {online_servers}/{total_servers} active servers online\n'
            f'Incidents: {open_incidents} currently open, {opened_24h} opened (24h), {resolved_24h} resolved (24h)\n'
            f'Uptime Checks: {total_checks} active checks, 24h uptime {uptime_pct}\n'
        )
        try:
            send_mail(
                subject=f'[SysRoar] Daily Digest - {company.name} ({today.isoformat()})',
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipients,
                fail_silently=False,
            )
            company.last_digest_sent_on = today
            company.save(update_fields=['last_digest_sent_on'])
            sent += 1
        except Exception as exc:
            logger.error(f'Failed sending daily digest for company {company.id}: {exc}')

    return {'sent': sent}
