import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F
from django.utils import timezone
from .managers import TenantManager, UnscopedManager


def hash_invite_token(raw_value: str) -> str:
    return hashlib.sha256(raw_value.encode('utf-8')).hexdigest()


class Company(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    retention_days = models.PositiveIntegerField(
        default=14,
        validators=[MinValueValidator(1), MaxValueValidator(365)],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Companies'

    def __str__(self):
        return self.name


class User(AbstractUser):
    ROLE_OWNER = 'owner'
    ROLE_ADMIN = 'admin'
    ROLE_MEMBER = 'member'
    ROLE_VIEWER = 'viewer'

    ROLE_CHOICES = [
        (ROLE_OWNER, 'Owner'),
        (ROLE_ADMIN, 'Admin'),
        (ROLE_MEMBER, 'Member'),
        (ROLE_VIEWER, 'Viewer'),
    ]

    ROLE_RANK = {
        ROLE_VIEWER: 1,
        ROLE_MEMBER: 2,
        ROLE_ADMIN: 3,
        ROLE_OWNER: 4,
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='users',
        null=True,
        blank=True,
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    session_epoch = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = 'auth_user'

    def has_min_role(self, min_role: str) -> bool:
        if self.is_superuser:
            return True
        if self.company_id is None:
            return False
        return self.ROLE_RANK.get(self.role, 0) >= self.ROLE_RANK[min_role]

    def invalidate_all_sessions(self):
        from rest_framework.authtoken.models import Token

        User.objects.filter(pk=self.pk).update(session_epoch=F('session_epoch') + 1)
        self.refresh_from_db(fields=['session_epoch'])
        Token.objects.filter(user=self).delete()

    def __str__(self):
        return f"{self.username} ({self.company.name if self.company else 'System'})"


class TenantModel(models.Model):
    company = models.ForeignKey(
        'accounts.Company',
        on_delete=models.CASCADE,
        related_name='%(class)s_data',
    )

    objects = TenantManager()
    unscoped = UnscopedManager()

    class Meta:
        abstract = True


class CompanyInvite(TenantModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=User.ROLE_CHOICES, default=User.ROLE_MEMBER)
    prefix = models.CharField(max_length=16, unique=True, db_index=True)
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_invites',
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @classmethod
    def generate(cls, company: Company, email: str, role: str, invited_by=None, expires_in_hours: int = 72):
        prefix = f'sri_{secrets.token_hex(4)}'
        secret_part = secrets.token_urlsafe(32)
        plaintext = f'{prefix}.{secret_part}'
        invite = cls.unscoped.create(
            company=company,
            email=email.strip().lower(),
            role=role,
            prefix=prefix,
            token_hash=hash_invite_token(plaintext),
            invited_by=invited_by,
            expires_at=timezone.now() + timedelta(hours=expires_in_hours),
        )
        return invite, plaintext

    def verify(self, plaintext: str, now=None) -> bool:
        now = now or timezone.now()
        if self.revoked_at is not None or self.accepted_at is not None:
            return False
        if now >= self.expires_at:
            return False
        return hmac.compare_digest(hash_invite_token(plaintext), self.token_hash)

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=['revoked_at'])

    def __str__(self):
        return f'Invite({self.email} -> {self.company_id} as {self.role})'
