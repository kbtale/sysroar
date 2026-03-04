import uuid
import json
import logging
from django_redis import get_redis_connection

logger = logging.getLogger(__name__)

redis_client = get_redis_connection("default")

TELEMETRY_QUEUE_KEY = "sysroar:telemetry_queue"

class UUIDEncoder(json.JSONEncoder):
    def default(self, obj):
        import datetime
        if isinstance(obj, uuid.UUID):
            return str(obj)
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
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
    Atomically retrieves and removes a batch of telemetry data from the Redis queue.
    Ensures safe horizontal scaling across multiple concurrent workers.
    """
    lua_script = """
    local key = KEYS[1]
    local batch_size = tonumber(ARGV[1])
    local items = redis.call('LRANGE', key, 0, batch_size - 1)
    redis.call('LTRIM', key, batch_size, -1)
    return items
    """
    try:
        con = get_redis_connection("default")
        results = con.eval(lua_script, 1, TELEMETRY_QUEUE_KEY, batch_size)
        if not results:
            return []
        return [json.loads(p) for p in results]
    except Exception as e:
        logger.error(f"Failed to pop batch from Redis: {e}", exc_info=True)
        return []
