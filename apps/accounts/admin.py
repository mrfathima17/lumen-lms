from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class LumenUserAdmin(UserAdmin):
    list_display = ("username", "get_full_name", "email", "role", "index_number", "is_active")
    list_filter = ("role", "is_active", "faculty")
    search_fields = ("username", "first_name", "last_name", "email", "index_number")
    fieldsets = UserAdmin.fieldsets + (("Lumen", {"fields": ("role", "index_number", "faculty", "must_change_password")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (("Lumen", {"fields": ("role", "index_number", "faculty", "must_change_password")}),)
