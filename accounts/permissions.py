from rest_framework.permissions import SAFE_METHODS, BasePermission
from accounts.models import User


def _is_human_user(user) -> bool:
    return bool(user and user.is_authenticated and not getattr(user, 'is_agent', False))


class IsInstanceAdmin(BasePermission):
    def has_permission(self, request, view):
        return _is_human_user(request.user) and bool(request.user.is_superuser)


class IsCompanyViewer(BasePermission):
    def has_permission(self, request, view):
        return _is_human_user(request.user) and request.user.has_min_role(User.ROLE_VIEWER)


class IsCompanyMember(BasePermission):
    def has_permission(self, request, view):
        return _is_human_user(request.user) and request.user.has_min_role(User.ROLE_MEMBER)


class IsCompanyAdmin(BasePermission):
    def has_permission(self, request, view):
        return _is_human_user(request.user) and request.user.has_min_role(User.ROLE_ADMIN)


class IsCompanyOwner(BasePermission):
    def has_permission(self, request, view):
        return _is_human_user(request.user) and request.user.has_min_role(User.ROLE_OWNER)


class ReadOnlyOrCompanyMember(BasePermission):
    def has_permission(self, request, view):
        if not _is_human_user(request.user):
            return False
        if request.method in SAFE_METHODS:
            return request.user.has_min_role(User.ROLE_VIEWER)
        return request.user.has_min_role(User.ROLE_MEMBER)
