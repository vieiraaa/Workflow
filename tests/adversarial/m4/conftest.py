"""Fixtures do adversarial M4 (cópia independente das do aceite) (docs/spec/setores.yaml, home.yaml).

SUPOSIÇÕES (lacunas registradas no relatório): modelo `contas.Setor` (nome, ativo); `Usuario.setor`, `Fluxo.setor`,
`Execucao.setor` são FKs atribuíveis por nome de campo `setor` (setores.yaml). As fixtures de papel de
tests/conftest.py NÃO têm setor; aqui criamos usuários próprios por setor.
"""
import copy
import itertools
from datetime import timedelta

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.utils import timezone

SENHA = "Senha-Forte-Ficticia-91"
_n = itertools.count(1)

GRAFO = {"versao": 1, "nos": [
    {"id": "n1", "tipo": "gatilho", "titulo": "Início", "posicao": {"x": 80, "y": 120}, "config": {}},
    {"id": "n2", "tipo": "http", "titulo": "Buscar", "posicao": {"x": 360, "y": 120},
     "config": {"metodo": "GET", "url": "https://api.exemplo.test/p/1", "headers": [], "query": [], "corpo": ""}},
    {"id": "n3", "tipo": "saida", "titulo": "Resultado", "posicao": {"x": 640, "y": 120}, "config": {}}],
    "arestas": [{"de": "n1", "para": "n2"}, {"de": "n2", "para": "n3"}]}


@pytest.fixture
def M(db):
    class _M:
        Setor = apps.get_model("contas", "Setor")
        Usuario = get_user_model()
        Fluxo = apps.get_model("fluxos", "Fluxo")
        Execucao = apps.get_model("execucoes", "Execucao")
    return _M


@pytest.fixture
def mk_setor(M):
    def _c(nome=None, ativo=True):
        return M.Setor.objects.create(nome=nome or f"Setor Ficticio {next(_n)}", ativo=ativo)
    return _c


@pytest.fixture
def mk_usuario(M):
    def _c(papel, setor=None, nome=None):
        n = next(_n)
        u = M.Usuario.objects.create_user(email=f"m4u{n}@exemplo.test", password=SENHA, nome=nome or f"Pessoa M4 {n}")
        u.groups.set([Group.objects.get(name=papel)])
        u.setor = setor
        u.save()
        return u
    return _c


@pytest.fixture
def logar():
    def _l(u):
        c = Client()
        c.force_login(u)
        return c
    return _l


@pytest.fixture
def mk_fluxo(M):
    def _c(setor, dono, nome=None, status="ativo"):
        return M.Fluxo.objects.create(nome=nome or f"Fluxo M4 {next(_n)}", descricao="d", dono=dono, status=status,
                                      grafo=copy.deepcopy(GRAFO), setor=setor)
    return _c


@pytest.fixture
def mk_exec(M):
    def _c(fluxo, por, status="sucesso", quando=None, dur=2, setor=None, nome=None, resumo=""):
        quando = quando or timezone.now() - timedelta(hours=1)
        return M.Execucao.objects.create(
            fluxo=fluxo, fluxo_nome=nome or (fluxo.nome if fluxo else "Fluxo removido"), grafo_snapshot=copy.deepcopy(GRAFO),
            executado_por=por, status=status, iniciada_em=quando,
            finalizada_em=None if status == "executando" else quando + timedelta(seconds=dur), erro_resumo=resumo,
            setor=setor if setor is not None else (fluxo.setor if fluxo else None))
    return _c


@pytest.fixture
def mundo(mk_setor, mk_usuario, mk_fluxo, mk_exec, logar):
    """Dois setores (A, B), Adm sem setor, gestor e base em cada um, fluxos e execuções em cada."""
    class W:
        pass
    w = W()
    w.A, w.B = mk_setor("Setor Alfa"), mk_setor("Setor Beta")
    w.adm = mk_usuario("Adm")
    w.gA, w.gB = mk_usuario("Coordenador", w.A), mk_usuario("Coordenador", w.B)
    w.bA, w.bB = mk_usuario("Base", w.A), mk_usuario("Base", w.B)
    w.bA2 = mk_usuario("Base", w.A)
    w.fA = mk_fluxo(w.A, w.gA, "Fluxo Alfa Ativo")
    w.fAr = mk_fluxo(w.A, w.gA, "Fluxo Alfa Rascunho", status="rascunho")
    w.fB = mk_fluxo(w.B, w.gB, "Fluxo Beta Ativo")
    w.fBr = mk_fluxo(w.B, w.gB, "Fluxo Beta Rascunho", status="rascunho")
    w.eA_bA = mk_exec(w.fA, w.bA)
    w.eA_bA2 = mk_exec(w.fA, w.bA2)
    w.eA_gA = mk_exec(w.fA, w.gA)
    w.eB_bB = mk_exec(w.fB, w.bB)
    w.eB_gB = mk_exec(w.fB, w.gB)
    w.c = {k: logar(getattr(w, k)) for k in ("adm", "gA", "gB", "bA", "bB", "bA2")}
    return w


@pytest.fixture(params=["chromium", "webkit"])
def pagina_adm(request, live_server, mundo):
    """Página Playwright (chromium e webkit, 1280x800) logada como Adm, contra o live_server. Coleta diálogos e erros JS."""
    import os

    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
    from playwright.sync_api import sync_playwright

    sessao = mundo.c["adm"].cookies["sessionid"].value
    with sync_playwright() as pw:
        navegador = getattr(pw, request.param).launch()
        contexto = navegador.new_context(viewport={"width": 1280, "height": 800})
        contexto.add_cookies([{"name": "sessionid", "value": sessao, "url": live_server.url}])
        pagina = contexto.new_page()
        pagina.live_url = live_server.url
        pagina.dialogos = []
        pagina.erros_js = []
        pagina.on("dialog", lambda d: (pagina.dialogos.append(d.message), d.dismiss()))
        pagina.on("pageerror", lambda e: pagina.erros_js.append(str(e)))
        yield pagina
        navegador.close()
