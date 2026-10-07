from django.views.generic import TemplateView

from apps.contas.permissoes import PermissaoMixin


class FluxoListaView(PermissaoMixin, TemplateView):
    """Lista de fluxos (TEL-04). PLACEHOLDER do M1: a lista real chega no M2.

    Template `fluxos/lista.html`; contexto: só o shell.
    """

    acao_requerida = "fluxos.ver"
    template_name = "fluxos/lista.html"
