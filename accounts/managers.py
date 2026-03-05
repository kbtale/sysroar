from django.db import models
from .middleware import get_current_company_id

class UnscopedManager(models.Manager):
    """Unfiltered manager for system-level queries (Celery tasks, management commands)."""
    pass

class TenantManager(models.Manager):
    """
    Automatically filters querysets by the authenticated user's company.
    Returns an empty queryset when no company_id is set (fail-closed).
    Use `Model.unscoped.all()` for legitimate system-wide queries.
    """
    def get_queryset(self):
        queryset = super().get_queryset()
        company_id = get_current_company_id()
        if company_id:
            return queryset.filter(company_id=company_id)
        return queryset.none()
