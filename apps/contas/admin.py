from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Usuario


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    list_display = ("email", "nome", "is_active", "is_staff", "criado_em")
    list_filter = ("is_active", "is_staff", "groups")
    search_fields = ("email", "nome")
    ordering = ("email",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dados", {"fields": ("nome",)}),
        ("Acesso", {"fields": ("is_active", "is_staff", "is_superuser", "groups")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "nome", "password1", "password2")}),
    )
