"""Context processor global: o shell (menu, nome e papel) que todo template recebe (PRM-05/06)."""

from django.conf import settings
from django.urls import NoReverseMatch, reverse

from apps.contas.permissoes import nome_do_papel, papel_de, pode
from apps.nucleo import easteregg

# (chave, rótulo, rota, ícone Lucide, namespace da rota, ação que libera o item). Ordem = menu.
ITENS_MENU = [
    ("inicio", "Início", "inicio", "house", "", "inicio.ver"),
    ("funcoes", "Funções", "funcoes:catalogo", "square-function", "funcoes", "funcoes.ver"),
    ("fluxos", "Fluxos", "fluxos:lista", "workflow", "fluxos", "fluxos.ver"),
    ("execucoes", "Execuções", "execucoes:lista", "clock", "execucoes", "execucoes.ver"),
    (
        "juridico",
        "Cadastro de processos",
        "juridico:painel",
        "scale",
        "juridico",
        "cadastro.ver",
        "Jurídico",
    ),
    (
        "cslog",
        "CSLOG",
        "juridico:cslog",
        "file-spreadsheet",
        "juridico",
        "cadastro.ver",
        "Jurídico",
    ),
    (
        "usuarios",
        "Usuários",
        "contas:usuarios",
        "users",
        "contas",
        "usuarios.gerenciar",
        "Administração",
    ),
    (
        "setores",
        "Setores",
        "contas:setores",
        "layers",
        "contas",
        "setores.gerenciar",
        "Administração",
    ),
    (
        "simular",
        "Simular usuário",
        "contas:simular",
        "scan-eye",
        "contas",
        "usuarios.simular",
        "Administração",
    ),
    (
        "credenciais",
        "Credenciais",
        "credenciais:lista",
        "key-round",
        "credenciais",
        "credenciais.gerenciar",
        "Administração",
    ),
]
# Itens que dividem o namespace com outro: ativo só nas rotas com este prefixo.
PREFIXOS_ROTA = {
    "usuarios": "contas:usuario",
    "setores": "contas:setor",
    "simular": "contas:simula",
    "cslog": "juridico:cslog",
}
# ...e o item "dono" do namespace deixa de ficar ativo nessas rotas.
EXCETO_ROTA = {"juridico": "juridico:cslog"}


def _aprovacoes_pendentes():
    from apps.juridico.recebimentos import total_pendentes  # tardio: o núcleo carrega antes

    return total_pendentes()


# Número ao lado do item (notificação): (ação exigida, função). Aprovações é uma aba do painel
# (D-063): o número dos itens esperando aprovação fica em "Cadastro de processos".
CONTADORES = {"juridico": ("cadastro.aprovar", _aprovacoes_pendentes)}


def _contador(usuario, chave):
    if chave not in CONTADORES:
        return 0
    acao, funcao = CONTADORES[chave]
    return funcao() if pode(usuario, acao) else 0


def montar_menu(request):
    """Itens do menu que o papel pode ver e cujas rotas já existem."""
    if not request.user.is_authenticated:
        return []
    return itens_do_menu(request.user, getattr(request, "resolver_match", None))


def itens_do_menu(usuario, resolvida=None):
    """Menu de `usuario` (o perfil usa para listar as telas de outra pessoa, D-041)."""
    namespace = getattr(resolvida, "namespace", "")
    rota_atual = getattr(resolvida, "view_name", "")
    menu = []
    for chave, rotulo, rota, icone, ns, acao, *grupo in ITENS_MENU:
        if not pode(usuario, acao):
            continue
        try:
            url = reverse(rota)
        except NoReverseMatch:
            continue
        if chave == "inicio":
            ativo = rota_atual == "inicio"
        elif chave in PREFIXOS_ROTA:  # namespace dividido: marca só o próprio item
            ativo = rota_atual.startswith(PREFIXOS_ROTA[chave])
        else:
            ativo = namespace == ns and not (
                chave in EXCETO_ROTA and rota_atual.startswith(EXCETO_ROTA[chave])
            )
        menu.append(
            {
                "chave": chave,
                "rotulo": rotulo,
                "url": url,
                "icone": icone,
                "ativo": ativo,
                "grupo": grupo[0] if grupo else "",
                "contador": _contador(usuario, chave),
            }
        )
    return menu


def atalhos_do_usuario(request):
    return montar_menu(request)


def shell(request):
    """Variáveis: `menu` [{chave, rotulo, url, icone, ativo, grupo, contador}] (grupo: '',
    'Jurídico' ou 'Administração'; contador: número de pendências, 0 = sem), `usuario_nome`,
    `usuario_papel`,
    `sem_papel` (True para usuário logado sem papel), `usuario_logado` (o Usuario, para o avatar:
    nome_curto, iniciais, cor_avatar), `usuario_cargo` (cargo do AD; sem ele, o papel) e
    `url_meu_perfil` ('' sem papel), `pode_trocar_senha` (só no login local, sem AD). D-041.
    `easteregg_url`: '' fora da lista do easter egg (D-045).
    `simulacao`: None, ou {nome, papel, url_encerrar} enquanto o Adm simula um usuário (D-047);
    aí todo o resto do shell já é o do usuário simulado.
    `aviso_aprovacoes`: None, ou {total, url} se há itens do n8n esperando aprovação e o usuário
    pode aprovar (D-048; a Home mostra o aviso; a url é a aba Aprovações do painel, D-063)."""
    usuario = request.user
    logado = usuario.is_authenticated
    papel = nome_do_papel(usuario) if logado else ""
    sem_papel = logado and papel_de(usuario) is None
    simulacao = None
    if getattr(request, "usuario_real", None) is not None and logado:
        simulacao = {
            "nome": usuario.nome or usuario.email,
            "papel": papel or "Sem papel",
            "url_encerrar": reverse("contas:simulacao_encerrar"),
        }
    menu = montar_menu(request)
    aviso_aprovacoes = next(
        (
            {"total": i["contador"], "url": f"{i['url']}?aba=aprovacoes"}
            for i in menu
            if i["chave"] == "juridico" and i["contador"]
        ),
        None,
    )
    return {
        "simulacao": simulacao,
        "aviso_aprovacoes": aviso_aprovacoes,
        "menu": menu,
        "usuario_nome": (usuario.nome or usuario.email) if logado else "",
        "usuario_papel": papel,
        "sem_papel": sem_papel,
        "usuario_logado": usuario if logado else None,
        "usuario_cargo": (usuario.cargo or papel) if logado else "",
        "url_meu_perfil": reverse("contas:meu_perfil") if logado and not sem_papel else "",
        "pode_trocar_senha": logado and not sem_papel and not settings.LOGIN_AD,
        "easteregg_url": reverse("easteregg_video")
        if logado and easteregg.liberado(usuario)
        else "",
    }
