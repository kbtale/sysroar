import uuid
from telemetry.ingestion import redis_client

class WebSocketTicketManager:
    """
    Manages one-time-use tickets for secure WebSocket authentication.
    """
    def __init__(self):
        self.redis = redis_client
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
        Atomically retrieves and deletes a one-time ticket.
        Uses GETDEL to prevent race conditions with concurrent connections.
        """
        key = f"{self.prefix}{ticket}"
        user_id = self.redis.getdel(key)
        return user_id

ticket_manager = WebSocketTicketManager()
