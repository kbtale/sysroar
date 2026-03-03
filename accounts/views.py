from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from .authentication import ticket_manager


class WebSocketTicketView(APIView):
    """
    Issues a one-time-use ticket for WebSocket authentication.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ticket = ticket_manager.create_ticket(str(request.user.id))
        return Response({'ticket': ticket}, status=status.HTTP_201_CREATED)
