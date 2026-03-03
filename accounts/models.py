import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser


class Company(models.Model):
    """
    The Tenant root. All data in SysRoar belongs to a Company.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Companies"

    def __str__(self):
        return self.name


class User(AbstractUser):
    """
    Custom User model strictly tied to a Company (Tenant).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company, 
        on_delete=models.CASCADE, 
        related_name='users',
        null=True, # Allow null for initial system setup/superusers
        blank=True
    )

    class Meta:
        db_table = 'auth_user'

    def __str__(self):
        return f"{self.username} ({self.company.name if self.company else 'System'})"


class TenantModel(models.Model):
    """
    Abstract base class for all models that must be logically isolated by Company.
    """
    company = models.ForeignKey(
        'accounts.Company', 
        on_delete=models.CASCADE,
        related_name="%(class)s_data"
    )

    class Meta:
        abstract = True
