import uuid
import json
import logging
from django_redis import get_redis_connection

logger = logging.getLogger(__name__)

redis_client = get_redis_connection("default")

TELEMETRY_QUEUE_KEY = "sysroar:telemetry_queue"

class UUIDEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, uuid.UUID):
            return str(obj)
        return super().default(obj)

def push_to_redis_queue(telemetry_data: dict):
    """
    Pushes validated telemetry data to the Redis ingestion queue.
    The data is JSON-serialized before insertion.
    """
    try:
        con = get_redis_connection("default")
        payload = json.dumps(telemetry_data, cls=UUIDEncoder)
        con.lpush(TELEMETRY_QUEUE_KEY, payload)
    except Exception as e:
        logger.error(f"Failed to push telemetry to Redis: {e}", exc_info=True)
        raise

def pop_batch(batch_size: int = 1000):
    """
    Atomically retrieves a batch of telemetry data from the Redis queue.
    """
    try:
        con = get_redis_connection("default")
        pipe = con.pipeline()
        pipe.lrange(TELEMETRY_QUEUE_KEY, 0, batch_size - 1)
        pipe.ltrim(TELEMETRY_QUEUE_KEY, batch_size, -1)
        results = pipe.execute()
        
        # results[0] contains the list of payloads
        return [json.loads(p) for p in results[0]]
    except Exception as e:
        logger.error(f"Failed to pop batch from Redis: {e}", exc_info=True)
        return []
