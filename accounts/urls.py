from django.urls import path
from .views import WebSocketTicketView

app_name = 'accounts'

urlpatterns = [
    path('auth/ticket/', WebSocketTicketView.as_view(), name='ws-ticket'),
]
