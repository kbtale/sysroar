import uuid
from django.contrib.auth.models import AbstractUser
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from .managers import TenantManager, UnscopedManager


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
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='users',
        null=True,
        blank=True,
    )

    class Meta:
        db_table = 'auth_user'

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
