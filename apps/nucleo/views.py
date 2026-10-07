from django.shortcuts import render


def erro_403(request, exception=None):
    """TEL-10: tela de erro do produto (shell) para quem não tem permissão (PRM-02)."""
    return render(request, "erros/403.html", status=403)


def erro_404(request, exception=None):
    """TEL-11: tela de erro do produto (shell) para rota ou objeto inexistente (PRM-03)."""
    return render(request, "erros/404.html", status=404)
