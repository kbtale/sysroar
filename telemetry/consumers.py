import json
import logging
from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from monitoring.models import Server
from monitoring.tasks import record_system_event

logger = logging.getLogger(__name__)


class ServerTelemetryConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.server_id = str(self.scope['url_route']['kwargs']['server_id'])
        self.group_name = f'server_{self.server_id}'
        self.user = self.scope.get('user')

        if not self.user or not self.user.is_authenticated or not getattr(self.user, 'company_id', None):
            await self.close(code=4401)
            return

        try:
            server_exists = await Server.unscoped.filter(
                id=self.server_id,
                company_id=self.user.company_id,
            ).aexists()

            if not server_exists:
                logger.error(
                    f'WS_AUTH_FAILURE | Unauthorized access attempt to server {self.server_id} by user {self.user.id}'
                )
                await sync_to_async(record_system_event.delay)(
                    event_type='WS_AUTH_FAILURE',
                    severity='WARNING',
                    context={'server_id': self.server_id, 'user_id': str(self.user.id)},
                )
                await self.close(code=4403)
                return
        except Exception as e:
            logger.error(
                f'WS_ERROR | Unexpected error during WebSocket auth for server {self.server_id}: {str(e)}'
            )
            await sync_to_async(record_system_event.delay)(
                event_type='WS_ERROR',
                severity='ERROR',
                context={'server_id': self.server_id, 'error': str(e)},
            )
            await self.close(code=4500)
            return

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name,
            )

    async def telemetry_message(self, event):
        message = event['message']
        await self.send(text_data=json.dumps(message))
