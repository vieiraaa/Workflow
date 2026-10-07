from django.contrib import admin

from .models import Execucao, ExecucaoNo


class ExecucaoNoInline(admin.TabularInline):
    model = ExecucaoNo
    extra = 0
    can_delete = False
    readonly_fields = [f.name for f in ExecucaoNo._meta.fields if f.name != "id"]


@admin.register(Execucao)
class ExecucaoAdmin(admin.ModelAdmin):
    list_display = ("fluxo_nome", "executado_por", "status", "iniciada_em", "finalizada_em")
    list_filter = ("status",)
    search_fields = ("fluxo_nome", "executado_por__email")
    raw_id_fields = ("fluxo", "executado_por")
    inlines = [ExecucaoNoInline]


@admin.register(ExecucaoNo)
class ExecucaoNoAdmin(admin.ModelAdmin):
    list_display = ("execucao", "ordem", "no_titulo", "no_tipo", "status", "duracao_ms")
    list_filter = ("status", "no_tipo")
    search_fields = ("no_titulo", "execucao__fluxo_nome")
    raw_id_fields = ("execucao",)
