import hashlib
import hmac
import json
import logging
import time
from typing import TYPE_CHECKING, Dict
import requests
from .base import NotificationStrategy
from .ssrf import SSRFBlockedError, send_safe_webhook_post

if TYPE_CHECKING:
    from monitoring.models import AlertRule, Server

logger = logging.getLogger(__name__)


def compute_webhook_signature(secret: str, timestamp: str, raw_body: bytes) -> str:
    signed_payload = f'{timestamp}.'.encode('utf-8') + raw_body
    digest = hmac.new(secret.encode('utf-8'), signed_payload, hashlib.sha256).hexdigest()
    return f'sha256={digest}'


def verify_webhook_signature(
    secret: str,
    timestamp: str,
    raw_body: bytes,
    signature_header: str,
    max_age_seconds: int = 300,
    now: int | None = None,
) -> bool:
    if not secret or not timestamp or not signature_header:
        return False
    try:
        ts_int = int(timestamp)
    except ValueError:
        return False
    current = int(time.time()) if now is None else int(now)
    if abs(current - ts_int) > max_age_seconds:
        return False
    expected = compute_webhook_signature(secret, timestamp, raw_body)
    return hmac.compare_digest(expected, signature_header)


class WebhookStrategy(NotificationStrategy):
    def send_alert(self, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        return self._dispatch(server, rule, context, 'alert_triggered')

    def send_resolution(self, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        return self._dispatch(server, rule, context, 'alert_resolved')

    def send_test(self, rule: 'AlertRule') -> tuple[bool, str]:
        payload = {
            'event': 'webhook_test',
            'server_id': str(rule.server_id),
            'hostname': rule.server.name,
            'rule': {
                'id': str(rule.id),
                'metric': rule.metric_type,
                'threshold': float(rule.threshold_value),
            },
            'timestamp': str(int(time.time())),
        }
        raw_body = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
        headers = self._build_headers(rule, 'webhook_test', raw_body)
        response = send_safe_webhook_post(rule.notification_target, raw_body, headers)
        if 200 <= response.status_code < 300:
            return True, f'HTTP {response.status_code}'
        return False, f'HTTP {response.status_code}'

    def _build_headers(self, rule: 'AlertRule', event_type: str, raw_body: bytes) -> dict[str, str]:
        timestamp = str(int(time.time()))
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'SysRoar-Webhook/1.0',
            'X-SysRoar-Event': event_type,
            'X-SysRoar-Timestamp': timestamp,
        }
        secret = getattr(rule, 'webhook_secret', '') or ''
        if secret:
            headers['X-SysRoar-Signature-256'] = compute_webhook_signature(secret, timestamp, raw_body)
        return headers

    def _dispatch(self, server: 'Server', rule: 'AlertRule', context: Dict, event_type: str) -> bool:
        from monitoring.tasks import record_system_event

        payload = {
            'event': event_type,
            'server_id': str(server.id),
            'hostname': server.name,
            'ip_address': server.ip_address,
            'rule': {
                'id': str(rule.id),
                'metric': rule.metric_type,
                'threshold': float(rule.threshold_value),
            },
            'metric_value': float(context.get('value', 0)),
            'timestamp': context.get('timestamp'),
        }
        raw_body = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
        headers = self._build_headers(rule, event_type, raw_body)

        try:
            response = send_safe_webhook_post(
                rule.notification_target,
                raw_body,
                headers,
                timeout=(3.0, 5.0),
            )
            if 300 <= response.status_code < 400:
                raise SSRFBlockedError('Webhook redirects are not permitted.')
            response.raise_for_status()
            logger.info(f'Webhook {event_type} sent to {rule.notification_target}')
            return True
        except SSRFBlockedError as exc:
            logger.warning(f'WEBHOOK_SSRF_BLOCKED | Rule {rule.id}: {exc}')
            record_system_event.delay(
                event_type='WEBHOOK_DISPATCH_FAILURE',
                severity='WARNING',
                context={
                    'target': rule.notification_target,
                    'rule_id': str(rule.id),
                    'error': str(exc),
                },
            )
            return False
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            logger.error(
                f'WEBHOOK_DISPATCH_FAILURE | HTTP {status_code} from {rule.notification_target}: {exc}'
            )
            record_system_event.delay(
                event_type='WEBHOOK_DISPATCH_FAILURE',
                severity='ERROR',
                context={
                    'target': rule.notification_target,
                    'rule_id': str(rule.id),
                    'error': str(exc),
                    'status_code': status_code,
                },
            )
            return False
        except requests.RequestException as exc:
            logger.error(f'WEBHOOK_DISPATCH_FAILURE | Request error to {rule.notification_target}: {exc}')
            record_system_event.delay(
                event_type='WEBHOOK_DISPATCH_FAILURE',
                severity='ERROR',
                context={
                    'target': rule.notification_target,
                    'rule_id': str(rule.id),
                    'error': str(exc),
                },
            )
            return False
