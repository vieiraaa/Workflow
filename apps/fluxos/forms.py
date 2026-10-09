from django import forms

from apps.contas.forms_setores import campo_setor, escolhas_setor, setor_escolhido

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

    def __init__(self, *args, com_setor=False, setor_atual_id=None, **kwargs):
        """`com_setor` (só Adm, SET-04): acrescenta o campo `setor` (id; vazio = não muda)."""
        super().__init__(*args, **kwargs)
        if com_setor:
            self.fields["setor"] = campo_setor()
            self.fields["setor"].choices = escolhas_setor("Manter o setor atual", setor_atual_id)

    def setor_novo(self):
        """Setor escolhido (Setor) ou None quando o campo não existe ou veio vazio."""
        return setor_escolhido(self.cleaned_data.get("setor"))
