import json
import logging
from typing import TYPE_CHECKING, Dict
from urllib.parse import quote
import requests
from .base import NotificationStrategy
from .ssrf import SSRFBlockedError, send_safe_webhook_post

if TYPE_CHECKING:
    from monitoring.models import AlertRule, Server

logger = logging.getLogger(__name__)

URL_BASED_CHANNELS = frozenset({'WEBHOOK', 'SLACK', 'DISCORD', 'TEAMS', 'PAGERDUTY', 'OPSGENIE', 'NTFY', 'GOTIFY'})
SECRET_REQUIRED_CHANNELS = frozenset({'TELEGRAM', 'PAGERDUTY', 'OPSGENIE', 'GOTIFY'})
DEFAULT_PROVIDER_URLS = {
    'PAGERDUTY': 'https://events.pagerduty.com/v2/enqueue',
    'OPSGENIE': 'https://api.opsgenie.com/v2/alerts',
}


def _severity_label(rule, context: Dict) -> str:
    return str(context.get('severity') or getattr(rule, 'severity', 'warning')).upper()


def _summary_lines(server: 'Server', rule: 'AlertRule', context: Dict, is_resolution: bool) -> tuple[str, str]:
    metric = str(getattr(rule, 'metric_type', 'metric')).upper()
    value = context.get('value', '--')
    threshold = getattr(rule, 'threshold_value', '--')
    severity = _severity_label(rule, context)
    host_label = f'{server.name} ({server.ip_address or "n/a"})'
    if is_resolution:
        title = f'[SysRoar] RESOLVED: {metric} on {server.name}'
        body = f'Host {host_label} recovered. {metric} is now {value} (threshold {threshold}).'
    else:
        title = f'[SysRoar] {severity}: {metric} on {server.name}'
        body = f'Host {host_label} breached {metric} threshold {threshold} with value {value}.'
    return title, body


class _HttpProviderStrategy(NotificationStrategy):
    provider_name = 'PROVIDER'

    def build_request(
        self,
        target: str,
        secret: str,
        title: str,
        body: str,
        severity: str,
        dedup_key: str,
        is_resolution: bool,
    ) -> tuple[str, bytes, dict[str, str]]:
        raise NotImplementedError

    def _post(self, url: str, raw_body: bytes, headers: dict[str, str]) -> requests.Response:
        resp = send_safe_webhook_post(url, raw_body, headers, timeout=(3.0, 6.0))
        if 300 <= resp.status_code < 400:
            raise SSRFBlockedError('Provider redirects are not permitted.')
        return resp

    def send_raw_test(self, target: str, secret: str, channel_name: str) -> tuple[bool, str]:
        title = f'[SysRoar] Test Notification ({channel_name})'
        body = f'Test alert dispatched from SysRoar channel "{channel_name}".'
        url, raw_body, headers = self.build_request(
            target=target,
            secret=secret,
            title=title,
            body=body,
            severity='WARNING',
            dedup_key=f'sysroar-test-{channel_name}',
            is_resolution=False,
        )
        resp = self._post(url, raw_body, headers)
        if 200 <= resp.status_code < 300:
            return True, f'HTTP {resp.status_code}'
        return False, f'HTTP {resp.status_code}'

    def _dispatch(self, server: 'Server', rule: 'AlertRule', context: Dict, is_resolution: bool) -> bool:
        from monitoring.tasks import record_system_event

        title, body = _summary_lines(server, rule, context, is_resolution)
        severity = _severity_label(rule, context)
        dedup_key = f'sysroar-{rule.id}-{server.id}'
        target = getattr(rule, 'notification_target', '') or ''
        secret = getattr(rule, 'webhook_secret', '') or ''

        try:
            url, raw_body, headers = self.build_request(
                target=target,
                secret=secret,
                title=title,
                body=body,
                severity=severity,
                dedup_key=dedup_key,
                is_resolution=is_resolution,
            )
            resp = self._post(url, raw_body, headers)
            resp.raise_for_status()
            return True
        except (SSRFBlockedError, requests.RequestException, ValueError) as exc:
            logger.error(f'{self.provider_name}_DISPATCH_FAILURE | Rule {rule.id}: {exc}')
            record_system_event.delay(
                event_type='NOTIFICATION_DISPATCH_FAILURE',
                severity='ERROR',
                context={
                    'provider': self.provider_name,
                    'rule_id': str(rule.id),
                    'error': str(exc),
                },
            )
            return False

    def send_alert(self, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        return self._dispatch(server, rule, context, is_resolution=False)

    def send_resolution(self, server: 'Server', rule: 'AlertRule', context: Dict) -> bool:
        return self._dispatch(server, rule, context, is_resolution=True)


class SlackStrategy(_HttpProviderStrategy):
    provider_name = 'SLACK'

    def build_request(self, target, secret, title, body, severity, dedup_key, is_resolution):
        color = '#10b981' if is_resolution else ('#ef4444' if severity == 'CRITICAL' else '#f59e0b')
        payload = {
            'text': title,
            'attachments': [{'color': color, 'title': title, 'text': body}],
        }
        return (
            target,
            json.dumps(payload, separators=(',', ':')).encode('utf-8'),
            {'Content-Type': 'application/json', 'User-Agent': 'SysRoar-Notify/1.0'},
        )


class DiscordStrategy(_HttpProviderStrategy):
    provider_name = 'DISCORD'

    def build_request(self, target, secret, title, body, severity, dedup_key, is_resolution):
        color = 0x10B981 if is_resolution else (0xEF4444 if severity == 'CRITICAL' else 0xF59E0B)
        payload = {
            'username': 'SysRoar',
            'embeds': [{'title': title, 'description': body, 'color': color}],
        }
        return (
            target,
            json.dumps(payload, separators=(',', ':')).encode('utf-8'),
            {'Content-Type': 'application/json', 'User-Agent': 'SysRoar-Notify/1.0'},
        )


class TeamsStrategy(_HttpProviderStrategy):
    provider_name = 'TEAMS'

    def build_request(self, target, secret, title, body, severity, dedup_key, is_resolution):
        color = '10B981' if is_resolution else ('EF4444' if severity == 'CRITICAL' else 'F59E0B')
        payload = {
            '@type': 'MessageCard',
            '@context': 'https://schema.org/extensions',
            'themeColor': color,
            'summary': title,
            'sections': [{'activityTitle': title, 'text': body}],
        }
        return (
            target,
            json.dumps(payload, separators=(',', ':')).encode('utf-8'),
            {'Content-Type': 'application/json', 'User-Agent': 'SysRoar-Notify/1.0'},
        )


class TelegramStrategy(_HttpProviderStrategy):
    provider_name = 'TELEGRAM'

    def build_request(self, target, secret, title, body, severity, dedup_key, is_resolution):
        token = secret.strip()
        if not token:
            raise ValueError('Telegram bot token is required.')
        url = f'https://api.telegram.org/bot{quote(token, safe=":")}/sendMessage'
        payload = {'chat_id': target.strip(), 'text': f'{title}\n{body}'}
        return (
            url,
            json.dumps(payload, separators=(',', ':')).encode('utf-8'),
            {'Content-Type': 'application/json', 'User-Agent': 'SysRoar-Notify/1.0'},
        )


class PagerDutyStrategy(_HttpProviderStrategy):
    provider_name = 'PAGERDUTY'

    def build_request(self, target, secret, title, body, severity, dedup_key, is_resolution):
        routing_key = secret.strip()
        if not routing_key:
            raise ValueError('PagerDuty routing key is required.')
        url = target.strip() or DEFAULT_PROVIDER_URLS['PAGERDUTY']
        pd_sev = 'critical' if severity == 'CRITICAL' else 'warning'
        payload = {
            'routing_key': routing_key,
            'event_action': 'resolve' if is_resolution else 'trigger',
            'dedup_key': dedup_key,
            'payload': {
                'summary': title,
                'severity': pd_sev,
                'source': 'sysroar',
                'custom_details': {'message': body},
            },
        }
        return (
            url,
            json.dumps(payload, separators=(',', ':')).encode('utf-8'),
            {'Content-Type': 'application/json', 'User-Agent': 'SysRoar-Notify/1.0'},
        )


class OpsgenieStrategy(_HttpProviderStrategy):
    provider_name = 'OPSGENIE'

    def build_request(self, target, secret, title, body, severity, dedup_key, is_resolution):
        api_key = secret.strip()
        if not api_key:
            raise ValueError('Opsgenie API key is required.')
        base_url = (target.strip() or DEFAULT_PROVIDER_URLS['OPSGENIE']).rstrip('/')
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'GenieKey {api_key}',
            'User-Agent': 'SysRoar-Notify/1.0',
        }
        if is_resolution:
            url = f'{base_url}/{quote(dedup_key, safe="")}/close?identifierType=alias'
            payload = {'note': body}
        else:
            url = base_url
            payload = {
                'message': title[:130],
                'alias': dedup_key,
                'description': body,
                'priority': 'P1' if severity == 'CRITICAL' else 'P3',
            }
        return url, json.dumps(payload, separators=(',', ':')).encode('utf-8'), headers


class NtfyStrategy(_HttpProviderStrategy):
    provider_name = 'NTFY'

    def build_request(self, target, secret, title, body, severity, dedup_key, is_resolution):
        priority = 'default' if is_resolution else ('urgent' if severity == 'CRITICAL' else 'high')
        tags = 'white_check_mark' if is_resolution else 'rotating_light'
        headers = {
            'Content-Type': 'text/plain; charset=utf-8',
            'Title': title,
            'Priority': priority,
            'Tags': tags,
            'User-Agent': 'SysRoar-Notify/1.0',
        }
        if secret.strip():
            headers['Authorization'] = f'Bearer {secret.strip()}'
        return target.strip(), body.encode('utf-8'), headers


class GotifyStrategy(_HttpProviderStrategy):
    provider_name = 'GOTIFY'

    def build_request(self, target, secret, title, body, severity, dedup_key, is_resolution):
        app_token = secret.strip()
        if not app_token:
            raise ValueError('Gotify application token is required.')
        base = target.strip().rstrip('/')
        url = base if base.endswith('/message') else f'{base}/message'
        payload = {
            'title': title,
            'message': body,
            'priority': 2 if is_resolution else (8 if severity == 'CRITICAL' else 5),
        }
        headers = {
            'Content-Type': 'application/json',
            'X-Gotify-Key': app_token,
            'User-Agent': 'SysRoar-Notify/1.0',
        }
        return url, json.dumps(payload, separators=(',', ':')).encode('utf-8'), headers
