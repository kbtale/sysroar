from django.contrib import admin
from .models import Company, User


class TenantAwareModelAdmin(admin.ModelAdmin):
    def get_queryset(self, request):
        if request.user.is_superuser:
            return self.model.unscoped.get_queryset()
        company_id = getattr(request.user, 'company_id', None)
        if not company_id:
            return self.model.unscoped.none()
        return self.model.unscoped.filter(company_id=company_id)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        related_model = db_field.remote_field.model
        if hasattr(related_model, 'unscoped'):
            if request.user.is_superuser:
                kwargs['queryset'] = related_model.unscoped.all()
            else:
                company_id = getattr(request.user, 'company_id', None)
                kwargs['queryset'] = (
                    related_model.unscoped.filter(company_id=company_id)
                    if company_id
                    else related_model.unscoped.none()
                )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'id', 'created_at')
    search_fields = ('name',)
    readonly_fields = ('id', 'created_at')


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'company', 'is_active', 'is_staff')
    list_filter = ('is_active', 'is_staff', 'company')
    search_fields = ('username', 'email')
