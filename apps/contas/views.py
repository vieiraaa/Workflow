from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse
from django.views.generic import TemplateView

from apps.nucleo.contexto import atalhos_do_usuario

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
    """Rota `inicio` (PRM-07). Template `inicio/inicio.html`.

    Sem papel → 403 do produto. Com papel → redireciona para `fluxos:lista`; enquanto essa rota
    não existe (antes do M2), renderiza o início.

    Contexto: shell (menu, usuario_nome, usuario_papel), `atalhos` (itens do menu),
    `saudacao` (str).
    """

    template_name = "inicio/inicio.html"

    def get(self, request, *args, **kwargs):
        if papel_de(request.user) is None:
            raise PermissionDenied
        try:
            return redirect(reverse("fluxos:lista"))
        except NoReverseMatch:
            return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["atalhos"] = atalhos_do_usuario(self.request)
        contexto["saudacao"] = f"Olá, {self.request.user.nome}"
        return contexto
