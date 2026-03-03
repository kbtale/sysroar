from django.db import models
from .middleware import get_current_company_id

class TenantManager(models.Manager):
    """
    Automatically filters querysets by the authenticated user's company.
    If no company_id is found in the current thread (e.g., during tests or 
    background system tasks that haven't explicitly set it), it returns all records.
    """
    def get_queryset(self):
        queryset = super().get_queryset()
        company_id = get_current_company_id()
        if company_id:
            return queryset.filter(company_id=company_id)
        return queryset
