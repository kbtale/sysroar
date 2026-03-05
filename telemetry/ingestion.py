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
    Atomically moves a batch from the main queue to a processing key.
    Returns the parsed items. Use ack_batch() after successful DB write
    or nack_batch() to return items on failure.
    """
    processing_key = f"{TELEMETRY_QUEUE_KEY}:processing"
    lua_script = """
    local key = KEYS[1]
    local processing_key = KEYS[2]
    local batch_size = tonumber(ARGV[1])
    local items = redis.call('LRANGE', key, 0, batch_size - 1)
    if #items > 0 then
        for _, item in ipairs(items) do
            redis.call('RPUSH', processing_key, item)
        end
        redis.call('LTRIM', key, batch_size, -1)
    end
    return items
    """
    try:
        con = get_redis_connection("default")
        results = con.eval(lua_script, 2, TELEMETRY_QUEUE_KEY, processing_key, batch_size)
        if not results:
            return []
        return [json.loads(p) for p in results]
    except Exception as e:
        logger.error(f"Failed to pop batch from Redis: {e}", exc_info=True)
        return []

def ack_batch():
    """Clears the processing key after successful DB write."""
    try:
        con = get_redis_connection("default")
        con.delete(f"{TELEMETRY_QUEUE_KEY}:processing")
    except Exception as e:
        logger.error(f"Failed to ack batch: {e}", exc_info=True)

def nack_batch():
    """Returns items from the processing key back to the main queue on failure."""
    processing_key = f"{TELEMETRY_QUEUE_KEY}:processing"
    lua_script = """
    local main_key = KEYS[1]
    local processing_key = KEYS[2]
    local items = redis.call('LRANGE', processing_key, 0, -1)
    for _, item in ipairs(items) do
        redis.call('RPUSH', main_key, item)
    end
    redis.call('DEL', processing_key)
    return #items
    """
    try:
        con = get_redis_connection("default")
        count = con.eval(lua_script, 2, TELEMETRY_QUEUE_KEY, processing_key)
        logger.warning(f"Returned {count} items to the main queue after batch failure.")
    except Exception as e:
        logger.error(f"CRITICAL: Failed to nack batch: {e}", exc_info=True)
