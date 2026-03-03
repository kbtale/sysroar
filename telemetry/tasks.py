import json
from celery import shared_task
from .ingestion import redis_ingestion
import logging

logger = logging.getLogger(__name__)

@shared_task(name="telemetry.process_batches")
def process_telemetry_batches():
    """
    Celery task that runs periodically (Write-Behind) to batch create 
    MetricLog objects in PostgreSQL.
    """
    batch_data = redis_ingestion.get_batch(count=1000)
    if not batch_data:
        return 0
    
    logger.info(f"Processed batch of {len(batch_data)} telemetry items.")
    return len(batch_data)
