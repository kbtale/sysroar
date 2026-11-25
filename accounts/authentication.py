import uuid
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from accounts.middleware import set_current_company_id
from telemetry.ingestion import redis_client


class TenantTokenAuthentication(TokenAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user, _ = result
            set_current_company_id(getattr(user, 'company_id', None))
        return result


class TenantSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is not None:
            user, _ = result
            set_current_company_id(getattr(user, 'company_id', None))
        return result


class WebSocketTicketManager:
    def __init__(self):
        self.redis = redis_client
        self.prefix = "ws:ticket:"
        self.ttl = 60

    def create_ticket(self, user_id: str) -> str:
        ticket = str(uuid.uuid4())
        key = f"{self.prefix}{ticket}"
        self.redis.setex(key, self.ttl, user_id)
        return ticket

    def consume_ticket(self, ticket: str) -> str:
        key = f"{self.prefix}{ticket}"
        user_id = self.redis.getdel(key)
        return user_id


ticket_manager = WebSocketTicketManager()
