import uuid
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, SessionAuthentication, TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed
from accounts.middleware import set_current_company_id
from telemetry.ingestion import redis_client


class AgentPrincipal:
    is_authenticated = True
    is_active = True
    is_anonymous = False
    is_agent = True
    is_staff = False
    is_superuser = False

    def __init__(self, agent_key):
        self.agent_key = agent_key
        self.id = agent_key.id
        self.pk = agent_key.id
        self.server_id = agent_key.server_id
        self.company_id = agent_key.company_id
        self.username = f'agent:{agent_key.prefix}'


class AgentKeyAuthentication(BaseAuthentication):
    keyword = 'AgentKey'

    def authenticate(self, request):
        auth_header = request.headers.get('Authorization', '')
        prefix_header = f'{self.keyword} '
        if not auth_header.startswith(prefix_header):
            return None

        raw_key = auth_header[len(prefix_header):].strip()
        if not raw_key or '.' not in raw_key:
            raise AuthenticationFailed('Invalid agent key.')

        key_prefix = raw_key.split('.', 1)[0]
        from monitoring.models import AgentKey

        agent_key = (
            AgentKey.unscoped.select_related('server')
            .filter(prefix=key_prefix, is_active=True, revoked_at__isnull=True)
            .first()
        )
        if agent_key is None or not agent_key.verify(raw_key):
            raise AuthenticationFailed('Invalid or revoked agent key.')

        now = timezone.now()
        if agent_key.last_used_at is None or (now - agent_key.last_used_at).total_seconds() >= 60:
            AgentKey.unscoped.filter(id=agent_key.id).update(last_used_at=now)

        set_current_company_id(agent_key.company_id)
        return (AgentPrincipal(agent_key), agent_key)

    def authenticate_header(self, request):
        return self.keyword


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

    def consume_ticket(self, ticket: str):
        key = f"{self.prefix}{ticket}"
        user_id = self.redis.getdel(key)
        if isinstance(user_id, bytes):
            return user_id.decode('utf-8')
        return user_id


ticket_manager = WebSocketTicketManager()
