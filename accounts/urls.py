from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token
from .views import WebSocketTicketView

app_name = 'accounts'

urlpatterns = [
    path('auth/login/', obtain_auth_token, name='user-login'),
    path('auth/ticket/', WebSocketTicketView.as_view(), name='ws-ticket'),
]
