from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from apps.contas.permissoes import papel_de
from apps.nucleo import listagem
from apps.nucleo.entrada import limpar_texto

from . import cofre
from .forms import CredencialForm
from .models import Credencial


class SoAdmMixin(LoginRequiredMixin):
    """CRD-01: gestão só do Adm (TI no M7). Anônimo → login; outro papel → 403."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if papel_de(request.user) != "adm":
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def _urls(credencial):
    chave = {"pk": credencial.pk}
    return reverse("credenciais:editar", kwargs=chave), reverse("credenciais:excluir", kwargs=chave)


class CredencialListaView(SoAdmMixin, TemplateView):
    """Lista de credenciais (CRD-01). Só Adm. Template `credenciais/lista.html`.

    Querystring: `q` (nome), `pagina` (25 por página). O valor NUNCA aparece (nem cifrado).

    Contexto (além do shell): `credenciais` [{pk, nome, tipo, tipo_rotulo, setor_nome ('' = global),
    atualizado_em, url_editar, url_excluir}], `page_obj`, `consulta`, `q`, `total`, `url_nova`,
    `pode_criar`, `pode_excluir` (True), `chave_ausente` (sem CREDENCIAIS_CHAVE no servidor).
    """

    template_name = "credenciais/lista.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        q = limpar_texto(self.request.GET.get("q", ""))
        qs = Credencial.objects.select_related("setor").order_by("nome")
        if q:
            qs = qs.filter(Q(nome__icontains=q))
        paginator = Paginator(qs, listagem.POR_PAGINA)
        pagina = listagem.pagina_valida(paginator, self.request.GET.get("pagina", 1))
        base = listagem.consulta({"q": q}, pagina="")
        linhas = []
        for c in pagina.object_list:
            url_editar, url_excluir = _urls(c)
            linhas.append(
                {
                    "pk": c.pk,
                    "nome": c.nome,
                    "tipo": c.tipo,
                    "tipo_rotulo": c.tipo_rotulo,
                    "setor_nome": c.setor.nome if c.setor_id else "",
                    "atualizado_em": c.atualizado_em,
                    "url_editar": url_editar,
                    "url_excluir": url_excluir,
                }
            )
        contexto.update(
            credenciais=linhas,
            page_obj=pagina,
            consulta=base + "&" if base else "",
            q=q,
            total=paginator.count,
            url_nova=reverse("credenciais:nova"),
            pode_criar=True,
            pode_excluir=True,
            chave_ausente=not cofre.chave_configurada(),
        )
        return contexto


def _renderizar(request, form, credencial=None, status=200):
    contexto = {
        "form": form,
        "credencial": credencial,
        "chave_ausente": not cofre.chave_configurada(),
        "url_lista": reverse("credenciais:lista"),
        "titulo": "Editar credencial" if credencial else "Nova credencial",
    }
    return render(request, "credenciais/form.html", contexto, status=status)


class CredencialNovaView(SoAdmMixin, View):
    """Criar credencial (CRD-01, MV2-18 C3). Só Adm. Template `credenciais/form.html`.

    Contexto (além do shell): `form` (CredencialForm; erros em form.<campo>.errors e
    form.non_field_errors), `credencial` (None), `chave_ausente`, `url_lista`, `titulo`. Erro →
    200 com o form (sem chave: erro "chave" e nada salvo). Sucesso → redirect `credenciais:lista` +
    toast "Credencial <nome> salva.".
    """

    http_method_names = ["get", "post", "head", "options"]

    def get(self, request):
        return _renderizar(request, CredencialForm(initial={"tipo": Credencial.BEARER}))

    def post(self, request):
        form = CredencialForm(request.POST)
        if not form.is_valid():
            return _renderizar(request, form)
        credencial = form.salvar(request.user)
        messages.success(request, f"Credencial {credencial.nome} salva.")
        return redirect("credenciais:lista")


class CredencialEditarView(SoAdmMixin, View):
    """Editar credencial (CRD-01). Só Adm. Mesmo template e contexto da criação, com `credencial`.

    O campo `valor` vem sempre vazio ("manter atual"); vazio no POST mantém o valor salvo.
    """

    http_method_names = ["get", "post", "head", "options"]

    def _dados_atuais(self, credencial):
        try:
            return credencial.dados()
        except cofre.ErroCofre:
            return {}

    def get(self, request, pk):
        credencial = get_object_or_404(Credencial, pk=pk)
        atuais = self._dados_atuais(credencial)
        inicial = {
            "nome": credencial.nome,
            "tipo": credencial.tipo,
            "setor": str(credencial.setor_id or ""),
            "usuario": atuais.get("usuario", ""),
            "header_nome": atuais.get("header_nome", ""),
            "host": atuais.get("host", ""),
            "porta": atuais.get("porta"),
            "tls": atuais.get("tls", False),
        }
        form = CredencialForm(initial=inicial, instance=credencial, dados_atuais=atuais)
        return _renderizar(request, form, credencial)

    def post(self, request, pk):
        credencial = get_object_or_404(Credencial, pk=pk)
        atuais = self._dados_atuais(credencial)
        form = CredencialForm(request.POST, instance=credencial, dados_atuais=atuais)
        if not form.is_valid():
            return _renderizar(request, form, credencial)
        form.salvar(request.user)
        messages.success(request, f"Credencial {form.instance.nome} salva.")
        return redirect("credenciais:lista")


class CredencialExcluirView(SoAdmMixin, View):
    """Excluir credencial. Só POST; Adm. Sucesso → redirect `credenciais:lista` + toast
    "Credencial <nome> excluída."."""

    http_method_names = ["post", "options"]

    def post(self, request, pk):
        credencial = get_object_or_404(Credencial, pk=pk)
        nome = credencial.nome
        credencial.delete()
        messages.success(request, f"Credencial {nome} excluída.")
        return redirect("credenciais:lista")
