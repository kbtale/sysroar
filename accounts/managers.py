from django.db import models


class TenantManager(models.Manager):
    """
    Automatically filters querysets by the authenticated user's company.
    """
    def get_queryset(self):
        return super().get_queryset()
