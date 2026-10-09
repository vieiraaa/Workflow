from django import forms
from django.core.exceptions import ValidationError

from apps.contas.forms_setores import campo_setor, escolhas_setor, setor_escolhido

from . import cofre
from .models import Credencial

MSG_OBRIGATORIO = "Este campo é obrigatório."
MSG_INVALIDO = "Valor inválido."
MSG_DUPLICADO = "Já existe uma credencial com este nome."
MSG_MAX_80 = "Use no máximo 80 caracteres."


class CredencialForm(forms.Form):
    """Campos POST: nome, tipo, setor (id ou vazio = global), valor, usuario (basic/smtp),
    header_nome (header), host, porta, tls (smtp). Valor obrigatório na criação; vazio na edição
    mantém o atual (CRD-01)."""

    nome = forms.CharField(
        label="Nome",
        max_length=80,
        error_messages={"required": MSG_OBRIGATORIO, "max_length": MSG_MAX_80},
    )
    tipo = forms.ChoiceField(
        label="Tipo",
        choices=Credencial.TIPOS,
        error_messages={"required": MSG_OBRIGATORIO, "invalid_choice": MSG_INVALIDO},
    )
    setor = campo_setor("Setor")
    valor = forms.CharField(
        label="Valor",
        required=False,
        max_length=4096,
        strip=False,
        widget=forms.PasswordInput(render_value=False),
        error_messages={"max_length": "Use no máximo 4096 caracteres."},
    )
    usuario = forms.CharField(label="Usuário", required=False, max_length=200)
    header_nome = forms.CharField(label="Nome do header", required=False, max_length=100)
    host = forms.CharField(label="Servidor (host)", required=False, max_length=255)
    porta = forms.IntegerField(
        label="Porta",
        required=False,
        min_value=1,
        max_value=65535,
        error_messages={
            "invalid": MSG_INVALIDO,
            "min_value": MSG_INVALIDO,
            "max_value": MSG_INVALIDO,
        },
    )
    tls = forms.BooleanField(label="Usar TLS", required=False)

    def __init__(self, *args, instance=None, dados_atuais=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        self.dados_atuais = dados_atuais or {}
        atual = instance.setor_id if instance is not None else None
        self.fields["setor"].choices = escolhas_setor("Todos os setores (global)", atual)
        self.fields["setor"].error_messages["invalid_choice"] = MSG_INVALIDO
        self.fields["valor"].help_text = (
            "Deixe vazio para manter o valor atual." if instance is not None else ""
        )

    def clean_nome(self):
        nome = self.cleaned_data["nome"].strip()
        if not nome:
            raise ValidationError(MSG_OBRIGATORIO, code="required")
        duplicados = Credencial.objects.filter(nome__iexact=nome)
        if self.instance is not None:
            duplicados = duplicados.exclude(pk=self.instance.pk)
        if duplicados.exists():
            raise ValidationError(MSG_DUPLICADO)
        return nome

    def clean(self):
        dados = super().clean()
        tipo = dados.get("tipo")
        if not cofre.chave_configurada():
            self.add_error(None, cofre.MSG_SEM_CHAVE + " Peça a quem administra o servidor.")
            return dados
        if not (dados.get("valor") or "") and (self.instance is None or not self.dados_atuais):
            self.add_error("valor", MSG_OBRIGATORIO)
        if tipo == Credencial.HEADER and not (dados.get("header_nome") or "").strip():
            self.add_error("header_nome", MSG_OBRIGATORIO)
        if tipo in (Credencial.BASIC, Credencial.SMTP) and not (dados.get("usuario") or "").strip():
            self.add_error("usuario", MSG_OBRIGATORIO)
        if tipo == Credencial.SMTP:
            if not (dados.get("host") or "").strip():
                self.add_error("host", MSG_OBRIGATORIO)
            if not dados.get("porta"):
                self.add_error("porta", MSG_OBRIGATORIO)
        return dados

    def salvar(self, usuario):
        dados = self.cleaned_data
        credencial = self.instance or Credencial(criado_por=usuario)
        credencial.nome = dados["nome"]
        credencial.tipo = dados["tipo"]
        credencial.setor = setor_escolhido(dados["setor"])
        guardado = {
            "valor": dados["valor"] or self.dados_atuais.get("valor", ""),
            "usuario": dados.get("usuario", "").strip(),
            "header_nome": dados.get("header_nome", "").strip(),
            "host": dados.get("host", "").strip(),
            "porta": dados.get("porta") or None,
            "tls": bool(dados.get("tls")),
        }
        credencial.definir_dados(guardado)
        credencial.save()
        return credencial
