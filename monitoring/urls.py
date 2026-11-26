from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AgentKeyViewSet, EnrollmentTokenViewSet, ServerViewSet

router = DefaultRouter()
router.register(r'servers', ServerViewSet, basename='server')
router.register(r'enrollment-tokens', EnrollmentTokenViewSet, basename='enrollment-token')
router.register(r'agent-keys', AgentKeyViewSet, basename='agent-key')

app_name = 'monitoring'

urlpatterns = [
    path('', include(router.urls)),
]
