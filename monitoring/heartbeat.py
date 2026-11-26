import json
import logging
from datetime import datetime, timezone as dt_timezone
from django.utils import timezone
from django_redis import get_redis_connection
from monitoring.models import AlertRule, Server, SystemEvent
from telemetry.notifications.dispatcher import NotificationDispatcher

logger = logging.getLogger(__name__)

HEARTBEAT_LAST_SEEN_KEY = 'sysroar:heartbeat:last_seen'
HEARTBEAT_DIRTY_KEY = 'sysroar:heartbeat:dirty'
HEARTBEAT_OFFLINE_KEY = 'sysroar:heartbeat:offline'


def _decode(value):
    if isinstance(value, bytes):
        return value.decode('utf-8')
    return value


def compute_offline_threshold_seconds(telemetry_cadence: int) -> int:
    cadence = int(telemetry_cadence or 30)
    return max(3 * cadence, 90)


def record_heartbeat(server_id, company_id, seen_at=None, ip_address=None, os_info=None, con=None):
    con = con or get_redis_connection('default')
    seen_at = seen_at or timezone.now()
    sid = str(server_id)
    existing_raw = con.hget(HEARTBEAT_LAST_SEEN_KEY, sid)
    existing = {}
    if existing_raw:
        try:
            existing = json.loads(_decode(existing_raw))
        except (ValueError, TypeError):
            existing = {}

    entry = {
        'ts': seen_at.timestamp(),
        'company_id': str(company_id),
        'ip_address': ip_address if ip_address is not None else existing.get('ip_address'),
        'os_info': os_info if os_info is not None else existing.get('os_info'),
    }
    pipe = con.pipeline(transaction=False)
    pipe.hset(HEARTBEAT_LAST_SEEN_KEY, sid, json.dumps(entry))
    pipe.sadd(HEARTBEAT_DIRTY_KEY, sid)
    pipe.execute()


def record_heartbeats_batch(items, con=None):
    if not items:
        return
    con = con or get_redis_connection('default')
    sids = [str(item['server_id']) for item in items]
    existing_values = con.hmget(HEARTBEAT_LAST_SEEN_KEY, sids)
    pipe = con.pipeline(transaction=False)
    for item, raw in zip(items, existing_values, strict=True):
        existing = {}
        if raw:
            try:
                existing = json.loads(_decode(raw))
            except (ValueError, TypeError):
                existing = {}
        seen_at = item.get('seen_at') or timezone.now()
        entry = {
            'ts': seen_at.timestamp(),
            'company_id': str(item['company_id']),
            'ip_address': item['ip_address'] if item.get('ip_address') is not None else existing.get('ip_address'),
            'os_info': item['os_info'] if item.get('os_info') is not None else existing.get('os_info'),
        }
        sid = str(item['server_id'])
        pipe.hset(HEARTBEAT_LAST_SEEN_KEY, sid, json.dumps(entry))
        pipe.sadd(HEARTBEAT_DIRTY_KEY, sid)
    pipe.execute()


def get_live_heartbeats(server_ids, con=None) -> dict:
    sids = [str(sid) for sid in server_ids]
    if not sids:
        return {}
    con = con or get_redis_connection('default')
    raw_values = con.hmget(HEARTBEAT_LAST_SEEN_KEY, sids)
    result = {}
    for sid, raw in zip(sids, raw_values, strict=True):
        if not raw:
            continue
        try:
            data = json.loads(_decode(raw))
            ts = data.get('ts')
            if ts is not None:
                result[sid] = {
                    'last_ping': datetime.fromtimestamp(float(ts), tz=dt_timezone.utc),
                    'ip_address': data.get('ip_address'),
                    'os_info': data.get('os_info'),
                }
        except (ValueError, TypeError):
            continue
    return result


def flush_heartbeats_to_db(batch_size: int = 500, con=None) -> int:
    con = con or get_redis_connection('default')
    dirty_raw = con.spop(HEARTBEAT_DIRTY_KEY, batch_size)
    if not dirty_raw:
        return 0
    if isinstance(dirty_raw, (bytes, str)):
        dirty_ids = [_decode(dirty_raw)]
    else:
        dirty_ids = [_decode(sid) for sid in dirty_raw]

    raw_values = con.hmget(HEARTBEAT_LAST_SEEN_KEY, dirty_ids)
    updated = 0
    for sid, raw in zip(dirty_ids, raw_values, strict=True):
        if not raw:
            continue
        try:
            data = json.loads(_decode(raw))
            ts = data.get('ts')
            company_id = data.get('company_id')
            if ts is None or not company_id:
                continue
            update_fields = {'last_ping': datetime.fromtimestamp(float(ts), tz=dt_timezone.utc)}
            if data.get('ip_address'):
                update_fields['ip_address'] = data['ip_address']
            if data.get('os_info'):
                update_fields['os_info'] = data['os_info']
            updated += Server.unscoped.filter(id=sid, company_id=company_id).update(**update_fields)
        except Exception as exc:
            logger.warning(f'Failed to flush heartbeat for server {sid}: {exc}')
    return updated


def check_server_heartbeats(now=None, con=None) -> dict:
    con = con or get_redis_connection('default')
    now = now or timezone.now()
    flushed = flush_heartbeats_to_db(con=con)

    offline_members = {_decode(m) for m in con.smembers(HEARTBEAT_OFFLINE_KEY)}
    active_servers = list(
        Server.unscoped.filter(is_active=True, last_ping__isnull=False).only(
            'id', 'company_id', 'name', 'ip_address', 'telemetry_cadence', 'last_ping'
        )
    )

    newly_offline = 0
    recovered = 0
    for server in active_servers:
        sid = str(server.id)
        threshold_seconds = compute_offline_threshold_seconds(server.telemetry_cadence)
        elapsed = (now - server.last_ping).total_seconds()
        is_offline = elapsed > threshold_seconds

        if is_offline and sid not in offline_members:
            con.sadd(HEARTBEAT_OFFLINE_KEY, sid)
            newly_offline += 1
            SystemEvent.objects.create(
                event_type='NO_DATA',
                severity='WARNING',
                context={
                    'server_id': sid,
                    'company_id': str(server.company_id),
                    'server_name': server.name,
                    'last_ping': server.last_ping.isoformat(),
                    'stale_seconds': threshold_seconds,
                },
            )
            no_data_rules = AlertRule.unscoped.filter(
                server=server,
                company_id=server.company_id,
                metric_type='no_data',
                is_active=True,
            )
            for rule in no_data_rules:
                NotificationDispatcher.dispatch_alert(
                    server,
                    rule,
                    {'value': round(elapsed, 1), 'timestamp': now.isoformat()},
                )
        elif not is_offline and sid in offline_members:
            con.srem(HEARTBEAT_OFFLINE_KEY, sid)
            recovered += 1
            SystemEvent.objects.create(
                event_type='NO_DATA_RESOLVED',
                severity='WARNING',
                context={
                    'server_id': sid,
                    'company_id': str(server.company_id),
                    'server_name': server.name,
                    'last_ping': server.last_ping.isoformat(),
                },
            )
            no_data_rules = AlertRule.unscoped.filter(
                server=server,
                company_id=server.company_id,
                metric_type='no_data',
                is_active=True,
            )
            for rule in no_data_rules:
                NotificationDispatcher.dispatch_resolution(
                    server,
                    rule,
                    {'timestamp': now.isoformat()},
                )

    return {'flushed': flushed, 'newly_offline': newly_offline, 'recovered': recovered}
