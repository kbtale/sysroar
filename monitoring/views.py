from rest_framework import viewsets
from rest_framework.response import Response
from accounts.mixins import TenantScopedViewSetMixin
from monitoring.heartbeat import get_live_heartbeats
from .models import Server
from .serializers import ServerSerializer


class ServerViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Server.unscoped.all().order_by('created_at', 'id')
    serializer_class = ServerSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        items = list(page) if page is not None else list(queryset)
        live_heartbeats = get_live_heartbeats([server.id for server in items])
        context = {**self.get_serializer_context(), 'live_heartbeats': live_heartbeats}
        serializer = self.get_serializer(items, many=True, context=context)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)
