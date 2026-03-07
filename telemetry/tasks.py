import json
import logging
from celery import shared_task
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from .ingestion import pop_batch, ack_batch, nack_batch
from .models import MetricLog

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
            logger.error(f"Critical failure during bulk_create: {e}", exc_info=True)
            raise

    return len(logs_to_create)
