from django.contrib import admin

from .models import Funcao


@admin.register(Funcao)
class FuncaoAdmin(admin.ModelAdmin):
    list_display = ("nome", "fluxo", "versao", "liberar_para", "ativa", "publicada_em")
    list_filter = ("ativa", "liberar_para")
    search_fields = ("nome", "descricao")
    raw_id_fields = ("fluxo", "publicada_por", "criada_por")
