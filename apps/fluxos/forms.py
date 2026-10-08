from django import forms

MSG_OBRIGATORIO = "Este campo é obrigatório."


class FluxoForm(forms.Form):
    """Criar/editar nome e descrição do fluxo (FLX-02/03/06). Campos POST: nome, descricao."""

    nome = forms.CharField(
        label="Nome",
        max_length=120,
        error_messages={"required": MSG_OBRIGATORIO, "max_length": "Use no máximo 120 caracteres."},
    )
    descricao = forms.CharField(
        label="Descrição",
        max_length=1000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        error_messages={"max_length": "Use no máximo 1000 caracteres."},
    )
