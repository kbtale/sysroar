import json
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from monitoring.models import Server
from monitoring.tasks import record_system_event
import logging

logger = logging.getLogger(__name__)

class ServerTelemetryConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.server_id = str(self.scope['url_route']['kwargs']['server_id'])
        self.group_name = f"server_{self.server_id}"
        self.user = self.scope.get('user')

        # Authentication check
        if not self.user or not self.user.is_authenticated:
            await self.close()
            return

        # Authorization check: Does this server belong to the user's company?
        try:
            # Using .unscoped cuz specific tenant filtering is handled via the permission check
            server_exists = await Server.unscoped.filter(
                id=self.server_id, 
                company=self.user.company
            ).aexists()
            
            if not server_exists:
                logger.error(f"WS_AUTH_FAILURE | Unauthorized access attempt to server {self.server_id} by user {self.user.id}")
                await sync_to_async(record_system_event.delay)(
                    event_type='WS_AUTH_FAILURE',
                    severity='WARNING',
                    context={'server_id': self.server_id, 'user_id': str(self.user.id)}
                )
                await self.close()
                return
        except Exception as e:
            logger.error(f"WS_ERROR | Unexpected error during WebSocket auth for server {self.server_id}: {str(e)}")
            await sync_to_async(record_system_event.delay)(
                event_type='WS_ERROR',
                severity='ERROR',
                context={'server_id': self.server_id, 'error': str(e)}
            )
            await self.close()
            return

        # Join the server-specific group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave the server-specific group
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def telemetry_message(self, event):
        """
        Receives message from the channel layer group and sends it over WebSocket.
        """
        message = event['message']
        await self.send(text_data=json.dumps(message))
