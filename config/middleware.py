from channels.db import database_sync_to_async
import uuid
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from accounts.authentication import ticket_manager
from .logging_utils import set_correlation_id, clear_correlation_id

User = get_user_model()

@database_sync_to_async
def get_user(user_id):
    try:
        return User.objects.get(id=user_id)
    except User.DoesNotExist:
        return AnonymousUser()

class WebSocketTicketMiddleware:
    """
    Custom middleware for Django Channels to authenticate 
    via a one-time Redis ticket.
    """
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        query_params = scope.get('query_string', b'').decode().split('&')
        ticket = None
        
        for param in query_params:
            if param.startswith('ticket='):
                ticket = param.split('=')[1]
                break
        
        if ticket:
            user_id = ticket_manager.consume_ticket(ticket)
            if user_id:
                scope['user'] = await get_user(user_id)
            else:
                scope['user'] = AnonymousUser()
        else:
            scope['user'] = AnonymousUser()

        return await self.inner(scope, receive, send)

class CorrelationIdMiddleware:
    """
    HTTP middleware to generate/propagate a Correlation ID for every request.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        set_correlation_id(correlation_id)
        
        request.correlation_id = correlation_id
        response = self.get_response(request)
        response["X-Correlation-ID"] = correlation_id
        clear_correlation_id()
        return response
