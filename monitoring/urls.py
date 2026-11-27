from django.urls import include, path
from rest_framework.routers import SimpleRouter
from .views import (
    AgentKeyViewSet,
    AlertRuleViewSet,
    AlertSilenceViewSet,
    AuditLogViewSet,
    EnrollmentTokenViewSet,
    IncidentViewSet,
    NotificationChannelViewSet,
    ServerViewSet,
)

router = SimpleRouter()
router.register(r'servers', ServerViewSet, basename='server')
router.register(r'channels', NotificationChannelViewSet, basename='notification-channel')
router.register(r'rules', AlertRuleViewSet, basename='alert-rule')
router.register(r'incidents', IncidentViewSet, basename='incident')
router.register(r'silences', AlertSilenceViewSet, basename='alert-silence')
router.register(r'enrollment-tokens', EnrollmentTokenViewSet, basename='enrollment-token')
router.register(r'agent-keys', AgentKeyViewSet, basename='agent-key')
router.register(r'audit-logs', AuditLogViewSet, basename='audit-log')

app_name = 'monitoring'

urlpatterns = [
    path('', include(router.urls)),
]
