import uuid
from urllib.parse import parse_qs
from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from accounts.authentication import ticket_manager
from .logging_utils import clear_correlation_id, set_correlation_id

User = get_user_model()


@database_sync_to_async
def get_user(user_id, expected_epoch=None):
    try:
        user = User.objects.get(id=user_id, is_active=True)
        if expected_epoch is not None and user.session_epoch != expected_epoch:
            return AnonymousUser()
        return user
    except (User.DoesNotExist, ValueError):
        return AnonymousUser()


class WebSocketTicketMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        raw_query = scope.get('query_string', b'').decode('utf-8', errors='ignore')
        tickets = parse_qs(raw_query).get('ticket', [])
        ticket = tickets[0] if tickets else None

        if ticket:
            payload = await sync_to_async(ticket_manager.consume_ticket)(ticket)
            if payload:
                if ':' in payload:
                    user_id, raw_epoch = payload.rsplit(':', 1)
                    try:
                        expected_epoch = int(raw_epoch)
                    except ValueError:
                        expected_epoch = -1
                else:
                    user_id = payload
                    expected_epoch = None
                scope['user'] = await get_user(user_id, expected_epoch=expected_epoch)
            else:
                scope['user'] = AnonymousUser()
        else:
            scope['user'] = AnonymousUser()

        return await self.inner(scope, receive, send)


class CorrelationIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        correlation_id = request.headers.get('X-Correlation-ID', str(uuid.uuid4()))
        set_correlation_id(correlation_id)

        request.correlation_id = correlation_id
        response = self.get_response(request)
        response['X-Correlation-ID'] = correlation_id
        clear_correlation_id()
        return response
