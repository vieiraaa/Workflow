from django.views.generic import TemplateView

from apps.contas.permissoes import PermissaoMixin


class ExecucaoListaView(PermissaoMixin, TemplateView):
    """Histórico de execuções (TEL-06). PLACEHOLDER do M1: a lista real chega no M3.

    Template `execucoes/lista.html`; contexto: só o shell.
    """

    acao_requerida = "execucoes.ver"
    template_name = "execucoes/lista.html"
