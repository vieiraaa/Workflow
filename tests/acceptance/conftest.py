"""Fixtures próprias do aceite. As de papel/cliente vêm de tests/conftest.py.

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


# ---------- M2: fluxos e grafo (docs/spec/grafo.yaml) ----------
import copy
import json as _json


def grafo_minimo_valido():
    """Cadeia gatilho → http → saída sem pendências (exemplo da spec)."""
    return {"versao": 1, "nos": [
        {"id": "n1", "tipo": "gatilho", "titulo": "Início", "posicao": {"x": 80, "y": 120}, "config": {}},
        {"id": "n2", "tipo": "http", "titulo": "Buscar pedido", "posicao": {"x": 360, "y": 120},
         "config": {"metodo": "GET", "url": "https://api.exemplo.test/pedidos/1",
                    "headers": [{"nome": "Accept", "valor": "application/json"}],
                    "query": [{"nome": "detalhe", "valor": "completo"}], "corpo": ""}},
        {"id": "n3", "tipo": "saida", "titulo": "Resultado", "posicao": {"x": 640, "y": 120}, "config": {}}],
        "arestas": [{"de": "n1", "para": "n2"}, {"de": "n2", "para": "n3"}]}


@pytest.fixture
def grafo_valido():
    return copy.deepcopy(grafo_minimo_valido())


@pytest.fixture
def fabrica_fluxo(db, usuario_adm):
    """Cria Fluxo fictício direto no modelo fluxos.Fluxo (campos: docs/spec/grafo.yaml)."""
    from django.apps import apps
    Fluxo = apps.get_model("fluxos", "Fluxo")
    contador = itertools.count(1)

    def _criar(nome=None, status="rascunho", dono=None, grafo=None, descricao="Descrição fictícia"):
        n = next(contador)
        return Fluxo.objects.create(
            nome=nome or f"Fluxo Fictício {n}", descricao=descricao, dono=dono or usuario_adm,
            status=status, grafo=copy.deepcopy(grafo if grafo is not None else grafo_minimo_valido()))

    return _criar


@pytest.fixture
def salvar_grafo():
    """POST JSON em fluxos:salvar_grafo (GRF-01). Devolve a resposta."""
    from django.urls import reverse

    def _salvar(cliente, fluxo, grafo, atualizado_em=None, bruto=None):
        from django.apps import apps
        if atualizado_em is None:
            fluxo.refresh_from_db()
            atualizado_em = fluxo.atualizado_em.isoformat()
        corpo = bruto if bruto is not None else _json.dumps({"grafo": grafo, "atualizado_em": atualizado_em})
        return cliente.post(reverse("fluxos:salvar_grafo", kwargs={"pk": fluxo.pk}), corpo,
                            content_type="application/json")

    return _salvar
