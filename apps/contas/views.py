from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.views.generic import TemplateView

from apps.execucoes.painel import painel_ou_erro

from .forms import LoginForm
from .permissoes import papel_de


class LoginView(auth_views.LoginView):
    """Login (TEL-01). Template `registration/login.html`.

    Contexto: `form` (campos `username` = e-mail e `password`; erros em
    `form.non_field_errors` / `form.<campo>.errors`), `next`.
    """

    form_class = LoginForm
    template_name = "registration/login.html"
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    """Logout: só POST (SEG-15); GET devolve 405."""

    http_method_names = ["post", "options"]


class InicioView(LoginRequiredMixin, TemplateView):
    """Home (TEL-13/16/17, HOM-01..09; PRM-07). Template `inicio/inicio.html`.

    Sem papel → 403 do produto. `?periodo=24h|7d|30d|6m|1a` (padrão 7d; inválido → padrão).
    Tudo no escopo do papel (SET-06); contexto montado por `apps.execucoes.painel`.

    Contexto (além do shell): `periodo_rotulo`; `periodos` [{rotulo, url, ativo}]; `sem_dados`
    (nada no escopo → estado vazio); `sem_dados_periodo`; `erro_carregar`; `indicadores`
    [{chave, rotulo, valor (texto), valor_cru (data-valor), variacao: None | {texto, valor,
    sentido 'alta'|'queda'|'igual', bom True|False|None}, dependente_periodo}] já sem os cartões
    que o papel não vê; `serie` [{rotulo, inicio, sucesso, erro}] (json_script home-serie);
    `erros` [{categoria, rotulo, total}] (home-erros); `por_setor` [{setor, total}] só Adm, None
    nos demais (home-setores); `top_fluxos` [{pk, nome, execucoes, taxa_sucesso, url}];
    `ultimas` [{pk, fluxo_nome, executado_por_nome, status, status_rotulo, iniciada_em,
    url_detalhe}]; `pode_criar_fluxo`, `url_novo_fluxo`, `url_execucoes`; `saudacao`.
    """

    template_name = "inicio/inicio.html"

    def get(self, request, *args, **kwargs):
        if papel_de(request.user) is None:
            raise PermissionDenied
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto.update(painel_ou_erro(self.request.user, self.request.GET.get("periodo", "")))
        contexto["saudacao"] = f"Olá, {self.request.user.nome}"
        return contexto
