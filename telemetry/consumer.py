import json
import logging
import socket
import threading
import uuid
from collections import defaultdict
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django_redis import get_redis_connection
from monitoring.metrics import INGEST_DLQ_TOTAL, INGEST_PERSISTED_TOTAL
from .ingestion import (
    TELEMETRY_CONSUMER_GROUP,
    TELEMETRY_DLQ_STREAM_KEY,
    TELEMETRY_MAX_DELIVERIES,
    TELEMETRY_STREAM_KEY,
    ack_entries,
    claim_stale_entries,
    ensure_consumer_group,
    get_delivery_counts,
    push_to_dlq,
    read_stream_batch,
)
from .models import MetricLog

logger = logging.getLogger(__name__)

_OPTIONAL_NUMERIC_FIELDS = (
    'disk_io',
    'swap_usage',
    'disk_usage',
    'disk_read_bps',
    'disk_write_bps',
    'net_rx_bps',
    'net_tx_bps',
    'load_1m',
)


def _parse_metric_record(raw_payload: str):
    data = json.loads(raw_payload)
    if not isinstance(data, dict):
        raise ValueError('Payload must be a JSON object')

    server_id = data.get('server_id') or data.get('server')
    company_id = data.get('company_id') or data.get('company')
    if not server_id or not company_id:
        raise ValueError('Missing server_id or company_id')

    server_uuid = uuid.UUID(str(server_id))
    company_uuid = uuid.UUID(str(company_id))

    raw_ts = data.get('timestamp')
    parsed_ts = parse_datetime(raw_ts) if isinstance(raw_ts, str) else raw_ts
    if parsed_ts is None:
        raise ValueError('Invalid or missing timestamp')
    if timezone.is_naive(parsed_ts):
        parsed_ts = timezone.make_aware(parsed_ts, timezone.utc)

    raw_received = data.get('received_at')
    parsed_received = parse_datetime(raw_received) if isinstance(raw_received, str) else raw_received
    if parsed_received is None:
        parsed_received = timezone.now()
    elif timezone.is_naive(parsed_received):
        parsed_received = timezone.make_aware(parsed_received, timezone.utc)

    cpu_usage = float(data['cpu_usage'])
    ram_usage = float(data['ram_usage'])
    if not (0.0 <= cpu_usage <= 100.0) or not (0.0 <= ram_usage <= 100.0):
        raise ValueError('CPU and RAM usage must be between 0 and 100')

    log_kwargs = {
        'server_id': server_uuid,
        'company_id': company_uuid,
        'timestamp': parsed_ts,
        'received_at': parsed_received,
        'cpu_usage': cpu_usage,
        'ram_usage': ram_usage,
    }

    if data.get('sample_id'):
        log_kwargs['sample_id'] = uuid.UUID(str(data['sample_id']))

    for field in _OPTIONAL_NUMERIC_FIELDS:
        if data.get(field) is not None:
            log_kwargs[field] = float(data[field])

    if data.get('uptime_seconds') is not None:
        log_kwargs['uptime_seconds'] = int(data['uptime_seconds'])

    details = data.get('details')
    if isinstance(details, dict):
        log_kwargs['details'] = details

    broadcast_payload = {
        'server_id': str(server_uuid),
        'company_id': str(company_uuid),
        'timestamp': parsed_ts.isoformat(),
        'cpu_usage': cpu_usage,
        'ram_usage': ram_usage,
        'disk_io': log_kwargs.get('disk_io'),
    }
    return MetricLog(**log_kwargs), broadcast_payload


class IngestConsumer:
    def __init__(
        self,
        consumer_name=None,
        batch_size=500,
        block_ms=1000,
        claim_idle_ms=30000,
        max_deliveries=TELEMETRY_MAX_DELIVERIES,
        stream_key=TELEMETRY_STREAM_KEY,
        dlq_key=TELEMETRY_DLQ_STREAM_KEY,
        group_name=TELEMETRY_CONSUMER_GROUP,
    ):
        self.consumer_name = consumer_name or f'{socket.gethostname()}-{uuid.uuid4().hex[:8]}'
        self.batch_size = batch_size
        self.block_ms = block_ms
        self.claim_idle_ms = claim_idle_ms
        self.max_deliveries = max_deliveries
        self.stream_key = stream_key
        self.dlq_key = dlq_key
        self.group_name = group_name

    def _route_failed_entry(self, entry_id, raw_payload, error, deliveries, con):
        if deliveries >= self.max_deliveries:
            push_to_dlq(
                entry_id=entry_id,
                raw_payload=raw_payload,
                error=str(error),
                deliveries=deliveries,
                con=con,
                dlq_key=self.dlq_key,
            )
            logger.error(
                f'Moved poison telemetry entry {entry_id} to DLQ after {deliveries} deliveries: {error}'
            )
            return True
        logger.warning(
            f'Telemetry entry {entry_id} failed ({deliveries}/{self.max_deliveries}): {error}'
        )
        return False

    def _broadcast_company_batches(self, broadcasts):
        if not broadcasts:
            return
        channel_layer = get_channel_layer()
        if not channel_layer:
            return

        grouped = defaultdict(list)
        for sample in broadcasts:
            grouped[sample['company_id']].append(sample)

        for company_id, samples in grouped.items():
            async_to_sync(channel_layer.group_send)(
                f'company_{company_id}',
                {
                    'type': 'telemetry_batch',
                    'samples': samples,
                },
            )

    def _persist_individually(self, valid_items, delivery_counts, con):
        persisted_logs = []
        committed_broadcasts = []
        ack_ids = []
        dlq_count = 0
        retried_count = 0

        for entry_id, raw_payload, log_obj, broadcast_payload in valid_items:
            try:
                with transaction.atomic():
                    MetricLog.unscoped.bulk_create([log_obj], ignore_conflicts=True)
                persisted_logs.append(log_obj)
                committed_broadcasts.append(broadcast_payload)
                ack_ids.append(entry_id)
            except IntegrityError as exc:
                deliveries = delivery_counts.get(entry_id, 1)
                if self._route_failed_entry(entry_id, raw_payload, exc, deliveries, con):
                    ack_ids.append(entry_id)
                    dlq_count += 1
                else:
                    retried_count += 1

        if committed_broadcasts:
            transaction.on_commit(lambda: self._broadcast_company_batches(committed_broadcasts))

        return persisted_logs, ack_ids, dlq_count, retried_count

    def process_entries(self, entries, con=None):
        if not entries:
            return {'persisted': 0, 'acked': 0, 'dlq': 0, 'retried': 0}

        con = con or get_redis_connection('default')
        entry_ids = [entry_id for entry_id, _ in entries]
        delivery_counts = get_delivery_counts(
            entry_ids,
            con=con,
            stream_key=self.stream_key,
            group_name=self.group_name,
        )

        valid_items = []
        ack_ids = []
        dlq_count = 0
        retried_count = 0

        for entry_id, fields in entries:
            raw_payload = fields.get('payload', '')
            try:
                log_obj, broadcast_payload = _parse_metric_record(raw_payload)
                valid_items.append((entry_id, raw_payload, log_obj, broadcast_payload))
            except Exception as exc:
                deliveries = delivery_counts.get(entry_id, 1)
                if self._route_failed_entry(entry_id, raw_payload, exc, deliveries, con):
                    ack_ids.append(entry_id)
                    dlq_count += 1
                else:
                    retried_count += 1

        persisted_logs = []

        if valid_items:
            try:
                batch_broadcasts = [item[3] for item in valid_items]
                with transaction.atomic():
                    MetricLog.unscoped.bulk_create(
                        [item[2] for item in valid_items],
                        ignore_conflicts=True,
                    )
                    transaction.on_commit(lambda: self._broadcast_company_batches(batch_broadcasts))
                persisted_logs = [item[2] for item in valid_items]
                ack_ids.extend(item[0] for item in valid_items)
            except IntegrityError:
                (
                    persisted_logs,
                    isolated_acks,
                    isolated_dlq,
                    isolated_retried,
                ) = self._persist_individually(valid_items, delivery_counts, con)
                ack_ids.extend(isolated_acks)
                dlq_count += isolated_dlq
                retried_count += isolated_retried

        acked = ack_entries(
            ack_ids,
            con=con,
            stream_key=self.stream_key,
            group_name=self.group_name,
        )

        if persisted_logs:
            INGEST_PERSISTED_TOTAL.inc(len(persisted_logs))
        if dlq_count:
            INGEST_DLQ_TOTAL.inc(dlq_count)

        return {
            'persisted': len(persisted_logs),
            'acked': acked,
            'dlq': dlq_count,
            'retried': retried_count,
        }

    def run_once(self, reclaim=True, con=None):
        con = con or get_redis_connection('default')
        ensure_consumer_group(con=con, stream_key=self.stream_key, group_name=self.group_name)
        totals = {'persisted': 0, 'acked': 0, 'dlq': 0, 'retried': 0}

        if reclaim:
            claimed = claim_stale_entries(
                consumer_name=self.consumer_name,
                min_idle_ms=self.claim_idle_ms,
                count=self.batch_size,
                con=con,
                stream_key=self.stream_key,
                group_name=self.group_name,
            )
            if claimed:
                claimed_stats = self.process_entries(claimed, con=con)
                for key in totals:
                    totals[key] += claimed_stats[key]

        fresh = read_stream_batch(
            consumer_name=self.consumer_name,
            count=self.batch_size,
            block_ms=self.block_ms,
            con=con,
            stream_key=self.stream_key,
            group_name=self.group_name,
        )
        if fresh:
            fresh_stats = self.process_entries(fresh, con=con)
            for key in totals:
                totals[key] += fresh_stats[key]

        return totals

    def run_forever(self, stop_event: threading.Event | None = None):
        stop_event = stop_event or threading.Event()
        logger.info(
            f'Starting ingest consumer {self.consumer_name} on stream {self.stream_key} '
            f'(group={self.group_name}, batch_size={self.batch_size})'
        )
        while not stop_event.is_set():
            try:
                self.run_once(reclaim=True)
            except Exception as exc:
                logger.error(f'Ingest consumer loop error: {exc}', exc_info=True)
                stop_event.wait(1.0)
        logger.info(f'Ingest consumer {self.consumer_name} stopped cleanly.')
