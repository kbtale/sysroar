from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from accounts.mixins import TenantScopedViewSetMixin
from accounts.permissions import IsCompanyAdmin, ReadOnlyOrCompanyMember
from monitoring.audit import record_audit_event
from monitoring.heartbeat import get_live_heartbeats
from .models import AgentKey, AlertRule, AuditLog, EnrollmentToken, Server
from .serializers import (
    AgentKeySerializer,
    AgentKeyServerActionSerializer,
    AlertRuleSerializer,
    AuditLogSerializer,
    EnrollmentTokenCreateSerializer,
    EnrollmentTokenSerializer,
    ServerSerializer,
)


class ServerViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Server.unscoped.all().order_by('created_at', 'id')
    serializer_class = ServerSerializer
    permission_classes = [ReadOnlyOrCompanyMember]

    def perform_create(self, serializer):
        server = serializer.save(company_id=self.request.user.company_id)
        record_audit_event(
            self.request,
            action='server.created',
            resource_type='server',
            resource_id=str(server.id),
            metadata={'name': server.name},
        )

    def perform_update(self, serializer):
        server = serializer.save()
        record_audit_event(
            self.request,
            action='server.updated',
            resource_type='server',
            resource_id=str(server.id),
            metadata={'name': server.name, 'is_active': server.is_active},
        )

    def perform_destroy(self, instance):
        server_id = str(instance.id)
        server_name = instance.name
        instance.delete()
        record_audit_event(
            self.request,
            action='server.deleted',
            resource_type='server',
            resource_id=server_id,
            metadata={'name': server_name},
        )

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


class AlertRuleViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = AlertRule.unscoped.select_related('server').all().order_by('id')
    serializer_class = AlertRuleSerializer
    permission_classes = [ReadOnlyOrCompanyMember]

    def perform_create(self, serializer):
        serializer.save(company_id=self.request.user.company_id)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rule = serializer.save(company_id=request.user.company_id)
        record_audit_event(
            request,
            action='alert_rule.created',
            resource_type='alert_rule',
            resource_id=str(rule.id),
            metadata={
                'server_id': str(rule.server_id),
                'metric_type': rule.metric_type,
                'notification_type': rule.notification_type,
            },
        )
        data = self.get_serializer(rule).data
        if rule.notification_type == 'WEBHOOK' and rule.webhook_secret:
            data['webhook_secret'] = rule.webhook_secret
        return Response(data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        rule = serializer.save()
        record_audit_event(
            self.request,
            action='alert_rule.updated',
            resource_type='alert_rule',
            resource_id=str(rule.id),
            metadata={
                'server_id': str(rule.server_id),
                'metric_type': rule.metric_type,
                'threshold_value': rule.threshold_value,
                'is_active': rule.is_active,
            },
        )

    def perform_destroy(self, instance):
        rule_id = str(instance.id)
        server_id = str(instance.server_id)
        instance.delete()
        record_audit_event(
            self.request,
            action='alert_rule.deleted',
            resource_type='alert_rule',
            resource_id=rule_id,
            metadata={'server_id': server_id},
        )

    @action(detail=True, methods=['post'], url_path='test-webhook')
    def test_webhook(self, request, pk=None):
        import requests as http_requests
        from telemetry.notifications.ssrf import SSRFBlockedError
        from telemetry.notifications.webhook import WebhookStrategy

        rule = self.get_object()
        if rule.notification_type != 'WEBHOOK' or not rule.notification_target:
            return Response(
                {'error': 'Rule is not configured with a webhook target.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            delivered, detail = WebhookStrategy().send_test(rule)
        except SSRFBlockedError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except http_requests.RequestException:
            return Response(
                {'delivered': False, 'error': 'Webhook delivery failed.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        record_audit_event(
            request,
            action='alert_rule.webhook_tested',
            resource_type='alert_rule',
            resource_id=str(rule.id),
            metadata={'delivered': delivered},
        )
        if delivered:
            return Response({'delivered': True, 'detail': detail}, status=status.HTTP_200_OK)
        return Response(
            {'delivered': False, 'detail': detail},
            status=status.HTTP_502_BAD_GATEWAY,
        )


class EnrollmentTokenViewSet(
    TenantScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = EnrollmentToken.unscoped.all().order_by('-created_at', 'id')
    serializer_class = EnrollmentTokenSerializer
    permission_classes = [IsCompanyAdmin]

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
        record_audit_event(
            request,
            action='enrollment_token.created',
            resource_type='enrollment_token',
            resource_id=str(token_obj.id),
            metadata={'name': token_obj.name, 'prefix': token_obj.prefix},
        )
        data = EnrollmentTokenSerializer(token_obj).data
        data['token'] = plaintext
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        token_obj = self.get_object()
        token_obj.revoke()
        record_audit_event(
            request,
            action='enrollment_token.revoked',
            resource_type='enrollment_token',
            resource_id=str(token_obj.id),
            metadata={'prefix': token_obj.prefix},
        )
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
    permission_classes = [IsCompanyAdmin]

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
        record_audit_event(
            request,
            action='agent_key.created',
            resource_type='agent_key',
            resource_id=str(key_obj.id),
            metadata={'server_id': str(server.id), 'prefix': key_obj.prefix},
        )
        data = AgentKeySerializer(key_obj).data
        data['key'] = plaintext
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def rotate(self, request):
        server = self._resolve_owned_server(request)
        if server is None:
            return Response({'error': 'Server not found.'}, status=status.HTTP_404_NOT_FOUND)
        key_obj, plaintext = AgentKey.rotate(server=server, created_by=request.user)
        record_audit_event(
            request,
            action='agent_key.rotated',
            resource_type='agent_key',
            resource_id=str(key_obj.id),
            metadata={'server_id': str(server.id), 'prefix': key_obj.prefix},
        )
        data = AgentKeySerializer(key_obj).data
        data['key'] = plaintext
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        key_obj = self.get_object()
        key_obj.revoke()
        record_audit_event(
            request,
            action='agent_key.revoked',
            resource_type='agent_key',
            resource_id=str(key_obj.id),
            metadata={'server_id': str(key_obj.server_id), 'prefix': key_obj.prefix},
        )
        return Response(AgentKeySerializer(key_obj).data, status=status.HTTP_200_OK)


class AuditLogViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.unscoped.all().order_by('-created_at', 'id')
    serializer_class = AuditLogSerializer
    permission_classes = [IsCompanyAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        action_filter = self.request.query_params.get('action')
        if action_filter:
            qs = qs.filter(action=action_filter)
        resource_type = self.request.query_params.get('resource_type')
        if resource_type:
            qs = qs.filter(resource_type=resource_type)
        return qs
