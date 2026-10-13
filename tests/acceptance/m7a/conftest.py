"""Fixtures do aceite M7a (núcleo das Funções). Só pela spec: docs/spec/funcoes.yaml (FUN-01..13), permissoes.yaml.

SUPOSIÇÕES (lacunas de spec, registradas no relatório): o app label do model Funcao não está na spec — é achado por
nome em apps.get_models(); Funcao/Credencial são criadas pelas rotas POST da spec (funcoes:nova, funcoes:publicar,
credenciais:nova), não pelo ORM. Reaproveita as fixtures do m5 (servidor local, grafo2/no2, executar…).
"""
import copy
import itertools
import json
import re

import pytest
from django.apps import apps
from django.test import Client
from django.urls import reverse

from tests.acceptance.m5.conftest import *  # noqa: F401,F403  (servidor, liberado, h, modelos, no, jsons, chave_credenciais…)

_n = itertools.count(1)


def html(r):
    return r.content.decode()


def texto(r):
    """HTML sem tags, espaços normalizados (para checar mensagens e células)."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html(r)))


@pytest.fixture
def Funcao(db):
    achados = [m for m in apps.get_models() if m.__name__ == "Funcao"]
    assert len(achados) == 1, "model Funcao não encontrado (FUN, modelo)"
    return achados[0]


@pytest.fixture
def mundo7(db, fabrica_usuario, mk_setor):
    """Dois setores; Adm; Coordenador e Base em cada setor; Base sem setor."""
    class W:
        pass

    w = W()
    w.A, w.B = mk_setor("Setor Alfa M7"), mk_setor("Setor Beta M7")
    w.adm = fabrica_usuario("Adm")
    w.cA, w.cB = fabrica_usuario("Coordenador"), fabrica_usuario("Coordenador")
    w.bA, w.bA2, w.bB, w.bS = (fabrica_usuario("Base") for _ in range(4))
    for u, s in ((w.cA, w.A), (w.cB, w.B), (w.bA, w.A), (w.bA2, w.A), (w.bB, w.B), (w.bS, None)):
        u.setor = s
        u.save()
    w.c = {}
    for k in ("adm", "cA", "cB", "bA", "bA2", "bB", "bS"):
        cl = Client()
        cl.force_login(getattr(w, k))
        w.c[k] = cl
    w.anon = Client()
    return w


def grafo_func(valor="{{ $parametros.nome }}", tipo="texto"):
    """gatilho → editar campos 'r' (lê $parametros) — último nó 'calc'."""
    return cadeia2(no2("calc", "editar_campos", cfg_editar([("r", valor, tipo)]), x=200, titulo="Calc"))  # noqa: F405


@pytest.fixture
def mk_fluxo7(fabrica_fluxo, modelos):
    def _f(setor=None, grafo=None, nome=None, status="ativo"):
        f = fabrica_fluxo(grafo=copy.deepcopy(grafo if grafo is not None else grafo_func("fixo")), status=status,
                          nome=nome)
        if setor is not None:
            modelos.Fluxo.objects.filter(pk=f.pk).update(setor=setor)
            f.refresh_from_db()
        return f

    return _f


def dados_funcao(fluxo, nome=None, **extra):
    d = {"nome": nome or f"Função Fictícia {next(_n)}", "descricao": "Descrição fictícia", "icone": "zap",
         "fluxo": fluxo.pk, "liberar_para": "todos", "entradas": "[]", "ativa": "on"}
    d.update(extra)
    return d


def entrada(nome, tipo="texto", **kw):
    e = {"nome": nome, "rotulo": kw.pop("rotulo", nome.capitalize()), "tipo": tipo,
         "obrigatoria": kw.pop("obrigatoria", False), "padrao": kw.pop("padrao", None), "opcoes": kw.pop("opcoes", [])}
    e.update(kw)
    return e


@pytest.fixture
def criar_funcao(mundo7, Funcao):
    """criar_funcao(fluxo, publicar=True, **campos) → Funcao. Cria pelo POST do Adm (FUN-03) e publica (FUN-04)."""

    def _c(fluxo, publicar=True, entradas=None, ativa=True, **extra):
        d = dados_funcao(fluxo, **extra)
        if entradas is not None:
            d["entradas"] = json.dumps(entradas)
        if not ativa:
            d.pop("ativa")
        r = mundo7.c["adm"].post(reverse("funcoes:nova"), d)
        assert r.status_code == 302, texto(r)[:500]
        f = Funcao.objects.get(nome=d["nome"])
        if publicar:
            r = mundo7.c["adm"].post(reverse("funcoes:publicar", kwargs={"pk": f.pk}))
            assert r.status_code == 302
            f.refresh_from_db()
            assert f.versao == 1
        return f

    return _c


@pytest.fixture
def exec_funcao(mundo7, modelos):
    """exec_funcao(cliente, funcao, dados=None) → (resposta, Execucao nova | None)."""

    def _e(cliente, funcao, dados=None, follow=False):
        antes = set(modelos.Execucao.objects.values_list("pk", flat=True))
        r = cliente.post(reverse("funcoes:executar", kwargs={"pk": funcao.pk}), dados or {}, follow=follow)
        novas = modelos.Execucao.objects.exclude(pk__in=antes).order_by("pk")
        return r, novas.last()

    return _e
