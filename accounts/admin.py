from django.contrib import admin
from .models import Company, User


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
