from django import forms
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction

from .forms_setores import campo_setor, escolhas_setor, setor_escolhido
from .models import Usuario
from .permissoes import papeis
from .sessoes import encerrar_sessoes

MSG_EMAIL_DUPLICADO = "Já existe um usuário com este e-mail."
MSG_SENHAS_DIFERENTES = "As senhas não conferem."
MSG_ULTIMO_ADM = "É preciso manter pelo menos um administrador ativo."
MSG_SETOR_OBRIGATORIO = "Escolha um setor."
MSG_AUTOPROTECAO = "Você não pode desativar a si mesmo nem remover o seu papel de administrador."


def _escolhas_papel():
    return [("", "Selecione um papel")] + [(p["id"], p["nome"]) for p in papeis()]


def _grupo_do_papel(papel_id):
    return next(p["grupo"] for p in papeis() if p["id"] == papel_id)


def _campo_papel():
    return forms.ChoiceField(
        label="Papel",
        choices=_escolhas_papel,
        error_messages={"required": "Escolha um papel.", "invalid_choice": "Papel inválido."},
    )


class _ComSenha(forms.Form):
    """Valida nova senha + confirmação com os validadores do Django."""

    campo_senha = "nova_senha"
    campo_confirmacao = "confirmacao"

    def _usuario_da_senha(self):
        return None

    def clean(self):
        dados = super().clean()
        senha = dados.get(self.campo_senha)
        confirmacao = dados.get(self.campo_confirmacao)
        if senha and confirmacao and senha != confirmacao:
            self.add_error(self.campo_confirmacao, MSG_SENHAS_DIFERENTES)
        elif senha and confirmacao:
            try:
                validate_password(senha, self._usuario_da_senha())
            except ValidationError as erro:
                self.add_error(self.campo_senha, erro)
        return dados


def _exigir_setor(form, dados):
    """SET-03: setor obrigatório para papel ≠ adm."""
    if dados.get("papel") and dados["papel"] != "adm" and not dados.get("setor"):
        if "setor" not in form.errors:
            form.add_error("setor", MSG_SETOR_OBRIGATORIO)


class UsuarioNovoForm(_ComSenha):
    """Campos POST: nome, email, papel (id), setor (id), senha, confirmacao (USR-13, SET-03)."""

    campo_senha = "senha"

    nome = forms.CharField(label="Nome", max_length=120)
    email = forms.EmailField(label="E-mail", max_length=254)
    papel = _campo_papel()
    setor = campo_setor()
    senha = forms.CharField(label="Senha", widget=forms.PasswordInput(render_value=False))
    confirmacao = forms.CharField(
        label="Confirmação da senha", widget=forms.PasswordInput(render_value=False)
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["setor"].choices = escolhas_setor("Sem setor")

    def clean(self):
        dados = super().clean()
        _exigir_setor(self, dados)
        return dados

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if Usuario.objects.filter(email__iexact=email).exists():
            raise ValidationError(MSG_EMAIL_DUPLICADO)
        return email

    def _usuario_da_senha(self):
        return Usuario(
            nome=self.cleaned_data.get("nome", ""), email=self.cleaned_data.get("email", "")
        )

    def salvar(self):
        dados = self.cleaned_data
        with transaction.atomic():
            usuario = Usuario.objects.create_user(
                email=dados["email"],
                password=dados["senha"],
                nome=dados["nome"],
                setor=setor_escolhido(dados.get("setor")),
            )
            usuario.groups.set([Group.objects.get(name=_grupo_do_papel(dados["papel"]))])
        return usuario


class UsuarioEditarForm(forms.Form):
    """Campos POST: nome, email, papel (id), setor (id), ativo (checkbox). Sem senha (USR-06)."""

    nome = forms.CharField(label="Nome", max_length=120)
    email = forms.EmailField(label="E-mail", max_length=254)
    papel = _campo_papel()
    setor = campo_setor()
    ativo = forms.BooleanField(label="Ativo", required=False)

    def __init__(self, *args, instance, editor, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance
        self.editor = editor
        self.fields["setor"].choices = escolhas_setor("Sem setor", instance.setor_id)

    @classmethod
    def valores_iniciais(cls, usuario):
        from .permissoes import papel_de

        return {
            "nome": usuario.nome,
            "email": usuario.email,
            "papel": papel_de(usuario) or "",
            "setor": str(usuario.setor_id) if usuario.setor_id else "",
            "ativo": usuario.is_active,
        }

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if Usuario.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError(MSG_EMAIL_DUPLICADO)
        return email

    def clean(self):
        dados = super().clean()
        if "papel" not in dados:
            return dados
        _exigir_setor(self, dados)
        papel, ativo = dados["papel"], dados.get("ativo", False)
        # Erro junto do campo: desativação → `ativo`; mudança de papel → `papel`.
        campo_do_erro = "ativo" if not ativo else "papel"
        if self.instance.pk == self.editor.pk and (not ativo or papel != "adm"):
            self.add_error(campo_do_erro, MSG_AUTOPROTECAO)
            return dados
        if not (ativo and papel == "adm"):
            restantes = (
                Usuario.objects.select_for_update()
                .filter(is_active=True, groups__name=_grupo_do_papel("adm"))
                .exclude(pk=self.instance.pk)
            )
            if not list(restantes.values_list("pk", flat=True)):
                self.add_error(campo_do_erro, MSG_ULTIMO_ADM)
        return dados

    def salvar(self):
        dados = self.cleaned_data
        usuario = self.instance
        usuario.nome = dados["nome"]
        usuario.email = dados["email"]
        foi_desativado = usuario.is_active and not dados["ativo"]
        usuario.is_active = dados["ativo"]
        usuario.setor = setor_escolhido(dados.get("setor"))
        usuario.save()
        if foi_desativado:
            encerrar_sessoes(usuario)
        usuario.groups.set([Group.objects.get(name=_grupo_do_papel(dados["papel"]))])
        usuario.__dict__.pop("_papel_cache", None)
        return usuario


class RedefinirSenhaForm(_ComSenha):
    """Campos POST: nova_senha, confirmacao (USR-13). Ação do Adm sobre outro usuário."""

    nova_senha = forms.CharField(label="Nova senha", widget=forms.PasswordInput(render_value=False))
    confirmacao = forms.CharField(
        label="Confirmação da senha", widget=forms.PasswordInput(render_value=False)
    )

    def __init__(self, *args, instance, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance = instance

    def _usuario_da_senha(self):
        return self.instance

    def salvar(self):
        self.instance.set_password(self.cleaned_data["nova_senha"])
        self.instance.save(update_fields=["password"])
        return self.instance


class TrocarSenhaForm(_ComSenha):
    """Campos POST: senha_atual, nova_senha, confirmacao (USR-10/13). A própria senha."""

    senha_atual = forms.CharField(
        label="Senha atual", widget=forms.PasswordInput(render_value=False)
    )
    nova_senha = forms.CharField(label="Nova senha", widget=forms.PasswordInput(render_value=False))
    confirmacao = forms.CharField(
        label="Confirmação da nova senha", widget=forms.PasswordInput(render_value=False)
    )

    def __init__(self, *args, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario

    def _usuario_da_senha(self):
        return self.usuario

    def clean_senha_atual(self):
        senha = self.cleaned_data["senha_atual"]
        if not self.usuario.check_password(senha):
            raise ValidationError("Senha atual incorreta.")
        return senha

    def salvar(self):
        self.usuario.set_password(self.cleaned_data["nova_senha"])
        self.usuario.save(update_fields=["password"])
        return self.usuario
