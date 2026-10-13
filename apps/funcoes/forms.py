import json

from django import forms

from apps.contas.models import Setor
from apps.fluxos.models import Fluxo

from . import entradas as ent
from .models import ICONES, PAPEIS_LIBERAVEIS, Funcao


class FuncaoForm(forms.Form):
    nome = forms.CharField(
        label="Nome", max_length=80, error_messages={"required": "Informe o nome."}
    )
    descricao = forms.CharField(label="Descrição", max_length=300, required=False)
    icone = forms.ChoiceField(
        label="Ícone",
        choices=[(i, i) for i in ICONES],
        initial="zap",
        error_messages={"invalid_choice": "Ícone inválido."},
    )
    fluxo = forms.ModelChoiceField(
        label="Fluxo",
        queryset=Fluxo.objects.all(),
        empty_label="Escolha um fluxo",
        error_messages={"required": "Fluxo inválido.", "invalid_choice": "Fluxo inválido."},
    )
    liberar_para = forms.ChoiceField(
        label="Liberar para", choices=Funcao.LIBERAR_PARA, initial=Funcao.TODOS
    )
    setores = forms.ModelMultipleChoiceField(
        label="Setores",
        queryset=Setor.objects.all(),
        required=False,
        error_messages={"invalid_choice": "Setor inválido.", "invalid_pk_value": "Setor inválido."},
    )
    papeis = forms.MultipleChoiceField(
        label="Papéis",
        choices=PAPEIS_LIBERAVEIS,
        required=False,
        error_messages={"invalid_choice": "Papel inválido."},
    )
    entradas = forms.CharField(label="Entradas", required=False)
    ativa = forms.BooleanField(label="Função ativa", required=False)

    def __init__(self, *args, instance=None, **kwargs):
        self.instance = instance
        if instance is not None and not args and "initial" not in kwargs:
            kwargs["initial"] = {
                "nome": instance.nome,
                "descricao": instance.descricao,
                "icone": instance.icone,
                "fluxo": instance.fluxo_id,
                "liberar_para": instance.liberar_para,
                "setores": list(instance.setores.values_list("pk", flat=True)),
                "papeis": list(instance.papeis or []),
                "entradas": json.dumps(instance.entradas or [], ensure_ascii=False),
                "ativa": instance.ativa,
            }
        elif instance is None and not args and "initial" not in kwargs:
            kwargs["initial"] = {"ativa": True}
        super().__init__(*args, **kwargs)

    def clean_nome(self):
        nome = self.cleaned_data["nome"].strip()
        if not nome:
            raise forms.ValidationError("Informe o nome.")
        existentes = Funcao.objects.filter(nome__iexact=nome)
        if self.instance is not None:
            existentes = existentes.exclude(pk=self.instance.pk)
        if existentes.exists():
            raise forms.ValidationError("Já existe uma função com este nome.")
        return nome

    def clean_entradas(self):
        try:
            return ent.ler_json(self.cleaned_data.get("entradas", ""))
        except ent.EntradaInvalida as erro:
            raise forms.ValidationError(f"Entradas inválidas: {erro}.") from None

    def clean(self):
        dados = super().clean()
        destino = dados.get("liberar_para")
        if destino == Funcao.SETORES and not dados.get("setores"):
            self.add_error("setores", "Escolha ao menos um setor.")
        if destino == Funcao.PAPEIS and not dados.get("papeis"):
            self.add_error("papeis", "Escolha ao menos um papel.")
        return dados

    def salvar(self, usuario):
        d = self.cleaned_data
        funcao = self.instance or Funcao(criada_por=usuario)
        funcao.nome, funcao.descricao, funcao.icone = d["nome"], d["descricao"].strip(), d["icone"]
        funcao.fluxo, funcao.liberar_para, funcao.entradas = (
            d["fluxo"],
            d["liberar_para"],
            d["entradas"],
        )
        funcao.papeis = list(d["papeis"]) if d["liberar_para"] == Funcao.PAPEIS else []
        funcao.ativa = d["ativa"]
        funcao.save()
        funcao.setores.set(d["setores"] if d["liberar_para"] == Funcao.SETORES else [])
        return funcao
