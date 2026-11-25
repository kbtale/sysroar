class TenantScopedViewSetMixin:
    def get_queryset(self):
        queryset = super().get_queryset()
        user = getattr(self.request, 'user', None)
        company_id = getattr(user, 'company_id', None) if user and user.is_authenticated else None
        if not company_id:
            return queryset.none()
        return queryset.filter(company_id=company_id)
