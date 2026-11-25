import datetime
import json
import logging
import uuid
from django.conf import settings
from django_redis import get_redis_connection
from redis.exceptions import ResponseError

logger = logging.getLogger(__name__)

redis_client = get_redis_connection('default')

TELEMETRY_STREAM_KEY = getattr(settings, 'TELEMETRY_STREAM_KEY', 'sysroar:telemetry:stream')
TELEMETRY_DLQ_STREAM_KEY = getattr(settings, 'TELEMETRY_DLQ_STREAM_KEY', 'sysroar:telemetry:dlq')
TELEMETRY_CONSUMER_GROUP = getattr(settings, 'TELEMETRY_CONSUMER_GROUP', 'sysroar-ingest')
TELEMETRY_STREAM_MAXLEN = getattr(settings, 'TELEMETRY_STREAM_MAXLEN', 100000)
TELEMETRY_DLQ_MAXLEN = getattr(settings, 'TELEMETRY_DLQ_MAXLEN', 10000)
TELEMETRY_MAX_DELIVERIES = getattr(settings, 'TELEMETRY_MAX_DELIVERIES', 5)


class UUIDEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        return super().default(obj)


def _decode(value):
    if isinstance(value, bytes):
        return value.decode('utf-8')
    return value


def _normalize_entries(raw_entries):
    normalized = []
    for entry_id, raw_fields in raw_entries:
        fields = {_decode(k): _decode(v) for k, v in raw_fields.items()}
        normalized.append((_decode(entry_id), fields))
    return normalized


def ensure_consumer_group(con=None, stream_key=None, group_name=None):
    con = con or get_redis_connection('default')
    stream_key = stream_key or TELEMETRY_STREAM_KEY
    group_name = group_name or TELEMETRY_CONSUMER_GROUP
    try:
        con.xgroup_create(name=stream_key, groupname=group_name, id='0', mkstream=True)
    except ResponseError as exc:
        if 'BUSYGROUP' not in str(exc):
            raise


def push_to_stream(telemetry_data: dict, con=None, stream_key=None) -> str:
    con = con or get_redis_connection('default')
    stream_key = stream_key or TELEMETRY_STREAM_KEY
    payload = json.dumps(telemetry_data, cls=UUIDEncoder)
    entry_id = con.xadd(
        stream_key,
        {'payload': payload},
        maxlen=TELEMETRY_STREAM_MAXLEN,
        approximate=True,
    )
    return _decode(entry_id)


def push_batch_to_stream(items: list[dict], con=None, stream_key=None) -> list[str]:
    if not items:
        return []
    con = con or get_redis_connection('default')
    stream_key = stream_key or TELEMETRY_STREAM_KEY
    pipe = con.pipeline(transaction=False)
    for item in items:
        payload = json.dumps(item, cls=UUIDEncoder)
        pipe.xadd(
            stream_key,
            {'payload': payload},
            maxlen=TELEMETRY_STREAM_MAXLEN,
            approximate=True,
        )
    results = pipe.execute()
    return [_decode(entry_id) for entry_id in results]


def push_to_dlq(entry_id: str, raw_payload: str, error: str, deliveries: int, con=None, dlq_key=None) -> str:
    con = con or get_redis_connection('default')
    dlq_key = dlq_key or TELEMETRY_DLQ_STREAM_KEY
    dlq_id = con.xadd(
        dlq_key,
        {
            'original_id': str(entry_id),
            'payload': raw_payload or '',
            'error': str(error)[:1000],
            'deliveries': str(deliveries),
        },
        maxlen=TELEMETRY_DLQ_MAXLEN,
        approximate=True,
    )
    return _decode(dlq_id)


def read_stream_batch(
    consumer_name: str,
    count: int = 500,
    block_ms: int = 1000,
    con=None,
    stream_key=None,
    group_name=None,
) -> list[tuple[str, dict]]:
    con = con or get_redis_connection('default')
    stream_key = stream_key or TELEMETRY_STREAM_KEY
    group_name = group_name or TELEMETRY_CONSUMER_GROUP
    ensure_consumer_group(con=con, stream_key=stream_key, group_name=group_name)
    response = con.xreadgroup(
        groupname=group_name,
        consumername=consumer_name,
        streams={stream_key: '>'},
        count=count,
        block=block_ms,
    )
    if not response:
        return []
    entries = []
    for _, raw_entries in response:
        entries.extend(_normalize_entries(raw_entries))
    return entries


def claim_stale_entries(
    consumer_name: str,
    min_idle_ms: int = 30000,
    count: int = 500,
    con=None,
    stream_key=None,
    group_name=None,
) -> list[tuple[str, dict]]:
    con = con or get_redis_connection('default')
    stream_key = stream_key or TELEMETRY_STREAM_KEY
    group_name = group_name or TELEMETRY_CONSUMER_GROUP
    ensure_consumer_group(con=con, stream_key=stream_key, group_name=group_name)
    result = con.xautoclaim(
        name=stream_key,
        groupname=group_name,
        consumername=consumer_name,
        min_idle_time=min_idle_ms,
        start_id='0-0',
        count=count,
    )
    raw_entries = result[1] if len(result) > 1 else []
    return _normalize_entries(raw_entries)


def get_delivery_counts(entry_ids: list[str], con=None, stream_key=None, group_name=None) -> dict[str, int]:
    if not entry_ids:
        return {}
    con = con or get_redis_connection('default')
    stream_key = stream_key or TELEMETRY_STREAM_KEY
    group_name = group_name or TELEMETRY_CONSUMER_GROUP
    counts = {}
    pending = con.xpending_range(
        name=stream_key,
        groupname=group_name,
        min=min(entry_ids),
        max=max(entry_ids),
        count=max(len(entry_ids) * 2, 100),
    )
    for item in pending:
        mid = _decode(item['message_id'])
        counts[mid] = int(item['times_delivered'])
    return counts


def ack_entries(entry_ids: list[str], con=None, stream_key=None, group_name=None) -> int:
    if not entry_ids:
        return 0
    con = con or get_redis_connection('default')
    stream_key = stream_key or TELEMETRY_STREAM_KEY
    group_name = group_name or TELEMETRY_CONSUMER_GROUP
    return int(con.xack(stream_key, group_name, *entry_ids))


def get_stream_metrics(con=None, stream_key=None, dlq_key=None, group_name=None) -> dict:
    con = con or get_redis_connection('default')
    stream_key = stream_key or TELEMETRY_STREAM_KEY
    dlq_key = dlq_key or TELEMETRY_DLQ_STREAM_KEY
    group_name = group_name or TELEMETRY_CONSUMER_GROUP
    stream_length = int(con.xlen(stream_key))
    dlq_length = int(con.xlen(dlq_key))
    pending_count = 0
    lag = 0
    try:
        groups = con.xinfo_groups(stream_key)
        for group in groups:
            name = _decode(group.get('name') or group.get(b'name'))
            if name == group_name:
                pending_count = int(group.get('pending') or group.get(b'pending') or 0)
                raw_lag = group.get('lag') if 'lag' in group else group.get(b'lag')
                lag = int(raw_lag) if raw_lag is not None else 0
                break
    except ResponseError:
        pass
    return {
        'stream_length': stream_length,
        'dlq_length': dlq_length,
        'pending_count': pending_count,
        'lag': lag,
    }
