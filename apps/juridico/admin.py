from django.contrib import admin

from .models import Carteira, ConfigCadastro, Envio, ItemEnvio, Processo


@admin.register(Carteira)
class CarteiraAdmin(admin.ModelAdmin):
    list_display = ("nome", "empresa", "ativa")
    search_fields = ("nome", "empresa")
    list_filter = ("ativa",)


@admin.register(ConfigCadastro)
class ConfigCadastroAdmin(admin.ModelAdmin):
    list_display = ("dify_url", "dify_credencial", "datajud_credencial")
    search_fields = ("dify_url",)
    list_filter = ("setores_com_acesso",)


@admin.register(Processo)
class ProcessoAdmin(admin.ModelAdmin):
    list_display = ("numero", "status", "carteira", "adverso_nome", "criado_via", "excluido_em")
    search_fields = ("numero", "numero_digitos", "adverso_nome")
    list_filter = ("status", "criado_via", "carteira", "cnj_validacao")
    raw_id_fields = ("criado_por", "excluido_por", "atualizado_por", "cadastrado_espaider_por")

    def get_queryset(self, request):
        return Processo.todos.all()


@admin.register(Envio)
class EnvioAdmin(admin.ModelAdmin):
    list_display = ("pk", "origem", "enviado_por", "criado_em", "terminado_em")
    search_fields = ("enviado_por__email",)
    list_filter = ("origem",)
    raw_id_fields = ("enviado_por",)


@admin.register(ItemEnvio)
class ItemEnvioAdmin(admin.ModelAdmin):
    list_display = ("pk", "envio", "nome_arquivo", "status", "etapa_erro", "resolvido")
    search_fields = ("nome_arquivo", "numero_informado", "sha256")
    list_filter = ("status", "etapa_erro", "resolvido")
    raw_id_fields = ("envio", "processo", "duplicado_de")
    exclude = ("resposta_ia",)
