"""Fixtures do adversarial (cópia independente das do aceite). Papel de dados_usuario = id (USR-14).

CONTRATO (docs/spec/usuarios.yaml USR-13..15):
- nomes de campos e manager: USR-13, USR-15; papel = id (adm|coordenador|base): USR-14.
  `fabrica_usuario(papel=...)` usa o NOME do Group (Adm|Coordenador|Base); `dados_usuario(papel=...)` usa o ID.
"""
import itertools

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

SENHA = "Senha-Forte-Ficticia-91"
_contador = itertools.count(1)


@pytest.fixture
def senha_padrao():
    return SENHA


@pytest.fixture
def fabrica_usuario(db):
    """Cria usuário fictício. papel=None cria sem grupo (sem papel)."""
    Usuario = get_user_model()

    def _criar(papel="Base", nome=None, email=None, ativo=True, senha=SENHA):
        n = next(_contador)
        usuario = Usuario.objects.create_user(
            email=email or f"fabrica{n}@exemplo.test",
            password=senha,
            nome=nome or f"Pessoa Fabrica {n}",
        )
        if papel:
            usuario.groups.set([Group.objects.get(name=papel)])
        if not ativo:
            usuario.is_active = False
            usuario.save()
        return usuario

    return _criar


@pytest.fixture
def usuario_sem_papel(fabrica_usuario):
    return fabrica_usuario(papel=None)


@pytest.fixture
def cliente_sem_papel(client, usuario_sem_papel):
    client.force_login(usuario_sem_papel)
    return client


@pytest.fixture
def dados_usuario():
    """Monta o POST do formulário de usuário (criar/editar)."""

    def _dados(nome="Maria Ficticia", email="maria@exemplo.test", papel="base",
               senha=SENHA, confirmacao=None, ativo=True, com_senha=True):
        d = {"nome": nome, "email": email, "papel": papel}
        if ativo:
            d["ativo"] = "on"
        if com_senha:
            d["senha"] = senha
            d["confirmacao"] = senha if confirmacao is None else confirmacao
        return d

    return _dados
