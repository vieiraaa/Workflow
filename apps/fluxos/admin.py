from django.contrib import admin

from .models import Fluxo


@admin.register(Fluxo)
class FluxoAdmin(admin.ModelAdmin):
    list_display = ("nome", "dono", "status", "atualizado_em")
    list_filter = ("status",)
    search_fields = ("nome", "descricao", "dono__email")
    raw_id_fields = ("dono",)
