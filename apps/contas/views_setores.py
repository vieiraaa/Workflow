from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from .forms_setores import SetorForm
from .models import Setor
from .permissoes import PermissaoMixin


class SetorListaView(PermissaoMixin, TemplateView):
    """Lista de setores (TEL-14, SET-02). Só Adm. Template `contas/setores.html`.

    Contexto (além do shell): `setores`: [{pk, nome, ativo, criado_em, url_editar}] (todos, por
    nome; poucos registros, sem paginação), `total`, `url_novo`.
    """

    acao_requerida = "setores.gerenciar"
    template_name = "contas/setores.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        setores = [
            {
                "pk": s.pk,
                "nome": s.nome,
                "ativo": s.ativo,
                "criado_em": s.criado_em,
                "url_editar": reverse("contas:setor_editar", kwargs={"pk": s.pk}),
            }
            for s in Setor.objects.order_by("nome")
        ]
        contexto.update(setores=setores, total=len(setores), url_novo=reverse("contas:setor_novo"))
        return contexto


def _renderizar(request, form, setor=None):
    contexto = {
        "form": form,
        "setor": setor,
        "url_lista": reverse("contas:setores"),
        "titulo": "Editar setor" if setor else "Novo setor",
    }
    modelo = "contas/setor_editar.html" if setor else "contas/setor_novo.html"
    return render(request, modelo, contexto)


class SetorNovoView(PermissaoMixin, View):
    """Criar setor (TEL-15, SET-02). Só Adm. Template `contas/setor_novo.html`.

    Contexto (além do shell): `form` (SetorForm: nome, ativo; erros em form.<campo>.errors),
    `setor` (None), `titulo` ("Novo setor"), `url_lista`. Erro → 200 com o form. Sucesso →
    redirect `contas:setores` + toast "Setor <nome> criado.". GET nunca grava.
    """

    acao_requerida = "setores.gerenciar"
    http_method_names = ["get", "post", "head", "options"]

    def get(self, request):
        return _renderizar(request, SetorForm(initial={"ativo": True}))

    def post(self, request):
        form = SetorForm(request.POST)
        if not form.is_valid():
            return _renderizar(request, form)
        setor = form.salvar()
        messages.success(request, f"Setor {setor.nome} criado.")
        return redirect("contas:setores")


class SetorEditarView(PermissaoMixin, View):
    """Renomear, ativar ou desativar setor (TEL-15, SET-02). Só Adm; pk inexistente → 404.
    Template `contas/setor_editar.html`, contexto de `SetorNovoView` com `setor` (Setor) e
    `titulo` "Editar setor".
    Sucesso → redirect `contas:setores` + toast "Setor <nome> atualizado.". Sem rota de exclusão.
    """

    acao_requerida = "setores.gerenciar"
    http_method_names = ["get", "post", "head", "options"]

    def get(self, request, pk):
        setor = get_object_or_404(Setor, pk=pk)
        form = SetorForm(initial=SetorForm.valores_iniciais(setor), instance=setor)
        return _renderizar(request, form, setor)

    def post(self, request, pk):
        setor = get_object_or_404(Setor, pk=pk)
        form = SetorForm(request.POST, instance=setor)
        if not form.is_valid():
            return _renderizar(request, form, setor)
        form.salvar()
        messages.success(request, f"Setor {setor.nome} atualizado.")
        return redirect("contas:setores")
