from django.urls import include, path
from rest_framework.routers import SimpleRouter
from .views import (
    AcceptInviteView,
    CompanyInviteViewSet,
    CompanyMemberViewSet,
    CompanyViewSet,
    CsrfTokenView,
    CurrentUserView,
    LogoutAllView,
    OpenRegistrationView,
    SessionLoginView,
    SessionLogoutView,
    SetupStatusView,
    SetupWizardView,
    WebSocketTicketView,
)

router = SimpleRouter()
router.register(r'invites', CompanyInviteViewSet, basename='company-invite')
router.register(r'members', CompanyMemberViewSet, basename='company-member')
router.register(r'companies', CompanyViewSet, basename='company')

app_name = 'accounts'

urlpatterns = [
    path('setup/status/', SetupStatusView.as_view(), name='setup-status'),
    path('setup/', SetupWizardView.as_view(), name='setup-wizard'),
    path('auth/register/', OpenRegistrationView.as_view(), name='auth-register'),
    path('auth/csrf/', CsrfTokenView.as_view(), name='auth-csrf'),
    path('auth/login/', SessionLoginView.as_view(), name='user-login'),
    path('auth/logout/', SessionLogoutView.as_view(), name='user-logout'),
    path('auth/logout-all/', LogoutAllView.as_view(), name='user-logout-all'),
    path('auth/me/', CurrentUserView.as_view(), name='auth-me'),
    path('auth/ticket/', WebSocketTicketView.as_view(), name='ws-ticket'),
    path('invites/accept/', AcceptInviteView.as_view(), name='accept-invite'),
    path('', include(router.urls)),
]
