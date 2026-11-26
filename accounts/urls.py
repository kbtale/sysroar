from django.urls import path
from .views import (
    CsrfTokenView,
    CurrentUserView,
    LogoutAllView,
    SessionLoginView,
    SessionLogoutView,
    WebSocketTicketView,
)

app_name = 'accounts'

urlpatterns = [
    path('auth/csrf/', CsrfTokenView.as_view(), name='auth-csrf'),
    path('auth/login/', SessionLoginView.as_view(), name='user-login'),
    path('auth/logout/', SessionLogoutView.as_view(), name='user-logout'),
    path('auth/logout-all/', LogoutAllView.as_view(), name='user-logout-all'),
    path('auth/me/', CurrentUserView.as_view(), name='auth-me'),
    path('auth/ticket/', WebSocketTicketView.as_view(), name='ws-ticket'),
]
