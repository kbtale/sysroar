from rest_framework import viewsets
from accounts.mixins import TenantScopedViewSetMixin
from .models import Server
from .serializers import ServerSerializer


class ServerViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Server.unscoped.all().order_by('created_at', 'id')
    serializer_class = ServerSerializer
