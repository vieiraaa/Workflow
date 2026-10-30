from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from . import bloqueio_login
from .ad import ADIndisponivel, SemPermissaoAD, normalizar_login


class LoginForm(AuthenticationForm):
    """Login (campo `username`). Com LOGIN_AD é o usuário de rede (D-039); sem, o e-mail.
    Mensagem genérica, sem revelar se o usuário existe (SEG-15)."""

    error_messages = {
        "invalid_login": "E-mail ou senha inválidos.",
        "inactive": "E-mail ou senha inválidos.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        campo = self.fields["username"]
        if settings.LOGIN_AD:
            self.error_messages = {
                "invalid_login": "Usuário ou senha inválidos.",
                "inactive": "Usuário ou senha inválidos.",
            }
            campo.label = "Usuário"
            campo.widget.attrs.update(
                {"autocomplete": "username", "autofocus": True, "placeholder": "nome.sobrenome"}
            )
        else:
            campo.label = "E-mail"
            campo.widget.attrs.update({"autocomplete": "email", "autofocus": True})

    def clean(self):
        if not settings.LOGIN_AD:
            return super().clean()
        par = bloqueio_login.chave(self.request, normalizar_login(self.data.get("username")))
        espera = bloqueio_login.espera(par)
        if espera:
            raise ValidationError(
                f"Muitas tentativas. Aguarde {espera} s e tente de novo.", code="bloqueado"
            )
        try:
            dados = super().clean()
        except ADIndisponivel:
            raise ValidationError(
                "Não foi possível conectar ao AD. Tente novamente em instantes.",
                code="ad_indisponivel",
            ) from None
        except SemPermissaoAD:
            raise ValidationError(
                "Seu usuário não tem permissão para acessar o Construtor de Workflows.",
                code="sem_permissao",
            ) from None
        except ValidationError:
            bloqueio_login.registrar_falha(par)
            raise
        bloqueio_login.limpar(par)
        return dados
