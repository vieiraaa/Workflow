from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps.execucoes.models import Execucao
from apps.nucleo.contexto import itens_do_menu

from . import presenca
from .forms_perfil import PerfilAcessoForm, PerfilForm
from .forms_usuarios import UsuarioEditarForm
from .models import Usuario
from .permissoes import PermissaoMixin, escopo, nome_do_papel, pode

ATIVIDADE_MAX = 5


def _url_perfil(usuario):
    return reverse("contas:perfil", kwargs={"pk": usuario.pk})


def _perfis_visiveis(usuario):
    """perfis.ver é 'todos'; perfil de inativo, só quem gerencia usuários vê."""
    qs = escopo(usuario, Usuario.objects.select_related("setor"), "perfis.ver")
    return qs if pode(usuario, "usuarios.gerenciar") else qs.filter(is_active=True)


def _contexto(request, perfil, form_acesso=None):
    leitor = request.user
    gerencia = pode(leitor, "usuarios.gerenciar")
    atividade = (
        escopo(leitor, Execucao.objects, "execucoes.ver")
        .filter(executado_por=perfil)
        .order_by("-iniciada_em")[:ATIVIDADE_MAX]
    )
    if gerencia and form_acesso is None:
        form_acesso = PerfilAcessoForm(
            initial=UsuarioEditarForm.valores_iniciais(perfil), instance=perfil, editor=leitor
        )
    return {
        "perfil": perfil,
        "eh_proprio": perfil.pk == leitor.pk,
        "papel_rotulo": nome_do_papel(perfil)
        or ("Inativo" if not perfil.is_active else "Sem papel"),
        "online": perfil.is_active and presenca.online(perfil),
        "visto_em": presenca.visto_em(perfil),
        "responsabilidades": perfil.lista_responsabilidades,
        "atividade": [
            {
                "fluxo_nome": e.fluxo_nome,
                "status": e.status,
                "status_rotulo": e.get_status_display(),
                "iniciada_em": e.iniciada_em,
                "url": reverse("execucoes:detalhe", kwargs={"pk": e.pk}),
            }
            for e in atividade
        ],
        "pode_editar": perfil.is_active and pode(leitor, "perfis.editar", perfil),
        "url_editar": reverse("contas:perfil_editar", kwargs={"pk": perfil.pk}),
        "pode_gerenciar": gerencia,
        "form_acesso": form_acesso if gerencia else None,
        "url_acesso": reverse("contas:perfil_acesso", kwargs={"pk": perfil.pk}),
        "url_cadastro": reverse("contas:usuario_editar", kwargs={"pk": perfil.pk}),
        "telas": [{"rotulo": i["rotulo"], "icone": i["icone"]} for i in itens_do_menu(perfil)]
        if gerencia
        else [],
    }


class PerfilView(PermissaoMixin, View):
    """Perfil (D-041): `meu_perfil` (o próprio) ou `perfil` (pk). Template `contas/perfil.html`.
    Todo papel vê o perfil de qualquer colega ativo; inativo → 404, salvo para o Adm.

    Contexto (além do shell): `perfil` (Usuario: nome, nome_curto, iniciais, cor_avatar, cargo,
    bio, email, setor, criado_em), `eh_proprio`, `papel_rotulo`, `online` (bool), `visto_em`
    (datetime ou None), `responsabilidades` [str], `atividade` [{fluxo_nome, status, status_rotulo,
    iniciada_em, url}] (até 5, no escopo de execucoes.ver de quem LÊ), `pode_editar` + `url_editar`,
    `pode_gerenciar` (Adm) + `form_acesso` (PerfilAcessoForm: papel, setor, ativo; POST em
    `url_acesso`) + `url_cadastro` + `telas` [{rotulo, icone}] (o menu da pessoa).
    """

    acao_requerida = "perfis.ver"
    http_method_names = ["get", "head", "options"]

    def get(self, request, pk=None):
        perfil = get_object_or_404(_perfis_visiveis(request.user), pk=pk or request.user.pk)
        return render(request, "contas/perfil.html", _contexto(request, perfil))


class PerfilEditarView(PermissaoMixin, View):
    """Editar bio e responsabilidades (D-041). Template `contas/perfil_editar.html`.
    O próprio usuário ou o Adm; perfil fora do escopo de perfis.editar → 404 (PRM-03).

    Contexto (além do shell): `form` (PerfilForm: bio, responsabilidades), `perfil`,
    `url_perfil`. Sucesso → redirect para o perfil + toast "Perfil atualizado.".
    """

    acao_requerida = "perfis.editar"
    http_method_names = ["get", "post", "head", "options"]

    def _perfil(self, pk):
        return get_object_or_404(
            self.escopo_queryset(Usuario.objects.filter(is_active=True)), pk=pk
        )

    def _pagina(self, request, perfil, form):
        contexto = {"form": form, "perfil": perfil, "url_perfil": _url_perfil(perfil)}
        return render(request, "contas/perfil_editar.html", contexto)

    def get(self, request, pk):
        perfil = self._perfil(pk)
        form = PerfilForm(
            initial={"bio": perfil.bio, "responsabilidades": perfil.responsabilidades}
        )
        return self._pagina(request, perfil, form)

    def post(self, request, pk):
        perfil = self._perfil(pk)
        form = PerfilForm(request.POST)
        if not form.is_valid():
            return self._pagina(request, perfil, form)
        form.salvar(perfil)
        messages.success(request, "Perfil atualizado.")
        return redirect(_url_perfil(perfil))


class PerfilAcessoView(PermissaoMixin, View):
    """Alterar o acesso pelo perfil: papel, setor e ativo (D-041). Só POST, só Adm.

    Sucesso → redirect para o perfil + toast "Acesso de <nome> atualizado.". Erro → re-renderiza
    `contas/perfil.html` (200) com `form_acesso` e os erros por campo.
    """

    acao_requerida = "usuarios.gerenciar"
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        perfil = get_object_or_404(Usuario.objects.select_related("setor"), pk=pk)
        with transaction.atomic():
            form = PerfilAcessoForm(request.POST, instance=perfil, editor=request.user)
            if form.is_valid():
                form.salvar()
                messages.success(request, f"Acesso de {perfil.nome_curto} atualizado.")
                return redirect(_url_perfil(perfil))
        return render(request, "contas/perfil.html", _contexto(request, perfil, form_acesso=form))
