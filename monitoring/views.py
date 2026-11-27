from collections import defaultdict
from datetime import timedelta
from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from accounts.mixins import TenantScopedViewSetMixin
from accounts.permissions import IsCompanyAdmin, ReadOnlyOrCompanyMember
from monitoring.audit import record_audit_event
from monitoring.heartbeat import get_live_heartbeats
from telemetry.models import MetricLog
from .models import (
    AgentKey,
    AlertRule,
    AlertSilence,
    AuditLog,
    EnrollmentToken,
    Incident,
    IncidentComment,
    NotificationChannel,
    Server,
)
from .serializers import (
    AgentKeySerializer,
    AgentKeyServerActionSerializer,
    AlertRuleSerializer,
    AlertSilenceSerializer,
    AuditLogSerializer,
    EnrollmentTokenCreateSerializer,
    EnrollmentTokenSerializer,
    IncidentCommentCreateSerializer,
    IncidentCommentSerializer,
    IncidentSerializer,
    IncidentSilenceActionSerializer,
    NotificationChannelSerializer,
    ServerSerializer,
)


def _compute_server_overlays(company_id, servers):
    server_ids = [server.id for server in servers]
    live_heartbeats = get_live_heartbeats(server_ids)
    alert_statuses: dict[str, str] = {}
    sparklines: dict[str, list[dict]] = defaultdict(list)

    if server_ids and company_id:
        open_incidents = Incident.unscoped.filter(
            company_id=company_id,
            server_id__in=server_ids,
            status__in=('open', 'acknowledged'),
        ).values_list('server_id', 'severity')
        for sid, severity in open_incidents:
            key = str(sid)
            if severity == 'critical' or alert_statuses.get(key) != 'critical':
                alert_statuses[key] = severity

        cutoff = timezone.now() - timedelta(hours=1)
        recent_rows = (
            MetricLog.unscoped.filter(
                company_id=company_id,
                server_id__in=server_ids,
                timestamp__gte=cutoff,
            )
            .order_by('-timestamp')
            .values_list('server_id', 'timestamp', 'cpu_usage', 'ram_usage')[: len(server_ids) * 20]
        )
        for sid, ts, cpu, ram in recent_rows:
            key = str(sid)
            if len(sparklines[key]) < 15:
                sparklines[key].append(
                    {
                        't': ts.isoformat(),
                        'cpu': round(float(cpu), 1),
                        'ram': round(float(ram), 1),
                    }
                )
        for key in sparklines:
            sparklines[key].reverse()

    return live_heartbeats, alert_statuses, dict(sparklines)


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

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        company_id = getattr(request.user, 'company_id', None)
        live_heartbeats, alert_statuses, sparklines = _compute_server_overlays(
            company_id,
            [instance],
        )
        latest_details: dict[str, dict] = {}
        if company_id:
            latest_row = (
                MetricLog.unscoped.filter(company_id=company_id, server_id=instance.id)
                .order_by('-timestamp')
                .values_list('details', flat=True)
                .first()
            )
            if isinstance(latest_row, dict):
                latest_details[str(instance.id)] = latest_row
        context = {
            **self.get_serializer_context(),
            'live_heartbeats': live_heartbeats,
            'alert_statuses': alert_statuses,
            'sparklines': sparklines,
            'latest_details': latest_details,
        }
        return Response(self.get_serializer(instance, context=context).data)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        items = list(page) if page is not None else list(queryset)
        live_heartbeats, alert_statuses, sparklines = _compute_server_overlays(
            getattr(request.user, 'company_id', None),
            items,
        )
        context = {
            **self.get_serializer_context(),
            'live_heartbeats': live_heartbeats,
            'alert_statuses': alert_statuses,
            'sparklines': sparklines,
        }
        serializer = self.get_serializer(items, many=True, context=context)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class NotificationChannelViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = NotificationChannel.unscoped.all().order_by('-is_default', 'name', 'id')
    serializer_class = NotificationChannelSerializer
    permission_classes = [ReadOnlyOrCompanyMember]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        channel = serializer.save(company_id=request.user.company_id)
        record_audit_event(
            request,
            action='channel.created',
            resource_type='notification_channel',
            resource_id=str(channel.id),
            metadata={'name': channel.name, 'channel_type': channel.channel_type},
        )
        data = self.get_serializer(channel).data
        if channel.channel_type == 'WEBHOOK' and channel.webhook_secret:
            data['webhook_secret'] = channel.webhook_secret
        return Response(data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        channel = serializer.save()
        record_audit_event(
            self.request,
            action='channel.updated',
            resource_type='notification_channel',
            resource_id=str(channel.id),
            metadata={'name': channel.name, 'is_default': channel.is_default, 'is_active': channel.is_active},
        )

    def perform_destroy(self, instance):
        cid = str(instance.id)
        name = instance.name
        instance.delete()
        record_audit_event(
            self.request,
            action='channel.deleted',
            resource_type='notification_channel',
            resource_id=cid,
            metadata={'name': name},
        )

    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        import json
        import time
        import requests as http_requests
        from telemetry.notifications.ssrf import SSRFBlockedError, send_safe_webhook_post
        from telemetry.notifications.webhook import compute_webhook_signature

        channel = self.get_object()
        if channel.channel_type == 'EMAIL':
            try:
                send_mail(
                    subject='[SysRoar] Test Notification Channel',
                    message=f'Test notification from SysRoar channel "{channel.name}".',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[channel.target],
                    fail_silently=False,
                )
                return Response({'delivered': True, 'detail': 'Email dispatched'}, status=status.HTTP_200_OK)
            except Exception:
                return Response(
                    {'delivered': False, 'error': 'Email delivery failed.'},
                    status=status.HTTP_502_BAD_GATEWAY,
                )

        ts = str(int(time.time()))
        raw_body = json.dumps(
            {'event': 'channel_test', 'channel_id': str(channel.id), 'name': channel.name, 'timestamp': ts},
            separators=(',', ':'),
            sort_keys=True,
        ).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'SysRoar-Webhook/1.0',
            'X-SysRoar-Event': 'channel_test',
            'X-SysRoar-Timestamp': ts,
        }
        if channel.webhook_secret:
            headers['X-SysRoar-Signature-256'] = compute_webhook_signature(channel.webhook_secret, ts, raw_body)

        try:
            resp = send_safe_webhook_post(channel.target, raw_body, headers)
        except SSRFBlockedError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except http_requests.RequestException:
            return Response(
                {'delivered': False, 'error': 'Webhook delivery failed.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        if 200 <= resp.status_code < 300:
            return Response({'delivered': True, 'detail': f'HTTP {resp.status_code}'}, status=status.HTTP_200_OK)
        return Response({'delivered': False, 'detail': f'HTTP {resp.status_code}'}, status=status.HTTP_502_BAD_GATEWAY)


class AlertRuleViewSet(TenantScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = AlertRule.unscoped.select_related('server', 'channel').all().order_by('id')
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
                'server_id': str(rule.server_id) if rule.server_id else None,
                'scope': rule.scope,
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
                'server_id': str(rule.server_id) if rule.server_id else None,
                'metric_type': rule.metric_type,
                'threshold_value': rule.threshold_value,
                'is_active': rule.is_active,
            },
        )

    def perform_destroy(self, instance):
        rule_id = str(instance.id)
        server_id = str(instance.server_id) if instance.server_id else None
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


class IncidentViewSet(TenantScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Incident.unscoped.select_related('server', 'rule').prefetch_related('comments').order_by('-opened_at')
    serializer_class = IncidentSerializer
    permission_classes = [ReadOnlyOrCompanyMember]

    def get_queryset(self):
        qs = super().get_queryset()
        status_filter = self.request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter)
        severity = self.request.query_params.get('severity')
        if severity:
            qs = qs.filter(severity=severity)
        server_id = self.request.query_params.get('server')
        if server_id:
            qs = qs.filter(server_id=server_id)
        return qs

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        incident = self.get_object()
        if incident.status == 'resolved':
            return Response({'error': 'Incident is already resolved.'}, status=status.HTTP_400_BAD_REQUEST)
        incident.status = 'acknowledged'
        incident.acknowledged_at = timezone.now()
        incident.acknowledged_by = request.user
        incident.save(update_fields=['status', 'acknowledged_at', 'acknowledged_by'])
        record_audit_event(
            request,
            action='incident.acknowledged',
            resource_type='incident',
            resource_id=str(incident.id),
            metadata={'server_id': str(incident.server_id)},
        )
        return Response(IncidentSerializer(incident).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        incident = self.get_object()
        incident.status = 'resolved'
        incident.resolved_at = timezone.now()
        incident.resolved_by = request.user
        incident.save(update_fields=['status', 'resolved_at', 'resolved_by'])
        record_audit_event(
            request,
            action='incident.resolved',
            resource_type='incident',
            resource_id=str(incident.id),
            metadata={'server_id': str(incident.server_id)},
        )
        return Response(IncidentSerializer(incident).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def comments(self, request, pk=None):
        incident = self.get_object()
        serializer = IncidentCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = IncidentComment.unscoped.create(
            company_id=incident.company_id,
            incident=incident,
            author=request.user,
            author_username=request.user.username,
            body=serializer.validated_data['body'].strip(),
        )
        record_audit_event(
            request,
            action='incident.commented',
            resource_type='incident',
            resource_id=str(incident.id),
            metadata={'comment_id': str(comment.id)},
        )
        return Response(IncidentCommentSerializer(comment).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def silence(self, request, pk=None):
        incident = self.get_object()
        serializer = IncidentSilenceActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        now = timezone.now()
        duration = serializer.validated_data['duration_minutes']
        silence_obj = AlertSilence.unscoped.create(
            company_id=incident.company_id,
            server=incident.server,
            rule=incident.rule,
            reason=serializer.validated_data['reason'].strip() or f'Silenced from incident {incident.id}',
            created_by=request.user,
            starts_at=now,
            ends_at=now + timedelta(minutes=duration),
        )
        record_audit_event(
            request,
            action='incident.silenced',
            resource_type='alert_silence',
            resource_id=str(silence_obj.id),
            metadata={'incident_id': str(incident.id), 'duration_minutes': duration},
        )
        return Response(AlertSilenceSerializer(silence_obj).data, status=status.HTTP_201_CREATED)


class AlertSilenceViewSet(
    TenantScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = AlertSilence.unscoped.all().order_by('-ends_at', 'id')
    serializer_class = AlertSilenceSerializer
    permission_classes = [ReadOnlyOrCompanyMember]

    def perform_create(self, serializer):
        silence_obj = serializer.save(company_id=self.request.user.company_id, created_by=self.request.user)
        record_audit_event(
            self.request,
            action='silence.created',
            resource_type='alert_silence',
            resource_id=str(silence_obj.id),
            metadata={'ends_at': silence_obj.ends_at.isoformat()},
        )

    def perform_destroy(self, instance):
        sid = str(instance.id)
        instance.delete()
        record_audit_event(
            self.request,
            action='silence.deleted',
            resource_type='alert_silence',
            resource_id=sid,
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
