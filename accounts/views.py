import logging
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.core.mail import send_mail
from django.db import transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from .authentication import ticket_manager
from .mixins import TenantScopedViewSetMixin
from .models import Company, CompanyInvite, User
from .permissions import IsCompanyAdmin, IsInstanceAdmin
from .throttling import LoginRateThrottle
from monitoring.audit import record_audit_event
from .serializers import (
    AcceptInviteSerializer,
    CompanyInviteCreateSerializer,
    CompanyInviteSerializer,
    CompanyMemberSerializer,
    CompanySerializer,
    OpenRegistrationSerializer,
    SetupWizardSerializer,
)

logger = logging.getLogger(__name__)
UserModel = get_user_model()


def serialize_user(user) -> dict:
    company = getattr(user, 'company', None)
    return {
        'id': str(user.id),
        'username': user.username,
        'email': user.email,
        'role': getattr(user, 'role', User.ROLE_MEMBER),
        'company_id': str(user.company_id) if user.company_id else None,
        'company_name': company.name if company else None,
        'is_superuser': bool(user.is_superuser),
    }


def _build_invite_url(raw_token: str) -> str:
    frontend = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173').rstrip('/')
    return f'{frontend}/accept-invite?token={raw_token}'


def _smtp_is_configured() -> bool:
    backend = getattr(settings, 'EMAIL_BACKEND', '')
    if 'console' in backend or 'dummy' in backend:
        return False
    return bool(getattr(settings, 'EMAIL_HOST', ''))


@method_decorator(ensure_csrf_cookie, name='dispatch')
class CsrfTokenView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({'csrfToken': get_token(request)}, status=status.HTTP_200_OK)


def axes_lockout_response(request, credentials=None, *args, **kwargs):
    return JsonResponse(
        {'error': 'Account temporarily locked due to too many failed login attempts.'},
        status=429,
    )


class SessionLoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        username = (request.data.get('username') or '').strip()
        password = request.data.get('password') or ''
        if not username or not password:
            return Response(
                {'error': 'Username and password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        django_request = getattr(request, '_request', request)
        user = authenticate(request=django_request, username=username, password=password)
        if getattr(django_request, 'axes_locked_out', False):
            return Response(
                {'error': 'Account temporarily locked due to too many failed login attempts.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
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


class SetupStatusView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                'needs_setup': not UserModel.objects.exists(),
                'open_registration': bool(getattr(settings, 'OPEN_REGISTRATION', False)),
            },
            status=status.HTTP_200_OK,
        )


class SetupWizardView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SetupWizardSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            if UserModel.objects.select_for_update().exists():
                return Response(
                    {'error': 'Initial setup has already been completed.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            company = Company.objects.create(name=data['company_name'].strip())
            user = UserModel.objects.create_superuser(
                username=data['username'].strip(),
                email=data['email'].strip().lower(),
                password=data['password'],
                company=company,
                role=User.ROLE_OWNER,
            )

        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return Response(
            {
                'user': serialize_user(user),
                'company': CompanySerializer(company).data,
            },
            status=status.HTTP_201_CREATED,
        )


class OpenRegistrationView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        if not getattr(settings, 'OPEN_REGISTRATION', False):
            return Response(
                {'error': 'Open registration is disabled on this instance.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = OpenRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            company = Company.objects.create(name=data['company_name'].strip())
            user = UserModel.objects.create_user(
                username=data['username'].strip(),
                email=data['email'].strip().lower(),
                password=data['password'],
                company=company,
                role=User.ROLE_OWNER,
            )

        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return Response(
            {
                'user': serialize_user(user),
                'company': CompanySerializer(company).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CompanyInviteViewSet(
    TenantScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = CompanyInvite.unscoped.all().order_by('-created_at', 'id')
    serializer_class = CompanyInviteSerializer
    permission_classes = [IsCompanyAdmin]

    def create(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if company is None:
            return Response({'error': 'Tenant company required.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = CompanyInviteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = serializer.validated_data['role']
        if role == User.ROLE_OWNER and not request.user.has_min_role(User.ROLE_OWNER):
            return Response(
                {'error': 'Only company owners can invite another owner.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        invite, raw_token = CompanyInvite.generate(
            company=company,
            email=serializer.validated_data['email'],
            role=role,
            invited_by=request.user,
            expires_in_hours=serializer.validated_data['expires_in_hours'],
        )
        invite_url = _build_invite_url(raw_token)
        email_sent = False
        if _smtp_is_configured():
            try:
                send_mail(
                    subject=f'You are invited to join {company.name} on SysRoar',
                    message=f'Accept your invitation using this link: {invite_url}',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[invite.email],
                    fail_silently=False,
                )
                email_sent = True
            except Exception as exc:
                logger.warning(f'Invite email dispatch failed for {invite.id}: {exc}')

        response_data = CompanyInviteSerializer(invite).data
        response_data['invite_url'] = invite_url
        response_data['token'] = raw_token
        response_data['email_sent'] = email_sent
        record_audit_event(
            request,
            action='invite.created',
            resource_type='company_invite',
            resource_id=str(invite.id),
            metadata={'email': invite.email, 'role': invite.role, 'prefix': invite.prefix},
        )
        return Response(response_data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        invite = self.get_object()
        invite.revoke()
        record_audit_event(
            request,
            action='invite.revoked',
            resource_type='company_invite',
            resource_id=str(invite.id),
            metadata={'email': invite.email, 'prefix': invite.prefix},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class AcceptInviteView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]

    def post(self, request):
        serializer = AcceptInviteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        raw_token = data['token'].strip()
        if '.' not in raw_token:
            return Response({'error': 'Invalid or expired invite token.'}, status=status.HTTP_400_BAD_REQUEST)

        prefix = raw_token.split('.', 1)[0]
        now = timezone.now()

        with transaction.atomic():
            invite = (
                CompanyInvite.unscoped.select_for_update()
                .select_related('company')
                .filter(prefix=prefix)
                .first()
            )
            if invite is None or not invite.verify(raw_token, now=now):
                return Response({'error': 'Invalid or expired invite token.'}, status=status.HTTP_400_BAD_REQUEST)

            user = UserModel.objects.create_user(
                username=data['username'].strip(),
                email=invite.email,
                password=data['password'],
                company=invite.company,
                role=invite.role,
            )
            invite.accepted_at = now
            invite.save(update_fields=['accepted_at'])

        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        return Response({'user': serialize_user(user)}, status=status.HTTP_201_CREATED)


class CompanyMemberViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CompanyMemberSerializer
    permission_classes = [IsCompanyAdmin]

    def get_queryset(self):
        company_id = getattr(self.request.user, 'company_id', None)
        if not company_id:
            return UserModel.objects.none()
        return UserModel.objects.filter(company_id=company_id).order_by('date_joined', 'id')

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        member = self.get_object()
        new_role = request.data.get('role', member.role)
        new_active = request.data.get('is_active', member.is_active)

        if (member.role == User.ROLE_OWNER or new_role == User.ROLE_OWNER) and not request.user.has_min_role(
            User.ROLE_OWNER
        ):
            return Response(
                {'error': 'Only company owners can assign or modify owner roles.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if member.role == User.ROLE_OWNER and (new_role != User.ROLE_OWNER or not new_active):
            other_owners = UserModel.objects.filter(
                company_id=member.company_id,
                role=User.ROLE_OWNER,
                is_active=True,
            ).exclude(pk=member.pk)
            if not other_owners.exists():
                return Response(
                    {'error': 'Company must retain at least one active owner.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer = self.get_serializer(member, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        if not member.is_active:
            member.invalidate_all_sessions()
        record_audit_event(
            request,
            action='member.updated',
            resource_type='user',
            resource_id=str(member.id),
            metadata={'username': member.username, 'role': member.role, 'is_active': member.is_active},
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class CompanyViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CompanySerializer

    def get_permissions(self):
        if self.action == 'create':
            return [IsInstanceAdmin()]
        if self.action in ('update', 'partial_update'):
            return [IsCompanyAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'is_agent', False):
            return Company.objects.none()
        if user.is_superuser:
            return Company.objects.all().order_by('created_at', 'id')
        if user.company_id:
            return Company.objects.filter(id=user.company_id)
        return Company.objects.none()

    def perform_update(self, serializer):
        company = serializer.save()
        record_audit_event(
            self.request,
            action='company.updated',
            resource_type='company',
            resource_id=str(company.id),
            metadata={'name': company.name, 'retention_days': company.retention_days},
            company_id=company.id,
        )
