from django.contrib import admin

from .models import AllowedNetwork, AuditLog, SiteSettings


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AllowedNetwork)
class AllowedNetworkAdmin(admin.ModelAdmin):
    list_display = ("name", "cidr", "scope", "is_active")
    list_filter = ("scope", "is_active")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "target", "ip_address")
    list_filter = ("action",)
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False
