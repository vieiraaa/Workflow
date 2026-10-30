from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View

from . import simulacao
from .models import Usuario
from .permissoes import PermissaoMixin, pode
from .views_usuarios import UsuarioListaView


class SimularListaView(UsuarioListaView):
    """Simular usuário (D-047): escolher quem simular. Só Adm. Template `contas/simular.html`.

    Mesma busca, filtros, ordenação e paginação da lista de Usuários (TEL-02, ver o contexto de
    UsuarioListaView). Cada linha de `usuarios` ganha `url_simular` (alvo do POST que inicia a
    simulação; "" para o próprio Adm e para inativos, que não podem ser simulados).
    """

    acao_requerida = "usuarios.simular"
    template_name = "contas/simular.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        for linha in contexto["usuarios"]:
            simulavel = linha["ativo"] and linha["pk"] != self.request.user.pk
            linha["url_simular"] = (
                reverse("contas:simular_iniciar", kwargs={"pk": linha["pk"]}) if simulavel else ""
            )
        return contexto


class SimularIniciarView(PermissaoMixin, View):
    """POST: passa a ver o sistema como o usuário `pk` (só leitura) e vai para a Home dele."""

    acao_requerida = "usuarios.simular"

    def post(self, request, pk):
        alvo = get_object_or_404(Usuario, pk=pk)
        if not simulacao.pode_simular(request.user, alvo):
            messages.error(request, "Não dá para simular um usuário inativo nem você mesmo.")
            return redirect("contas:simular")
        simulacao.iniciar(request, alvo)
        messages.info(
            request,
            f"Você está vendo o sistema como {alvo.nome_curto}. Nada pode ser alterado.",
        )
        return redirect("inicio")


class SimulacaoEncerrarView(LoginRequiredMixin, View):
    """POST: encerra a simulação e volta para a tela de Simular usuário (ou a Home)."""

    def post(self, request):
        if simulacao.encerrar(request):
            messages.success(request, "Simulação encerrada.")
        return redirect("contas:simular" if pode(request.user, "usuarios.simular") else "inicio")
