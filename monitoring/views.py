from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from accounts.mixins import TenantScopedViewSetMixin
from monitoring.heartbeat import get_live_heartbeats
from .models import AgentKey, EnrollmentToken, Server
from .serializers import (
    AgentKeySerializer,
    AgentKeyServerActionSerializer,
    EnrollmentTokenCreateSerializer,
    EnrollmentTokenSerializer,
    ServerSerializer,
)


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


class EnrollmentTokenViewSet(
    TenantScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = EnrollmentToken.unscoped.all().order_by('-created_at', 'id')
    serializer_class = EnrollmentTokenSerializer

    def create(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if company is None:
            return Response({'error': 'Tenant company required.'}, status=status.HTTP_403_FORBIDDEN)
        serializer = EnrollmentTokenCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token_obj, plaintext = EnrollmentToken.generate(
            company=company,
            name=serializer.validated_data['name'].strip(),
            created_by=request.user,
            max_uses=serializer.validated_data.get('max_uses'),
            expires_in_hours=serializer.validated_data.get('expires_in_hours'),
        )
        data = EnrollmentTokenSerializer(token_obj).data
        data['token'] = plaintext
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        token_obj = self.get_object()
        token_obj.revoke()
        return Response(EnrollmentTokenSerializer(token_obj).data, status=status.HTTP_200_OK)


class AgentKeyViewSet(
    TenantScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = AgentKey.unscoped.all().order_by('-created_at', 'id')
    serializer_class = AgentKeySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        server_id = self.request.query_params.get('server')
        if server_id:
            qs = qs.filter(server_id=server_id)
        return qs

    def _resolve_owned_server(self, request):
        serializer = AgentKeyServerActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company_id = getattr(request.user, 'company_id', None)
        if not company_id:
            return None
        return Server.unscoped.filter(
            id=serializer.validated_data['server'],
            company_id=company_id,
        ).first()

    def create(self, request, *args, **kwargs):
        server = self._resolve_owned_server(request)
        if server is None:
            return Response({'error': 'Server not found.'}, status=status.HTTP_404_NOT_FOUND)
        key_obj, plaintext = AgentKey.generate(server=server, created_by=request.user)
        data = AgentKeySerializer(key_obj).data
        data['key'] = plaintext
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def rotate(self, request):
        server = self._resolve_owned_server(request)
        if server is None:
            return Response({'error': 'Server not found.'}, status=status.HTTP_404_NOT_FOUND)
        key_obj, plaintext = AgentKey.rotate(server=server, created_by=request.user)
        data = AgentKeySerializer(key_obj).data
        data['key'] = plaintext
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        key_obj = self.get_object()
        key_obj.revoke()
        return Response(AgentKeySerializer(key_obj).data, status=status.HTTP_200_OK)
