from django.urls import path, include
from rest_framework.routers import SimpleRouter
from .views import AgentKeyViewSet, AlertRuleViewSet, AuditLogViewSet, EnrollmentTokenViewSet, ServerViewSet

router = SimpleRouter()
router.register(r'servers', ServerViewSet, basename='server')
router.register(r'rules', AlertRuleViewSet, basename='alert-rule')
router.register(r'enrollment-tokens', EnrollmentTokenViewSet, basename='enrollment-token')
router.register(r'agent-keys', AgentKeyViewSet, basename='agent-key')
router.register(r'audit-logs', AuditLogViewSet, basename='audit-log')

app_name = 'monitoring'

urlpatterns = [
    path('', include(router.urls)),
]
