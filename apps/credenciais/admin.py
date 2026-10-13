from django.contrib import admin

from .models import Credencial


@admin.register(Credencial)
class CredencialAdmin(admin.ModelAdmin):
    """O valor cifrado nunca aparece (nem cifrado): só metadados."""

    list_display = ("nome", "tipo", "setor", "criado_por", "atualizado_em")
    search_fields = ("nome",)
    list_filter = ("tipo", "setor")
    exclude = ("dados_cifrados",)
    readonly_fields = ("criado_por", "atualizado_em")

    def has_add_permission(self, request):
        return False  # criar só pela tela (que cifra o valor)
