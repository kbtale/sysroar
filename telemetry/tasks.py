import json
import logging
from celery import shared_task
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from .ingestion import pop_batch, ack_batch, nack_batch
from .models import MetricLog, MetricRollup
from django.db.models.functions import TruncHour
from django.db.models import Avg
from django.utils import timezone
from datetime import timedelta
from django.conf import settings

logger = logging.getLogger(__name__)

@shared_task(name="telemetry.process_telemetry_batch")
def process_telemetry_batch():
    """
    Drains the Redis queue and persists telemetry in batches to PostgreSQL.
    """
    batch_data = pop_batch(batch_size=1000)
    if not batch_data:
        return 0
    
    logs_to_create = []
    channel_layer = get_channel_layer()

    for data in batch_data:
        try:
            # Map legacy 'server' to 'server_id' if needed
            if 'server' in data and 'server_id' not in data:
                data['server_id'] = data.pop('server')
            
            if 'company' in data and 'company_id' not in data:
                data['company_id'] = data.pop('company')

            logs_to_create.append(MetricLog(**data))
            
            # Broadcast each metric to its server-specific group
            async_to_sync(channel_layer.group_send)(
                f"server_{data['server_id']}",
                {
                    "type": "telemetry_message",
                    "message": data
                }
            )

        except Exception as e:
            logger.warning(f"Skipping malformed telemetry record: {e}")

    if logs_to_create:
        try:
            created_instances = MetricLog.unscoped.bulk_create(logs_to_create)
            ack_batch()
            logger.info(f"Successfully persisted batch of {len(created_instances)} metrics to PostgreSQL.")
            
            # Trigger evaluation for the newly created IDs
            from monitoring.tasks import evaluate_metrics_batch
            new_ids = [str(log.id) for log in created_instances]
            evaluate_metrics_batch.delay(new_ids)
            
        except Exception as e:
            nack_batch()
            logger.error(
                f"METRIC_PERSISTENCE_FAILURE | Critical failure during bulk_create: {e}. "
                f"Batch Size: {len(logs_to_create)}",
                exc_info=True
            )
            from monitoring.tasks import record_system_event
            record_system_event.delay(
                event_type='METRIC_PERSISTENCE_FAILURE',
                severity='CRITICAL',
                context={'batch_size': len(logs_to_create), 'error': str(e)}
            )
            raise

    return len(logs_to_create)

@shared_task(name="telemetry.rollup_telemetry_data")
def rollup_telemetry_data():
    """
    Aggregates MetricLog entries from the previous hour into MetricRollup.
    Runs hourly (e.g., at 2:00 for the 1:00-1:59 block).
    """
    # Calculate the previous hour window
    now = timezone.now()
    last_hour = now - timedelta(hours=1)
    start_time = last_hour.replace(minute=0, second=0, microsecond=0)
    end_time = start_time + timedelta(hours=1)

    logger.info(f"Starting telemetry rollup for window: {start_time} to {end_time}")

    # Aggregate raw logs by server and truncated hour
    aggregates = MetricLog.unscoped.filter(
        timestamp__range=(start_time, end_time)
    ).values('server_id', 'company_id').annotate(
        hour=TruncHour('timestamp'),
        avg_cpu_val=Avg('cpu_usage'),
        avg_ram_val=Avg('ram_usage'),
        avg_disk_val=Avg('disk_io')
    )

    rollups_to_create = []
    for agg in aggregates:
        rollups_to_create.append(MetricRollup(
            server_id=agg['server_id'],
            company_id=agg['company_id'],
            timestamp=agg['hour'],
            avg_cpu=agg['avg_cpu_val'],
            avg_ram=agg['avg_ram_val'],
            avg_disk_io=agg['avg_disk_val']
        ))

    if rollups_to_create:
        MetricRollup.unscoped.bulk_create(
            rollups_to_create,
            ignore_conflicts=True # Prevent crashes if task re-runs for same hour
        )
        logger.info(f"Created {len(rollups_to_create)} rollup records.")
    else:
        logger.info("No metric logs found for the previous hour; no rollups created.")

@shared_task(name="telemetry.purge_old_telemetry")
def purge_old_telemetry():
    """
    Deletes MetricLog entries older than the retention period.
    Default retention is 7 days.
    """
    retention_days = getattr(settings, 'TELEMETRY_RETENTION_DAYS', 7)
    cutoff_date = timezone.now() - timedelta(days=retention_days)

    logger.info(f"Starting telemetry purge for records older than {cutoff_date} ({retention_days} days retention)")

    deleted_count, _ = MetricLog.unscoped.filter(timestamp__lt=cutoff_date).delete()
    
    logger.info(f"Successfully purged {deleted_count} stale MetricLog records.")
    return deleted_count
