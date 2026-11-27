import asyncio
from datetime import timedelta
import json
import logging
from urllib.parse import parse_qs
from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone
from monitoring.models import Server
from monitoring.tasks import record_system_event
from telemetry.logs import get_log_backend

logger = logging.getLogger(__name__)


class CompanyTelemetryConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get('user')
        if not self.user or not self.user.is_authenticated or not getattr(self.user, 'company_id', None):
            await self.close(code=4401)
            return

        self.company_id = str(self.user.company_id)
        self.group_name = f'company_{self.company_id}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def telemetry_batch(self, event):
        await self.send(text_data=json.dumps({'type': 'telemetry_batch', 'samples': event['samples']}))


class ServerTelemetryConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.server_id = str(self.scope['url_route']['kwargs']['server_id'])
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

        self.group_name = f'company_{self.user.company_id}'
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

    async def telemetry_batch(self, event):
        for sample in event.get('samples', []):
            if sample.get('server_id') == self.server_id:
                await self.send(text_data=json.dumps(sample))


class LogTailConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get('user')
        if not self.user or not self.user.is_authenticated or not getattr(self.user, 'company_id', None):
            await self.close(code=4401)
            return

        qs = parse_qs((self.scope.get('query_string') or b'').decode('utf-8', errors='ignore'))
        self.server_id = (qs.get('server_id', [''])[0] or '').strip() or None
        self.q = (qs.get('q', [''])[0] or '').strip()[:256]
        self.level = (qs.get('level', [''])[0] or '').strip().upper()[:16]
        self.company_id = str(self.user.company_id)

        if self.server_id:
            exists = await Server.unscoped.filter(id=self.server_id, company_id=self.user.company_id).aexists()
            if not exists:
                await self.close(code=4403)
                return

        await self.accept()
        self._tail_task = asyncio.create_task(self._poll_loop())

    async def disconnect(self, close_code):
        task = getattr(self, '_tail_task', None)
        if task is not None:
            task.cancel()

    async def _poll_loop(self):
        cursor = timezone.now() - timedelta(seconds=15)
        try:
            while True:
                backend = get_log_backend()
                if backend.enabled:
                    now = timezone.now()
                    try:
                        entries = await sync_to_async(backend.query)(
                            company_id=self.company_id,
                            server_id=self.server_id,
                            q=self.q,
                            level=self.level,
                            start=cursor,
                            end=now,
                            limit=100,
                        )
                    except Exception:
                        entries = []
                    cursor = now
                    if entries:
                        await self.send(text_data=json.dumps({'type': 'log_lines', 'entries': entries}))
                await asyncio.sleep(2)
        except asyncio.CancelledError:
            return
