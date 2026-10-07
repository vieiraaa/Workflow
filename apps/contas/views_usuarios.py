from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from .forms_usuarios import (
    RedefinirSenhaForm,
    TrocarSenhaForm,
    UsuarioEditarForm,
    UsuarioNovoForm,
)
from .models import Usuario
from .permissoes import PermissaoMixin, papeis

POR_PAGINA = 25
ORDENS = {
    "nome": ("nome", "pk"),
    "email": ("email", "pk"),
    "criado_em": ("criado_em", "pk"),
}
ORDEM_PADRAO = "nome"


def _ordem_valida(valor):
    base = (valor or "").lstrip("-")
    return valor if base in ORDENS and valor.count("-") <= 1 else ORDEM_PADRAO


def _url_editar(usuario):
    return reverse("contas:usuario_editar", kwargs={"pk": usuario.pk})


class UsuarioListaView(PermissaoMixin, TemplateView):
    """Lista de usuários (TEL-02, USR-01..03). Só Adm. Template `contas/usuarios.html`.

    Querystring: `q`, `papel` (adm|coordenador|base), `ativo` (1|0), `ordem`
    (nome|email|criado_em, com `-` para decrescente), `pagina`. Valor inválido é ignorado.

    Contexto (além do shell):
    - `usuarios`: linhas da página, dicts {pk, nome, email, papel_id, papel_rotulo, ativo,
      criado_em, url_editar}; `page_obj` (Page, 25 por página) p/ `componentes/paginacao.html`
    - `consulta`: querystring dos filtros já codificada com "&" no fim (para a paginação)
    - `q`, `ordem` (str), `papel_atual` ("" = Todos), `ativo_atual` ("", "1" ou "0")
    - `filtros_papel`, `filtros_status`: opções {rotulo, url, ativo} (segmentado.html)
    - `ordenacoes`: {nome, email, criado_em} -> {url, sentido ('asc'|'desc'|'')} dos cabeçalhos
    - `total`: nº de usuários no filtro; `url_novo`: rota de criação
    """

    acao_requerida = "usuarios.gerenciar"
    template_name = "contas/usuarios.html"

    def _parametros(self):
        get = self.request.GET
        grupos_por_id = {p["id"]: p["grupo"] for p in papeis()}
        papel = get.get("papel", "")
        ativo = get.get("ativo", "")
        return {
            "q": get.get("q", "").strip()[:200],
            "papel": papel if papel in grupos_por_id else "",
            "ativo": ativo if ativo in ("1", "0") else "",
            "ordem": _ordem_valida(get.get("ordem", ORDEM_PADRAO)),
        }, grupos_por_id

    @staticmethod
    def _consulta(parametros, **trocas):
        valores = {**parametros, **trocas}
        itens = [
            (k, v) for k, v in valores.items() if v and not (k == "ordem" and v == ORDEM_PADRAO)
        ]
        return urlencode(itens)

    def _queryset(self, parametros, grupos_por_id):
        qs = Usuario.objects.prefetch_related("groups")
        if parametros["q"]:
            qs = qs.filter(Q(nome__icontains=parametros["q"]) | Q(email__icontains=parametros["q"]))
        if parametros["papel"]:
            qs = qs.filter(groups__name=grupos_por_id[parametros["papel"]])
        if parametros["ativo"]:
            qs = qs.filter(is_active=parametros["ativo"] == "1")
        ordem = parametros["ordem"]
        campos = [("-" + c if ordem.startswith("-") else c) for c in ORDENS[ordem.lstrip("-")]]
        return qs.order_by(*campos)

    def _pagina(self, paginator):
        try:
            numero = int(self.request.GET.get("pagina", 1))
        except TypeError, ValueError:
            numero = 1
        return paginator.get_page(min(max(numero, 1), paginator.num_pages))

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        parametros, grupos_por_id = self._parametros()
        paginator = Paginator(self._queryset(parametros, grupos_por_id), POR_PAGINA)
        pagina = self._pagina(paginator)
        por_grupo = {g: i for i, g in grupos_por_id.items()}
        rotulos = {p["id"]: p["nome"] for p in papeis()}
        linhas = []
        for usuario in pagina.object_list:
            ids = [por_grupo[g.name] for g in usuario.groups.all() if g.name in por_grupo]
            papel_id = ids[0] if len(ids) == 1 else ""
            linhas.append(
                {
                    "pk": usuario.pk,
                    "nome": usuario.nome,
                    "email": usuario.email,
                    "papel_id": papel_id,
                    "papel_rotulo": rotulos.get(papel_id, "Sem papel"),
                    "ativo": usuario.is_active,
                    "criado_em": usuario.criado_em,
                    "url_editar": _url_editar(usuario),
                }
            )

        def url(**trocas):
            consulta = self._consulta(parametros, **trocas)
            return f"?{consulta}" if consulta else "?"

        ordens = {}
        for campo in ORDENS:
            atual = parametros["ordem"]
            sentido = (
                ("desc" if atual.startswith("-") else "asc") if atual.lstrip("-") == campo else ""
            )
            proxima = f"-{campo}" if sentido == "asc" else campo
            ordens[campo] = {"url": url(ordem=proxima), "sentido": sentido}
        url_novo = reverse("contas:usuario_novo")
        contexto.update(
            usuarios=linhas,
            page_obj=pagina,
            consulta=(self._consulta(parametros, pagina="") + "&")
            if self._consulta(parametros)
            else "",
            q=parametros["q"],
            ordem=parametros["ordem"],
            papel_atual=parametros["papel"],
            ativo_atual=parametros["ativo"],
            filtros_papel=[
                {"rotulo": "Todos", "url": url(papel=""), "ativo": not parametros["papel"]}
            ]
            + [
                {
                    "rotulo": p["nome"],
                    "url": url(papel=p["id"]),
                    "ativo": parametros["papel"] == p["id"],
                }
                for p in papeis()
            ],
            filtros_status=[
                {"rotulo": "Todos", "url": url(ativo=""), "ativo": not parametros["ativo"]},
                {"rotulo": "Ativos", "url": url(ativo="1"), "ativo": parametros["ativo"] == "1"},
                {"rotulo": "Inativos", "url": url(ativo="0"), "ativo": parametros["ativo"] == "0"},
            ],
            ordenacoes=ordens,
            total=paginator.count,
            url_novo=url_novo,
        )
        return contexto


def _pagina_editar(request, usuario, form=None, form_senha=None, status=200):
    form = form or UsuarioEditarForm(
        initial=UsuarioEditarForm.valores_iniciais(usuario), instance=usuario, editor=request.user
    )
    form_senha = form_senha or RedefinirSenhaForm(instance=usuario)
    return render(
        request,
        "contas/usuario_editar.html",
        {
            "form": form,
            "form_senha": form_senha,
            "usuario_editado": usuario,
            "eh_proprio": usuario.pk == request.user.pk,
            "url_redefinir": reverse("contas:usuario_redefinir_senha", kwargs={"pk": usuario.pk}),
            "url_lista": reverse("contas:usuarios"),
        },
        status=status,
    )


class UsuarioNovoView(PermissaoMixin, View):
    """Criar usuário (TEL-03, USR-04/05/14). Só Adm. Template `contas/usuario_novo.html`.

    Contexto (além do shell): `form` (UsuarioNovoForm: campos nome, email, papel, senha,
    confirmacao; erros em form.<campo>.errors; papel tem as opções {id, nome} dos papéis),
    `url_lista`. Sucesso → redirect para `contas:usuarios` + toast "Usuário <nome> criado.".
    """

    acao_requerida = "usuarios.gerenciar"
    http_method_names = ["get", "post", "head", "options"]

    def _render(self, request, form, status=200):
        contexto = {"form": form, "url_lista": reverse("contas:usuarios")}
        return render(request, "contas/usuario_novo.html", contexto, status=status)

    def get(self, request):
        return self._render(request, UsuarioNovoForm())

    def post(self, request):
        form = UsuarioNovoForm(request.POST)
        if not form.is_valid():
            return self._render(request, form)
        usuario = form.salvar()
        messages.success(request, f"Usuário {usuario.nome} criado.")
        return redirect("contas:usuarios")


class UsuarioEditarView(PermissaoMixin, View):
    """Editar usuário e redefinir senha (TEL-09, USR-06/07/08). Só Adm. Template
    `contas/usuario_editar.html`; pk inexistente → 404.

    Contexto (além do shell): `form` (UsuarioEditarForm: nome, email, papel, ativo;
    erros de formulário em form.non_field_errors), `usuario_editado` (Usuario: nome, email,
    is_active), `eh_proprio` (bool), `form_senha` (RedefinirSenhaForm: nova_senha, confirmacao),
    `url_redefinir` (POST), `url_lista`. Sucesso → redirect para `contas:usuarios` + toast
    "Usuário <nome> atualizado.". Não há rota de exclusão (USR-09).
    """

    acao_requerida = "usuarios.gerenciar"
    http_method_names = ["get", "post", "head", "options"]

    def get(self, request, pk):
        return _pagina_editar(request, get_object_or_404(Usuario, pk=pk))

    def post(self, request, pk):
        usuario = get_object_or_404(Usuario, pk=pk)
        with transaction.atomic():
            form = UsuarioEditarForm(request.POST, instance=usuario, editor=request.user)
            if form.is_valid():
                form.salvar()
                messages.success(request, f"Usuário {usuario.nome} atualizado.")
                return redirect("contas:usuarios")
        return _pagina_editar(request, usuario, form=form)


class UsuarioRedefinirSenhaView(PermissaoMixin, View):
    """Redefinir a senha de um usuário (USR-06/13). Só POST, só Adm: `nova_senha`, `confirmacao`.

    Sucesso → redirect para `contas:usuario_editar` + toast "Senha de <nome> redefinida.".
    Erro → re-renderiza `contas/usuario_editar.html` (200) com `form_senha` com os erros.
    """

    acao_requerida = "usuarios.gerenciar"
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        usuario = get_object_or_404(Usuario, pk=pk)
        form = RedefinirSenhaForm(request.POST, instance=usuario)
        if not form.is_valid():
            return _pagina_editar(request, usuario, form_senha=form)
        form.salvar()
        if usuario.pk == request.user.pk:
            update_session_auth_hash(request, usuario)
        messages.success(request, f"Senha de {usuario.nome} redefinida.")
        return redirect("contas:usuario_editar", pk=usuario.pk)


class TrocarSenhaView(PermissaoMixin, View):
    """Trocar a própria senha (TEL-08, USR-10). Todos os papéis; sem papel → 403.
    Template `contas/trocar_senha.html`.

    Contexto (além do shell): `form` (TrocarSenhaForm: senha_atual, nova_senha, confirmacao;
    erros em form.<campo>.errors). Sucesso mantém a sessão → redirect para a própria tela +
    toast "Senha alterada.".
    """

    acao_requerida = "conta.trocar_senha"
    http_method_names = ["get", "post", "head", "options"]

    def get(self, request):
        return render(
            request, "contas/trocar_senha.html", {"form": TrocarSenhaForm(usuario=request.user)}
        )

    def post(self, request):
        form = TrocarSenhaForm(request.POST, usuario=request.user)
        if not form.is_valid():
            return render(request, "contas/trocar_senha.html", {"form": form})
        form.salvar()
        update_session_auth_hash(request, request.user)
        messages.success(request, "Senha alterada.")
        return redirect("contas:trocar_senha")
