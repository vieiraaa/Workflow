"""Formulários do cadastro: processo (conferência/manual) e configuração (CAD-14/15/21)."""

from decimal import Decimal

from django import forms

from apps.contas.models import Setor
from apps.credenciais.models import Credencial

from . import clientes, cnj, leitura
from .models import CAMPOS_MANUAIS, CAMPOS_TEXTO, Carteira, ConfigCadastro, Processo

CAMPOS_PROCESSO = (
    "numero", "carteira", *CAMPOS_TEXTO, "fase_atual", "distribuido_em", "data_citacao",
    "valor_causa", "pedidos", "observacoes", "proxima_audiencia",
)  # fmt: skip
GRUPOS = (
    ("Identificação", ("numero", "carteira", "operacoes_vinculadas", "desdobramento")),
    ("Cliente", ("empresa", "condicao", "advogado_empresa")),
    (
        "Adverso",
        ("adverso_nome", "adverso_cpf_cnpj", "advogado_adverso_nome", "advogado_adverso_oab"),
    ),
    (
        "Jurisdição",
        (
            "tribunal",
            "comarca",
            "juizo",
            "estado",
            "instancia",
            "rito",
            "natureza",
            "meio_tramitacao",
            "tipo_acao",
            "fase_atual",
        ),
    ),  # fmt: skip
    ("Datas e valores", ("distribuido_em", "data_citacao", "valor_causa", "proxima_audiencia")),
    ("Pedidos", ("pedidos",)),
    ("Andamentos", ()),
    ("Controle", ("observacoes", *CAMPOS_MANUAIS)),
)


def texto_valor(valor):
    """Valor no formato brasileiro do formulário: 12500 → '12.500,00'."""
    if valor is None:
        return ""
    inteiro, _, centavos = f"{Decimal(valor):,.2f}".partition(".")
    return f"{inteiro.replace(',', '.')},{centavos}"


class ProcessoForm(forms.ModelForm):
    numero = forms.CharField(label="Número", required=False, max_length=60)
    valor_causa = forms.CharField(label="Valor da causa", required=False, max_length=30)
    distribuido_em = forms.DateField(label="Distribuído em", required=False)
    data_citacao = forms.DateField(label="Data de citação", required=False)
    proxima_audiencia = forms.DateTimeField(label="Próxima audiência", required=False)
    carteira = forms.ModelChoiceField(
        label="Carteira", queryset=Carteira.objects.all(), required=False
    )
    fase_atual = forms.ChoiceField(
        label="Fase atual", required=False, choices=[("", "—"), *Processo.FASES]
    )

    class Meta:
        model = Processo
        fields = CAMPOS_PROCESSO
        labels = {
            "adverso_nome": "Nome do adverso",
            "adverso_cpf_cnpj": "CPF/CNPJ do adverso",
            "advogado_adverso_nome": "Advogado do adverso",
            "advogado_adverso_oab": "OAB do advogado adverso",
            "advogado_empresa": "Advogado da empresa",
            "operacoes_vinculadas": "Operações vinculadas",
            "meio_tramitacao": "Meio de tramitação",
            "tipo_acao": "Tipo de ação",
            "na_fase_desde": "Na fase desde",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nome, campo in self.fields.items():
            campo.required = nome == "numero" and self.instance.pk is None
        if self.instance.pk is None:
            self.fields["numero"].required = True
        if self.instance.pk:  # o ModelForm já preencheu 'valor_causa' com 12500.00: troca
            self.initial["valor_causa"] = texto_valor(self.instance.valor_causa)

    def clean_numero(self):
        numero = (self.cleaned_data.get("numero") or "").strip()
        if self.instance.pk is None and not cnj.valido(numero):
            raise forms.ValidationError("Número CNJ inválido.")
        digitos = cnj.so_digitos(numero)
        if self.instance.pk and not numero:
            raise forms.ValidationError("Informe o número do processo.")
        if cnj.valido(digitos):
            outro = Processo.todos.filter(numero_digitos=digitos, numero_valido=True)
            if self.instance.pk:
                outro = outro.exclude(pk=self.instance.pk)
            if outro.exists():
                raise forms.ValidationError("Já existe outro processo com este número.")
        return numero

    def clean_valor_causa(self):
        texto = (self.cleaned_data.get("valor_causa") or "").strip()
        if not texto:
            return None
        valor = leitura.converter_valor(texto)
        if valor is None or valor < 0:
            raise forms.ValidationError("Informe um valor válido, como 1.234,56.")
        return valor

    def clean_fase_atual(self):
        return self.cleaned_data.get("fase_atual") or None


class ConfigForm(forms.ModelForm):
    setores_com_acesso = forms.ModelMultipleChoiceField(
        label="Setores com acesso",
        queryset=Setor.objects.order_by("nome"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = ConfigCadastro
        fields = (
            "dify_url", "dify_credencial", "dify_usuario", "dify_ca_pem",
            "datajud_url", "datajud_credencial", "setores_com_acesso",
        )  # fmt: skip

    def clean_dify_ca_pem(self):
        pem = (self.cleaned_data.get("dify_ca_pem") or "").strip()
        try:
            clientes.validar_pem(pem)
        except ValueError as erro:
            raise forms.ValidationError(str(erro)) from None
        return pem

    def _credencial(self, campo, tipo, rotulo):
        nome = (self.cleaned_data.get(campo) or "").strip()
        if (
            nome
            and not Credencial.objects.filter(
                nome__iexact=nome, tipo=tipo, setor__isnull=True
            ).exists()
        ):
            raise forms.ValidationError(
                f"Escolha uma credencial {rotulo} sem setor, cadastrada em Credenciais."
            )
        return nome

    def clean_dify_credencial(self):
        return self._credencial("dify_credencial", Credencial.BEARER, "do tipo Bearer")

    def clean_datajud_credencial(self):
        return self._credencial("datajud_credencial", Credencial.HEADER, "do tipo Header")


class CarteiraForm(forms.ModelForm):
    class Meta:
        model = Carteira
        fields = ("nome", "empresa", "ativa")

    def clean_nome(self):
        nome = (self.cleaned_data.get("nome") or "").strip()
        outras = Carteira.objects.filter(nome__iexact=nome)
        if self.instance.pk:
            outras = outras.exclude(pk=self.instance.pk)
        if not nome:
            raise forms.ValidationError("Informe o nome da carteira.")
        if outras.exists():
            raise forms.ValidationError("Já existe uma carteira com este nome.")
        return nome
