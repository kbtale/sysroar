import logging
import re
import socket
import ssl
import time
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlsplit
import requests
from django.utils import timezone
from telemetry.notifications.dispatcher import NotificationDispatcher
from telemetry.notifications.ssrf import SSRFBlockedError, validate_ip_address, validate_webhook_url
from .models import AlertRule, Incident, Server, UptimeCheck, UptimeCheckResult

logger = logging.getLogger(__name__)

_SAFE_HOST_RE = re.compile(r'^[a-zA-Z0-9._:-]{1,253}$')


def _resolve_target_host(host: str, port: int, allow_private: bool) -> str:
    cleaned = host.strip().rstrip('.').lower()
    if not cleaned or not _SAFE_HOST_RE.match(cleaned):
        raise SSRFBlockedError('Invalid target hostname or IP.')
    try:
        infos = socket.getaddrinfo(cleaned, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f'DNS resolution failed for {cleaned}') from exc
    if not infos:
        raise ValueError(f'No addresses resolved for {cleaned}')
    first_ip = infos[0][4][0].split('%', 1)[0]
    if not allow_private:
        for entry in infos:
            validate_ip_address(entry[4][0].split('%', 1)[0])
    return first_ip


def _inspect_ssl_expiry_days(hostname: str, port: int, timeout_s: float) -> int:
    ctx = ssl.create_default_context()
    with socket.create_connection((hostname, port), timeout=timeout_s) as sock:
        with ctx.wrap_socket(sock, server_hostname=hostname) as tls_sock:
            cert = tls_sock.getpeercert()
    not_after = cert.get('notAfter') if isinstance(cert, dict) else None
    if not not_after:
        raise ValueError('Certificate missing notAfter field.')
    expiry = datetime.strptime(not_after, '%b %d %H:%M:%S %Y %Z').replace(tzinfo=dt_timezone.utc)
    delta = expiry - datetime.now(dt_timezone.utc)
    return int(delta.total_seconds() // 86400)


def _run_http_check(check_obj: UptimeCheck) -> dict:
    url = check_obj.target.strip()
    if not check_obj.allow_private_targets:
        validate_webhook_url(url)
    parsed = urlsplit(url)
    timeout_s = float(max(1, min(60, check_obj.timeout_seconds or 10)))
    started = time.monotonic()
    resp = requests.get(
        url,
        timeout=(min(timeout_s, 5.0), timeout_s),
        allow_redirects=False,
        headers={'User-Agent': 'SysRoar-Uptime/1.0'},
    )
    latency_ms = round((time.monotonic() - started) * 1000.0, 2)
    ssl_days = None
    if parsed.scheme.lower() == 'https' and parsed.hostname:
        try:
            ssl_days = _inspect_ssl_expiry_days(parsed.hostname, parsed.port or 443, min(timeout_s, 5.0))
        except Exception:
            ssl_days = None

    expected_status = check_obj.expected_status or 200
    if resp.status_code != expected_status:
        return {
            'status': 'down',
            'latency_ms': latency_ms,
            'status_code': resp.status_code,
            'ssl_expiry_days': ssl_days,
            'error_message': f'Expected HTTP {expected_status}, got {resp.status_code}',
        }

    keyword = (check_obj.expected_keyword or '').strip()
    if keyword and keyword not in resp.text:
        return {
            'status': 'down',
            'latency_ms': latency_ms,
            'status_code': resp.status_code,
            'ssl_expiry_days': ssl_days,
            'error_message': f'Keyword "{keyword}" not found in response',
        }

    if ssl_days is not None and ssl_days <= 0:
        return {
            'status': 'down',
            'latency_ms': latency_ms,
            'status_code': resp.status_code,
            'ssl_expiry_days': ssl_days,
            'error_message': 'SSL certificate has expired',
        }

    if ssl_days is not None and ssl_days <= (check_obj.ssl_expiry_warning_days or 14):
        return {
            'status': 'degraded',
            'latency_ms': latency_ms,
            'status_code': resp.status_code,
            'ssl_expiry_days': ssl_days,
            'error_message': f'SSL certificate expires in {ssl_days} days',
        }

    return {
        'status': 'up',
        'latency_ms': latency_ms,
        'status_code': resp.status_code,
        'ssl_expiry_days': ssl_days,
        'error_message': '',
    }


def _run_tcp_check(check_obj: UptimeCheck) -> dict:
    port = check_obj.port or 443
    ip_addr = _resolve_target_host(check_obj.target, port, check_obj.allow_private_targets)
    timeout_s = float(max(1, min(60, check_obj.timeout_seconds or 10)))
    started = time.monotonic()
    with socket.create_connection((ip_addr, port), timeout=timeout_s):
        pass
    return {
        'status': 'up',
        'latency_ms': round((time.monotonic() - started) * 1000.0, 2),
        'status_code': None,
        'ssl_expiry_days': None,
        'error_message': '',
    }


def _run_ssl_check(check_obj: UptimeCheck) -> dict:
    host = check_obj.target.strip()
    if '://' in host:
        parsed = urlsplit(host)
        host = parsed.hostname or host
    port = check_obj.port or 443
    _resolve_target_host(host, port, check_obj.allow_private_targets)
    timeout_s = float(max(1, min(60, check_obj.timeout_seconds or 10)))
    started = time.monotonic()
    ssl_days = _inspect_ssl_expiry_days(host, port, timeout_s)
    latency_ms = round((time.monotonic() - started) * 1000.0, 2)
    if ssl_days <= 0:
        return {
            'status': 'down',
            'latency_ms': latency_ms,
            'status_code': None,
            'ssl_expiry_days': ssl_days,
            'error_message': 'SSL certificate has expired',
        }
    if ssl_days <= (check_obj.ssl_expiry_warning_days or 14):
        return {
            'status': 'degraded',
            'latency_ms': latency_ms,
            'status_code': None,
            'ssl_expiry_days': ssl_days,
            'error_message': f'SSL certificate expires in {ssl_days} days',
        }
    return {
        'status': 'up',
        'latency_ms': latency_ms,
        'status_code': None,
        'ssl_expiry_days': ssl_days,
        'error_message': '',
    }


def _run_dns_check(check_obj: UptimeCheck) -> dict:
    host = check_obj.target.strip()
    if not _SAFE_HOST_RE.match(host):
        raise ValueError('Invalid DNS hostname.')
    started = time.monotonic()
    infos = socket.getaddrinfo(host, None)
    latency_ms = round((time.monotonic() - started) * 1000.0, 2)
    if not infos:
        raise ValueError('No DNS records found.')
    return {
        'status': 'up',
        'latency_ms': latency_ms,
        'status_code': None,
        'ssl_expiry_days': None,
        'error_message': '',
    }


def _run_ping_check(check_obj: UptimeCheck) -> dict:
    host = check_obj.target.strip()
    probe_port = check_obj.port or 443
    ip_addr = _resolve_target_host(host, probe_port, check_obj.allow_private_targets)
    timeout_s = float(max(1, min(30, check_obj.timeout_seconds or 5)))
    started = time.monotonic()
    try:
        with socket.create_connection((ip_addr, probe_port), timeout=timeout_s):
            pass
    except OSError as exc:
        return {
            'status': 'down',
            'latency_ms': round((time.monotonic() - started) * 1000.0, 2),
            'status_code': None,
            'ssl_expiry_days': None,
            'error_message': str(exc)[:255],
        }
    return {
        'status': 'up',
        'latency_ms': round((time.monotonic() - started) * 1000.0, 2),
        'status_code': None,
        'ssl_expiry_days': None,
        'error_message': '',
    }


def _notify_uptime_event(check_obj: UptimeCheck, is_resolution: bool, detail: str):
    if not check_obj.channel_id or not check_obj.channel or not check_obj.channel.is_active:
        return
    pseudo_server = Server(
        id=check_obj.id,
        company_id=check_obj.company_id,
        name=check_obj.name,
        ip_address=None,
    )
    pseudo_rule = AlertRule(
        id=check_obj.id,
        company_id=check_obj.company_id,
        metric_type='no_data',
        threshold_value=0.0,
        severity='critical' if check_obj.last_status == 'down' else 'warning',
        notification_type=check_obj.channel.channel_type,
        notification_target=check_obj.channel.target,
        webhook_secret=check_obj.channel.webhook_secret,
    )
    ctx = {
        'value': detail or check_obj.last_status,
        'severity': 'critical' if check_obj.last_status == 'down' else 'warning',
        'timestamp': timezone.now().isoformat(),
    }
    if is_resolution:
        NotificationDispatcher.dispatch_resolution(pseudo_server, pseudo_rule, ctx)
    else:
        NotificationDispatcher.dispatch_alert(pseudo_server, pseudo_rule, ctx)


def execute_uptime_check(check_obj: UptimeCheck, now=None) -> UptimeCheckResult:
    now = now or timezone.now()
    runners = {
        'http': _run_http_check,
        'tcp': _run_tcp_check,
        'ssl': _run_ssl_check,
        'dns': _run_dns_check,
        'ping': _run_ping_check,
    }
    runner = runners.get(check_obj.check_type, _run_http_check)
    try:
        outcome = runner(check_obj)
    except Exception as exc:
        outcome = {
            'status': 'down',
            'latency_ms': None,
            'status_code': None,
            'ssl_expiry_days': None,
            'error_message': str(exc)[:500],
        }

    result = UptimeCheckResult.unscoped.create(
        company_id=check_obj.company_id,
        check_obj=check_obj,
        status=outcome['status'],
        latency_ms=outcome.get('latency_ms'),
        status_code=outcome.get('status_code'),
        ssl_expiry_days=outcome.get('ssl_expiry_days'),
        error_message=outcome.get('error_message', '')[:512],
        checked_at=now,
    )

    prev_status = check_obj.last_status
    check_obj.last_status = outcome['status']
    check_obj.last_latency_ms = outcome.get('latency_ms')
    check_obj.last_ssl_expiry_days = outcome.get('ssl_expiry_days')
    check_obj.last_error = outcome.get('error_message', '')[:512]
    check_obj.last_checked_at = now
    if outcome['status'] == 'up':
        check_obj.consecutive_failures = 0
    else:
        check_obj.consecutive_failures = (check_obj.consecutive_failures or 0) + 1
    check_obj.save(
        update_fields=[
            'last_status',
            'last_latency_ms',
            'last_ssl_expiry_days',
            'last_error',
            'last_checked_at',
            'consecutive_failures',
        ]
    )

    if outcome['status'] in ('down', 'degraded'):
        open_inc = Incident.unscoped.filter(
            company_id=check_obj.company_id,
            uptime_check=check_obj,
            status__in=('open', 'acknowledged'),
        ).first()
        if open_inc is None:
            Incident.unscoped.create(
                company_id=check_obj.company_id,
                uptime_check=check_obj,
                title=f'Uptime {outcome["status"].upper()}: {check_obj.name}',
                severity='critical' if outcome['status'] == 'down' else 'warning',
                status='open',
                opened_at=now,
            )
            _notify_uptime_event(check_obj, is_resolution=False, detail=outcome.get('error_message', ''))
    elif prev_status in ('down', 'degraded'):
        resolved = Incident.unscoped.filter(
            company_id=check_obj.company_id,
            uptime_check=check_obj,
            status__in=('open', 'acknowledged'),
        ).update(status='resolved', resolved_at=now)
        if resolved:
            _notify_uptime_event(check_obj, is_resolution=True, detail='Recovered')

    return result
