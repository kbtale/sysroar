import uuid
from telemetry.ingestion import redis_ingestion

class WebSocketTicketManager:
    """
    Manages one-time-use tickets for secure WebSocket authentication.
    """
    def __init__(self):
        self.redis = redis_ingestion.client
        self.prefix = "ws:ticket:"
        self.ttl = 60 # Secs

    def create_ticket(self, user_id: str) -> str:
        """
        Creates a short-lived ticket mapped to a user ID.
        """
        ticket = str(uuid.uuid4())
        key = f"{self.prefix}{ticket}"
        self.redis.setex(key, self.ttl, user_id)
        return ticket

    def consume_ticket(self, ticket: str) -> str:
        """
        Retrieves the user ID for a ticket and deletes it immediately.
        """
        key = f"{self.prefix}{ticket}"
        user_id = self.redis.get(key)
        if user_id:
            self.redis.delete(key)
        return user_id

ticket_manager = WebSocketTicketManager()
