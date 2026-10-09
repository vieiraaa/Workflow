from django import forms
from django.core.exceptions import ValidationError

from .models import Setor

MSG_NOME_DUPLICADO = "Já existe um setor com este nome."
MSG_OBRIGATORIO = "Este campo é obrigatório."
MSG_SETOR_INVALIDO = "Setor inválido."


class SetorForm(forms.Form):
    """Campos POST: nome, ativo (checkbox). Criar e renomear/ativar/desativar (SET-02)."""

    nome = forms.CharField(
        label="Nome",
        max_length=80,
        error_messages={"required": MSG_OBRIGATORIO, "max_length": "Use no máximo 80 caracteres."},
    )
    ativo = forms.BooleanField(label="Ativo", required=False)

    def __init__(self, *args, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    @classmethod
    def valores_iniciais(cls, setor):
        return {"nome": setor.nome, "ativo": setor.ativo}

    def clean_nome(self):
        nome = self.cleaned_data["nome"].strip()
        if not nome:
            raise ValidationError(MSG_OBRIGATORIO, code="required")
        duplicados = Setor.objects.filter(nome__iexact=nome)
        if self.instance is not None:
            duplicados = duplicados.exclude(pk=self.instance.pk)
        if duplicados.exists():
            raise ValidationError(MSG_NOME_DUPLICADO)
        return nome

    def salvar(self):
        setor = self.instance or Setor()
        setor.nome = self.cleaned_data["nome"]
        setor.ativo = self.cleaned_data["ativo"]
        setor.save()
        return setor


def campo_setor(label="Setor", **kwargs):
    """Campo `setor` (id) de formulário: só setores ativos; vazio é aceito (cada form decide)."""
    return forms.ChoiceField(
        label=label,
        required=False,
        choices=[],
        error_messages={"invalid_choice": MSG_SETOR_INVALIDO},
        **kwargs,
    )


def escolhas_setor(vazio, atual_id=None):
    """[(id, nome)] dos setores ativos, mais o atual (mesmo inativo, rotulado) para não perdê-lo."""
    escolhas = [("", vazio)]
    for setor in Setor.objects.order_by("nome"):
        if setor.ativo:
            escolhas.append((str(setor.pk), setor.nome))
        elif setor.pk == atual_id:
            escolhas.append((str(setor.pk), f"{setor.nome} (inativo)"))
    return escolhas


def setor_escolhido(valor):
    return Setor.objects.get(pk=int(valor)) if valor else None
