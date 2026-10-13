from django.views.generic import TemplateView

from apps.contas.permissoes import PermissaoMixin


class CatalogoView(PermissaoMixin, TemplateView):
    acao_requerida = "funcoes.ver"
    template_name = "funcoes/catalogo.html"
