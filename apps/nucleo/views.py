from django.http import HttpResponseServerError
from django.shortcuts import render
from django.template.loader import render_to_string


def erro_403(request, exception=None):
    """TEL-10: tela de erro do produto (shell) para quem não tem permissão (PRM-02)."""
    return render(request, "erros/403.html", status=403)


def erro_404(request, exception=None):
    """TEL-11: tela de erro do produto (shell) para rota ou objeto inexistente (PRM-03)."""
    return render(request, "erros/404.html", status=404)


FALLBACK_500 = (
    '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Erro interno</title>'
    "<body><h1>Algo deu errado</h1><p>Não foi possível concluir a operação. "
    "Tente novamente em instantes.</p></body></html>"
)


def erro_500(request):
    """Página de erro interno do produto (sem shell). Não usa banco nem context processors:
    renderiza `erros/500.html` SEM `request`, e cai num HTML mínimo se o template falhar.
    """
    try:
        corpo = render_to_string("erros/500.html")
    except Exception:  # noqa: BLE001 - o handler de erro nunca pode falhar
        corpo = FALLBACK_500
    return HttpResponseServerError(corpo)
