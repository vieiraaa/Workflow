"""Context processor global: o shell (menu, nome e papel) que todo template recebe (PRM-05/06)."""

from django.urls import NoReverseMatch, reverse

from apps.contas.permissoes import nome_do_papel, papel_de, pode

# (chave, rótulo, rota, ícone Lucide, namespace da rota, ação que libera o item). Ordem = menu.
ITENS_MENU = [
    ("fluxos", "Fluxos", "fluxos:lista", "workflow", "fluxos", "fluxos.ver"),
    ("execucoes", "Execuções", "execucoes:lista", "clock", "execucoes", "execucoes.ver"),
    ("usuarios", "Usuários", "contas:usuarios", "users", "contas", "usuarios.gerenciar"),
]


def montar_menu(request):
    """Itens do menu que o papel pode ver e cujas rotas já existem."""
    if not request.user.is_authenticated:
        return []
    namespace = getattr(getattr(request, "resolver_match", None), "namespace", "")
    menu = []
    for chave, rotulo, rota, icone, ns, acao in ITENS_MENU:
        if not pode(request.user, acao):
            continue
        try:
            url = reverse(rota)
        except NoReverseMatch:
            continue
        menu.append(
            {"chave": chave, "rotulo": rotulo, "url": url, "icone": icone, "ativo": namespace == ns}
        )
    return menu


def atalhos_do_usuario(request):
    return montar_menu(request)


def shell(request):
    """Variáveis: `menu` [{chave, rotulo, url, icone, ativo}], `usuario_nome`, `usuario_papel`,
    `sem_papel` (True para usuário logado sem papel)."""
    logado = request.user.is_authenticated
    return {
        "menu": montar_menu(request),
        "usuario_nome": (request.user.nome or request.user.email) if logado else "",
        "usuario_papel": nome_do_papel(request.user) if logado else "",
        "sem_papel": logado and papel_de(request.user) is None,
    }
