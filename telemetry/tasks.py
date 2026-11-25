import logging
from asgiref.sync import async_to_sync
from celery import shared_task
from channels.layers import get_channel_layer
from .ingestion import ack_batch, nack_batch, pop_batch
from .models import MetricLog

logger = logging.getLogger(__name__)


@shared_task(name='telemetry.process_telemetry_batch', ignore_result=True)
def process_telemetry_batch():
    batch_data = pop_batch(batch_size=1000)
    if not batch_data:
        return 0

    logs_to_create = []
    channel_layer = get_channel_layer()

    for data in batch_data:
        try:
            if 'server' in data and 'server_id' not in data:
                data['server_id'] = data.pop('server')
            if 'company' in data and 'company_id' not in data:
                data['company_id'] = data.pop('company')
            if not data.get('server_id') or not data.get('company_id'):
                raise ValueError('Missing server_id or company_id')

            log_kwargs = {
                'server_id': data['server_id'],
                'company_id': data['company_id'],
                'timestamp': data['timestamp'],
                'cpu_usage': data['cpu_usage'],
                'ram_usage': data['ram_usage'],
                'disk_io': data.get('disk_io'),
            }
            logs_to_create.append(MetricLog(**log_kwargs))

            async_to_sync(channel_layer.group_send)(
                f"server_{data['server_id']}",
                {
                    'type': 'telemetry_message',
                    'message': data,
                },
            )
        except Exception as e:
            logger.warning(f'Skipping malformed telemetry record: {e}')

    if logs_to_create:
        try:
            created_instances = MetricLog.unscoped.bulk_create(logs_to_create, ignore_conflicts=True)
            ack_batch()
            logger.info(f'Successfully persisted batch of {len(created_instances)} metrics to PostgreSQL.')

            from monitoring.tasks import evaluate_metrics_batch
            new_ids = [str(log.id) for log in created_instances]
            evaluate_metrics_batch.delay(new_ids)
        except Exception as e:
            nack_batch()
            logger.error(
                f'METRIC_PERSISTENCE_FAILURE | Critical failure during bulk_create: {e}. '
                f'Batch Size: {len(logs_to_create)}',
                exc_info=True,
            )
            from monitoring.tasks import record_system_event
            record_system_event.delay(
                event_type='METRIC_PERSISTENCE_FAILURE',
                severity='CRITICAL',
                context={'batch_size': len(logs_to_create), 'error': str(e)},
            )
            raise

    return len(logs_to_create)
