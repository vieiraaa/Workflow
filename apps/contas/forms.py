from django.contrib.auth.forms import AuthenticationForm


class LoginForm(AuthenticationForm):
    """Login por e-mail (campo `username`). Mensagem genérica, sem revelar o e-mail (SEG-15)."""

    error_messages = {
        "invalid_login": "E-mail ou senha inválidos.",
        "inactive": "E-mail ou senha inválidos.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "E-mail"
        self.fields["username"].widget.attrs.update({"autocomplete": "email", "autofocus": True})
