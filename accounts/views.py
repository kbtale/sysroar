from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .authentication import ticket_manager


def serialize_user(user) -> dict:
    company = getattr(user, 'company', None)
    return {
        'id': str(user.id),
        'username': user.username,
        'email': user.email,
        'company_id': str(user.company_id) if user.company_id else None,
        'company_name': company.name if company else None,
        'is_superuser': bool(user.is_superuser),
    }


@method_decorator(ensure_csrf_cookie, name='dispatch')
class CsrfTokenView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'csrfToken': get_token(request)}, status=status.HTTP_200_OK)


class SessionLoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        username = (request.data.get('username') or '').strip()
        password = request.data.get('password') or ''
        if not username or not password:
            return Response(
                {'error': 'Username and password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = authenticate(request=request, username=username, password=password)
        if user is None or not user.is_active:
            return Response(
                {'error': 'Invalid credentials.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        login(request, user)
        return Response({'user': serialize_user(user)}, status=status.HTTP_200_OK)


class SessionLogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutAllView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        request.user.invalidate_all_sessions()
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurrentUserView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({'user': serialize_user(request.user)}, status=status.HTTP_200_OK)


class WebSocketTicketView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ticket = ticket_manager.create_ticket(
            str(request.user.id),
            session_epoch=getattr(request.user, 'session_epoch', None),
        )
        return Response({'ticket': ticket}, status=status.HTTP_201_CREATED)
