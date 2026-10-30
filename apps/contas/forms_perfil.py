from django import forms
from django.core.exceptions import ValidationError

from .forms_usuarios import UsuarioEditarForm

MAX_RESPONSABILIDADES = 20
MAX_LINHA = 160


class PerfilForm(forms.Form):
    """Campos POST: bio, responsabilidades (uma por linha). D-041."""

    bio = forms.CharField(
        label="Bio",
        required=False,
        max_length=1000,
        widget=forms.Textarea(
            attrs={"rows": 4, "placeholder": "Conte um pouco sobre você e o seu trabalho."}
        ),
        error_messages={"max_length": "Use no máximo %(limit_value)d caracteres."},
    )
    responsabilidades = forms.CharField(
        label="Responsabilidades",
        required=False,
        max_length=MAX_RESPONSABILIDADES * MAX_LINHA,
        widget=forms.Textarea(attrs={"rows": 6, "placeholder": "Uma por linha"}),
        help_text=f"Uma por linha, até {MAX_RESPONSABILIDADES}.",
        error_messages={"max_length": "Texto longo demais."},
    )

    def clean_responsabilidades(self):
        linhas = [linha.strip() for linha in self.cleaned_data["responsabilidades"].splitlines()]
        linhas = [linha for linha in linhas if linha]
        if len(linhas) > MAX_RESPONSABILIDADES:
            raise ValidationError(f"Liste no máximo {MAX_RESPONSABILIDADES} responsabilidades.")
        if any(len(linha) > MAX_LINHA for linha in linhas):
            raise ValidationError(f"Cada responsabilidade pode ter até {MAX_LINHA} caracteres.")
        return "\n".join(linhas)

    def salvar(self, usuario):
        usuario.bio = self.cleaned_data["bio"].strip()
        usuario.responsabilidades = self.cleaned_data["responsabilidades"]
        usuario.save(update_fields=["bio", "responsabilidades"])
        return usuario


class PerfilAcessoForm(UsuarioEditarForm):
    """Acesso pelo perfil (só Adm): papel, setor, ativo. Mesmas regras do UsuarioEditarForm
    (setor obrigatório, não se rebaixar, manter um Adm ativo); nome e e-mail ficam como estão."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields["nome"], self.fields["email"]

    def salvar(self):
        self.cleaned_data.update(nome=self.instance.nome, email=self.instance.email)
        return super().salvar()
