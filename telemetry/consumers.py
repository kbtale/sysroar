import json
from channels.generic.websocket import AsyncWebsocketConsumer
from monitoring.models import Server

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
                await self.close()
                return
        except Exception:
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
