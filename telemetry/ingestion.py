import redis
from django.conf import settings

class RedisIngestionClient:
    """
    Thread-safe Redis client using connection pooling for high-throughput 
    telemetry ingestion.
    """
    def __init__(self):
        self.pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=20,
            decode_responses=True
        )
        self.client = redis.Redis(connection_pool=self.pool)
        self.queue_key = "sysroar:telemetry:ingestion_queue"

    def push(self, data: str):
        """
        LPUSH telemetry data to the Redis queue.
        """
        return self.client.lpush(self.queue_key, data)

    def get_batch(self, count: int = 1000):
        """
        RPOP a batch of data from the queue for processing.
        """
        pipeline = self.client.pipeline()
        for _ in range(count):
            pipeline.rpop(self.queue_key)
        
        # Filter out None values from the pipeline results
        return [item for item in pipeline.execute() if item is not None]

# Singleton instance for high-performance reuse
redis_ingestion = RedisIngestionClient()
