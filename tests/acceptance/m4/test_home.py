"""Aceite M4: Home por papel e período. Fontes: HOM-01..08, SET-06, PRM-01/02, TEL-13/16/17.

SUPOSIÇÕES (lacunas no relatório): a spec não define DOM/contexto da Home; os testes leem o HTML renderizado:
cartão = rótulo (texto da spec) seguido do valor em até ~80 caracteres de texto; séries dos gráficos = blocos
<script type="application/json"> (json_script, HOM-08) com listas cujo tamanho = nº de intervalos.
"""
import json
import re
import time
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m4")]


def _h(r):
    return r.content.decode()


def _texto(html):
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def _cartao(html, rotulo, janela=80):
    """Valores (texto) que seguem cada ocorrência do rótulo."""
    t = _texto(html)
    return [t[m.end():m.end() + janela] for m in re.finditer(re.escape(rotulo), t)]


def _tem_valor(html, rotulo, valor):
    return any(re.search(rf"(?<![\d,.]){re.escape(str(valor))}(?![\d])", seg) for seg in _cartao(html, rotulo))


def _blocos_json(html):
    out = []
    for m in re.finditer(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, flags=re.S):
        try:
            out.append(json.loads(m.group(1)))
        except ValueError:
            pass
    return out


def _listas(o):
    if isinstance(o, list):
        yield o
        for x in o:
            yield from _listas(x)
    elif isinstance(o, dict):
        for x in o.values():
            yield from _listas(x)


def _numeros(o):
    if isinstance(o, bool):
        return
    if isinstance(o, (int, float)):
        yield o
    elif isinstance(o, list):
        for x in o:
            yield from _numeros(x)
    elif isinstance(o, dict):
        for x in o.values():
            yield from _numeros(x)


def _serie(html, lo, hi):
    """Primeira lista de dados com tamanho em [lo, hi] e algum número; devolve a lista."""
    for b in _blocos_json(html):
        for lst in _listas(b):
            if lo <= len(lst) <= hi and all(isinstance(x, (dict, list)) for x in lst) and any(list(_numeros(x)) for x in lst):
                return lst
    return None


def _home(c, **params):
    return c.get(reverse("inicio"), params)


@pytest.fixture
def cenario(mundo, mk_fluxo, mk_exec, mk_setor, mk_usuario, M):
    """Setor Alfa: 15 sucesso + 5 erro nos últimos 7d (2 s cada); 10 no período anterior (7–14 d); 2 a 100 d; outros setores: 40 erros."""
    agora = timezone.now()
    for e in list(M.Execucao.objects.all()):
        e.delete()
    f = mundo.fA
    for i in range(15):
        mk_exec(f, mundo.bA if i % 2 else mundo.bA2, "sucesso", agora - timedelta(hours=2 + i * 8))  # até ~5 dias
    for i in range(5):
        mk_exec(f, mundo.bA, "erro", agora - timedelta(hours=3 + i * 20))
    for i in range(10):
        mk_exec(f, mundo.bA2, "sucesso", agora - timedelta(days=8 + i * 0.5))
    for i in range(2):
        mk_exec(f, mundo.bA, "sucesso", agora - timedelta(days=100 + i))
    mk_exec(f, mundo.bA, "sucesso", agora - timedelta(days=300))
    for i in range(40):
        mk_exec(mundo.fB, mundo.bB, "erro", agora - timedelta(hours=1 + i))
    mundo.agora = agora
    return mundo


# ---------- HOM-01 acesso ----------

def test_hom01_anonimo_login(cliente_anonimo):
    """PRM-01/HOM-01: anônimo na Home → login."""
    r = cliente_anonimo.get(reverse("inicio"))
    assert r.status_code == 302 and r.url.startswith(reverse("login"))


def test_hom01_sem_papel_403(cliente_sem_papel):
    """HOM-01/PAP-02: sem papel → 403 (tela do produto)."""
    assert cliente_sem_papel.get(reverse("inicio")).status_code == 403


@pytest.mark.parametrize("quem", ["adm", "gA", "bA"])
def test_hom01_todos_os_papeis_abrem_home_sem_redirect(mundo, quem):
    """HOM-01: `inicio` deixa de redirecionar: 200 com título "Início"."""
    r = _home(mundo.c[quem])
    assert r.status_code == 200 and "Início" in _h(r)


@pytest.mark.parametrize("quem", ["adm", "gA", "bA"])
def test_hom01_sidebar_tem_inicio_no_topo(mundo, quem):
    """HOM-01: item "Início" no topo da sidebar, antes de Fluxos."""
    h = _texto(_h(_home(mundo.c[quem])))
    assert h.index("Início") < h.index("Fluxos")
    assert f'href="{reverse("inicio")}"' in _h(_home(mundo.c[quem]))


@pytest.mark.parametrize("quem", ["gA", "bA"])
def test_hom01_nada_fora_do_escopo(cenario, quem):
    """HOM-01/SET-06: nenhum nome de fluxo nem link de execução de outro setor na Home."""
    w = cenario
    h = _h(_home(w.c[quem], periodo="1a"))
    assert w.fB.nome not in h and w.fBr.nome not in h and "Setor Beta" not in h
    assert reverse("execucoes:detalhe", kwargs={"pk": w.eB_bB.pk}) not in h


def test_hom01_base_so_ve_links_das_proprias(mundo, mk_exec):
    """HOM-01/SET-06: Base só vê links das execuções que ele executou."""
    pa = mk_exec(mundo.fA, mundo.bA)
    pb = mk_exec(mundo.fA, mundo.bA2)
    h = _h(_home(mundo.c["bA"]))
    assert reverse("execucoes:detalhe", kwargs={"pk": pa.pk}) in h
    assert reverse("execucoes:detalhe", kwargs={"pk": pb.pk}) not in h


# ---------- HOM-02 período ----------

@pytest.mark.parametrize("p", ["24h", "7d", "30d", "6m", "1a"])
def test_hom02_seletor_tem_todos_os_periodos(mundo, p):
    """HOM-02: controle segmentado oferece ?periodo=24h|7d|30d|6m|1a."""
    assert f"periodo={p}" in _h(_home(mundo.c["adm"]))


@pytest.mark.parametrize("p,esperado", [("24h", 5 + 3), ("7d", 20), ("30d", 30), ("6m", 32), ("1a", 33)])
def test_hom02_execucoes_no_periodo_adm_so_setor_a_filtrado(cenario, p, esperado):
    """HOM-02/03: contagem de execuções do período para o gestor A (janela relativa ao agora)."""
    h = _h(_home(cenario.c["gA"], periodo=p))
    if p == "24h":
        # execuções do setor A nas últimas 24 h: 2h,10h,18h (sucesso) e 3h,23h (erro) = 5
        esperado = 5
    assert _tem_valor(h, "Execuções no período", esperado), _cartao(h, "Execuções no período")


@pytest.mark.parametrize("p", ["", "x", "7D", "99d", "<script>alert(1)</script>", "7d;drop", "24h&periodo=1a"])
def test_hom02_periodo_invalido_usa_padrao_7d(cenario, p):
    """HOM-02: valor inválido → padrão 7d (mesmo resultado que sem parâmetro), nunca 500, nunca refletido."""
    ref = _home(cenario.c["gA"])
    r = cenario.c["gA"].get(reverse("inicio"), {"periodo": p})
    assert r.status_code == 200
    assert _cartao(_h(r), "Execuções no período") == _cartao(_h(ref), "Execuções no período")
    assert "<script>alert(1)</script>" not in _h(r)


def test_hom02_padrao_e_7d(cenario):
    """HOM-02: sem parâmetro = 7d."""
    assert _tem_valor(_h(_home(cenario.c["gA"])), "Execuções no período", 20)


# ---------- HOM-03 cartões ----------

def test_hom03_cartoes_gestor_batem(cenario):
    """HOM-03/SET-06: gestor A, 7d — 20 execuções, taxa 75%, 5 com erro, duração 2 s, fluxos ativos 1 / rascunho 1."""
    h = _h(_home(cenario.c["gA"]))
    assert _tem_valor(h, "Execuções no período", 20)
    assert _tem_valor(h, "Taxa de sucesso", 75)
    assert _tem_valor(h, "Execuções com erro", 5)
    assert any(re.search(r"(?<![\d,.])2([.,]0+)?\s*s", seg) for seg in _cartao(h, "Duração média"))
    assert _tem_valor(h, "Fluxos ativos", 1)
    assert _tem_valor(h, "Fluxos em rascunho", 1)


def test_hom03_adm_soma_todos_os_setores(cenario):
    """HOM-03/SET-06: Adm 7d = 20 (A) + 40 (B) = 60 execuções, 45 com erro, taxa 25%."""
    h = _h(_home(cenario.c["adm"]))
    assert _tem_valor(h, "Execuções no período", 60)
    assert _tem_valor(h, "Execuções com erro", 45)
    assert _tem_valor(h, "Taxa de sucesso", 25)
    assert _tem_valor(h, "Fluxos ativos", 2) and _tem_valor(h, "Fluxos em rascunho", 2)


def test_hom03_cartoes_independem_do_periodo_para_fluxos(cenario):
    """HOM-03: fluxos ativos/rascunho são estado atual, não dependem do período."""
    for p in ("24h", "1a"):
        h = _h(_home(cenario.c["gA"], periodo=p))
        assert _tem_valor(h, "Fluxos ativos", 1) and _tem_valor(h, "Fluxos em rascunho", 1)


def test_hom03_base_so_as_proprias(cenario):
    """HOM-03/SET-06: Base A (bA) conta só as próprias: 5 erros + sucessos ímpares."""
    w = cenario
    h = _h(_home(w.c["bA"]))
    assert _tem_valor(h, "Execuções com erro", 5)
    assert not _tem_valor(h, "Execuções no período", 20)


def test_hom03_base_ve_fluxos_ativos_do_setor_sem_rascunho(cenario):
    """HOM-03/SET-06: Base conta só fluxos ATIVOS do setor (1); rascunho não é visível a ele."""
    h = _h(_home(cenario.c["bA"]))
    assert _tem_valor(h, "Fluxos ativos", 1)
    if "Fluxos em rascunho" in _texto(h):
        assert _tem_valor(h, "Fluxos em rascunho", 0)


def test_hom03_usuarios_ativos_por_papel(cenario, M):
    """HOM-03: Usuários ativos — Adm: total; gestor: do setor; Base: não exibe."""
    w = cenario
    total = M.Usuario.objects.filter(is_active=True).count()
    do_setor = M.Usuario.objects.filter(is_active=True, setor=w.A).count()
    assert _tem_valor(_h(_home(w.c["adm"])), "Usuários ativos", total)
    assert _tem_valor(_h(_home(w.c["gA"])), "Usuários ativos", do_setor)
    assert "Usuários ativos" not in _texto(_h(_home(w.c["bA"])))


def test_hom03_usuarios_ativos_ignora_inativos(cenario, mk_usuario, M):
    """HOM-03: usuário inativo não conta como ativo."""
    w = cenario
    u = mk_usuario("Base", w.A)
    antes = M.Usuario.objects.filter(is_active=True, setor=w.A).count()
    u.is_active = False
    u.save()
    assert _tem_valor(_h(_home(w.c["gA"])), "Usuários ativos", antes - 1)


def test_hom03_setores_ativos_so_adm(cenario, M):
    """HOM-03: Setores ativos só para Adm (valor = setores ativos no banco, inclui Geral)."""
    w = cenario
    n = M.Setor.objects.filter(ativo=True).count()
    assert _tem_valor(_h(_home(w.c["adm"])), "Setores ativos", n)
    for k in ("gA", "bA"):
        assert "Setores ativos" not in _texto(_h(_home(w.c[k])))


def test_hom03_variacao_vs_periodo_anterior(cenario):
    """HOM-03: variação vs período anterior equivalente: 20 vs 10 execuções = +100%."""
    h = _texto(_h(_home(cenario.c["gA"])))
    assert re.search(r"100\s*%", h)


def test_hom03_periodo_anterior_vazio_nao_quebra(mundo, mk_exec):
    """HOM-03: sem dados no período anterior (divisão por zero) → 200, sem NaN/inf/None."""
    mk_exec(mundo.fA, mundo.bA)
    r = _home(mundo.c["gA"])
    t = _texto(_h(r))
    assert r.status_code == 200 and not re.search(r"\b(nan|inf|None|Infinity)\b", t, re.I)


def test_hom03_taxa_sem_execucoes_nao_quebra(mundo):
    """HOM-03: zero execuções → taxa sem divisão por zero (200)."""
    r = _home(mundo.c["gB"])
    assert r.status_code == 200 and "Taxa de sucesso" in _texto(_h(r))


def test_hom03_execucoes_executando_nao_contam_como_sucesso_nem_erro(mundo, mk_exec):
    """HOM-03: execução em andamento não entra como erro."""
    mk_exec(mundo.fA, mundo.bA, "executando")
    mk_exec(mundo.fA, mundo.bA, "sucesso")
    h = _h(_home(mundo.c["gA"]))
    assert _tem_valor(h, "Execuções com erro", 0)


# ---------- HOM-04 gráfico ----------

@pytest.mark.parametrize("p,lo,hi", [("24h", 24, 24), ("7d", 7, 8), ("30d", 30, 31), ("6m", 26, 28), ("1a", 12, 13)])
def test_hom04_numero_de_intervalos(cenario, p, lo, hi):
    """HOM-04: 24h por hora (24); 7d/30d por dia; 6m por semana; 1a por mês — via json_script."""
    assert _serie(_h(_home(cenario.c["gA"], periodo=p)), lo, hi) is not None


def test_hom04_intervalos_sem_dados_com_zero(mundo, mk_exec):
    """HOM-04: uma única execução → quase todos os 24 intervalos com zero (nenhum omitido)."""
    mk_exec(mundo.fA, mundo.bA, quando=timezone.now() - timedelta(hours=5))
    s = _serie(_h(_home(mundo.c["gA"], periodo="24h")), 24, 24)
    assert s is not None
    zeros = sum(1 for x in s if sum(_numeros(x)) == 0)
    assert zeros >= 22


def test_hom04_soma_da_serie_bate_com_cartao(cenario):
    """HOM-04/HOM-03: soma das barras (sucesso+erro) = Execuções no período."""
    s = _serie(_h(_home(cenario.c["gA"])), 7, 8)
    assert s is not None
    assert sum(sum(_numeros(x)) for x in s) >= 20


def test_hom04_acessibilidade(cenario):
    """HOM-04: título do gráfico e tabela de dados equivalente."""
    h = _h(_home(cenario.c["gA"]))
    assert "Execuções no período" in h and "<table" in h


def test_hom04_sem_dados_no_periodo_mostra_aviso_e_zeros(mundo):
    """HOM-04/07: sem dados no período → gráfico com zeros + aviso, 200."""
    r = _home(mundo.c["gB"], periodo="24h")
    assert r.status_code == 200 and _serie(_h(r), 24, 24) is not None


# ---------- HOM-05 ----------

def test_hom05_titulos(cenario):
    """HOM-05: seções "Erros por categoria" e "Fluxos mais executados"; "Execuções por setor" só Adm."""
    for k in ("adm", "gA", "bA"):
        h = _texto(_h(_home(cenario.c[k])))
        assert "Erros por categoria" in h and "Fluxos mais executados" in h
    assert "Execuções por setor" in _texto(_h(_home(cenario.c["adm"])))
    for k in ("gA", "bA"):
        assert "Execuções por setor" not in _texto(_h(_home(cenario.c[k])))


def test_hom05_ranking_top5(mundo, mk_fluxo, mk_exec):
    """HOM-05: ranking mostra só os 5 fluxos mais executados do escopo; os demais ficam de fora."""
    agora = timezone.now()
    fl = [mk_fluxo(mundo.A, mundo.gA, f"Ranking Fluxo {i}") for i in range(1, 8)]
    for i, f in enumerate(fl):
        n = 7 - i
        for j in range(n):
            # os fluxos 6 e 7 são os mais antigos (fora das 10 últimas execuções)
            quando = agora - timedelta(days=5, hours=j) if i >= 5 else agora - timedelta(minutes=5 + j)
            mk_exec(f, mundo.bA, quando=quando)
    h = _h(_home(mundo.c["gA"]))
    for i in range(1, 6):
        assert f"Ranking Fluxo {i}" in h
    assert "Ranking Fluxo 6" not in h and "Ranking Fluxo 7" not in h


def test_hom05_ranking_nao_inclui_outro_setor(mundo, mk_fluxo, mk_exec):
    """HOM-05/SET-06: fluxo muito executado de outro setor nunca aparece no ranking do gestor."""
    f = mk_fluxo(mundo.B, mundo.gB, "Campeao Do Setor Beta")
    for _ in range(9):
        mk_exec(f, mundo.bB)
    assert "Campeao Do Setor Beta" not in _h(_home(mundo.c["gA"]))
    assert "Campeao Do Setor Beta" in _h(_home(mundo.c["adm"]))


def test_hom05_erros_por_categoria_escopo(mundo, mk_exec, M):
    """HOM-05/SEG-10: categorias de erro só do escopo (categoria exclusiva do setor B não vaza ao gestor A)."""
    No = __import__("django.apps", fromlist=["apps"]).apps.get_model("execucoes", "ExecucaoNo")
    for setor_fluxo, por, cat in ((mundo.fA, mundo.bA, "timeout"), (mundo.fB, mundo.bB, "bloqueado_ssrf")):
        e = mk_exec(setor_fluxo, por, "erro")
        No.objects.create(execucao=e, no_id="n2", no_tipo="http", no_titulo="Buscar", ordem=2, status="erro", entrada={},
                          saida={}, erro_categoria=cat, erro_mensagem="m", duracao_ms=5)
    blocos = json.dumps(_blocos_json(_h(_home(mundo.c["gA"]))))
    assert "bloqueado_ssrf" not in blocos and "timeout" in blocos


# ---------- HOM-06 ----------

def test_hom06_ultimas_10_mais_recentes(mundo, mk_exec):
    """HOM-06: "Últimas execuções" = 10 mais recentes do escopo, com link ao detalhe."""
    agora = timezone.now()
    es = [mk_exec(mundo.fA, mundo.bA, quando=agora - timedelta(minutes=i)) for i in range(12)]
    h = _h(_home(mundo.c["gA"]))
    for e in es[:10]:
        assert reverse("execucoes:detalhe", kwargs={"pk": e.pk}) in h
    for e in es[10:]:
        assert reverse("execucoes:detalhe", kwargs={"pk": e.pk}) not in h


def test_hom06_ultimas_independe_do_periodo(mundo, mk_exec):
    """HOM-06: a lista de últimas execuções é das mais recentes do escopo (mostra mesmo fora da janela de 24h)."""
    e = mk_exec(mundo.fA, mundo.bA, quando=timezone.now() - timedelta(days=20))
    assert reverse("execucoes:detalhe", kwargs={"pk": e.pk}) in _h(_home(mundo.c["gA"], periodo="24h"))


def test_hom06_atalhos(mundo):
    """HOM-06: "Novo fluxo" para quem cria (Adm, Coordenador), não para Base; "Ver todas as execuções" para todos."""
    for k in ("adm", "gA"):
        assert "Novo fluxo" in _h(_home(mundo.c[k]))
    assert "Novo fluxo" not in _h(_home(mundo.c["bA"]))
    for k in ("adm", "gA", "bA"):
        h = _h(_home(mundo.c[k]))
        assert "Ver todas as execuções" in h and reverse("execucoes:lista") in h


def test_hom06_numeros_batem_com_a_lista(cenario):
    """HOM-01/06: número "Execuções no período" da Home = linhas do histórico do mesmo usuário (todas na janela, ≤ 25)."""
    from django.apps import apps
    w = cenario
    apps.get_model("execucoes", "Execucao").objects.filter(iniciada_em__lt=w.agora - timedelta(days=6)).delete()
    for k in ("gA", "bA", "adm"):
        r = w.c[k].get(reverse("execucoes:lista"), {"pagina": 1})
        total = len(set(re.findall(r"/execucoes/(\d+)/", _h(r))))
        pagina_unica = total < 25
        if pagina_unica:
            assert _tem_valor(_h(_home(w.c[k])), "Execuções no período", total), (k, total)


# ---------- HOM-07 estados ----------

def test_hom07_vazio_com_botao_para_quem_cria(db, M, mk_usuario, logar, mk_setor):
    """HOM-07: sem fluxos/execuções → estado vazio com mensagem e botão Novo fluxo (Adm/Coordenador)."""
    M.Execucao.objects.all().delete()
    M.Fluxo.objects.all().delete()
    s = mk_setor("Setor Vazio")
    r = _home(logar(mk_usuario("Coordenador", s)))
    assert r.status_code == 200 and "Novo fluxo" in _h(r)
    r = _home(logar(mk_usuario("Adm")))
    assert r.status_code == 200 and "Novo fluxo" in _h(r)


def test_hom07_vazio_base_sem_botao(db, M, mk_usuario, logar, mk_setor):
    """HOM-07: Base no estado vazio não vê Novo fluxo."""
    M.Execucao.objects.all().delete()
    M.Fluxo.objects.all().delete()
    r = _home(logar(mk_usuario("Base", mk_setor("Setor Vazio 2"))))
    assert r.status_code == 200 and "Novo fluxo" not in _h(r)


@pytest.mark.parametrize("p", ["24h", "7d", "30d", "6m", "1a"])
def test_hom07_todos_os_periodos_respondem_200_para_todos(cenario, p):
    """HOM-02/07: nenhum período quebra para nenhum papel."""
    for k in ("adm", "gA", "bA"):
        assert _home(cenario.c[k], periodo=p).status_code == 200


def test_hom07_xss_em_nome_de_fluxo_e_usuario(mundo, mk_fluxo, mk_exec, mk_usuario):
    """SEG-13/HOM-05/06: nome de fluxo e de usuário com <script> são escapados na Home."""
    u = mk_usuario("Base", mundo.A, nome="<script>x(1)</script>")
    f = mk_fluxo(mundo.A, mundo.gA, "<img src=x onerror=y(1)>")
    mk_exec(f, u)
    h = _h(_home(mundo.c["gA"]))
    assert "<script>x(1)</script>" not in h and "<img src=x onerror=y(1)>" not in h


# ---------- HOM-08 técnico ----------

def _bulk(M, fluxo, por, n, agora):
    import copy

    M.Execucao.objects.bulk_create([
        M.Execucao(fluxo=fluxo, fluxo_nome=fluxo.nome, grafo_snapshot=copy.deepcopy(fluxo.grafo), executado_por=por,
                   status="erro" if i % 4 == 0 else "sucesso", iniciada_em=agora - timedelta(minutes=i * 7),
                   finalizada_em=agora - timedelta(minutes=i * 7) + timedelta(seconds=2), erro_resumo="", setor=fluxo.setor)
        for i in range(n)], batch_size=1000)


@pytest.mark.parametrize("quem", ["adm", "gA", "bA"])
@pytest.mark.parametrize("p", ["24h", "1a"])
def test_hom08_queries_constantes(mundo, M, quem, p):
    """HOM-08: nº de queries da Home independe do volume (1 vs 200 execuções)."""
    def conta():
        with CaptureQueriesContext(connection) as q:
            mundo.c[quem].get(reverse("inicio"), {"periodo": p})
        return len(q)
    agora = timezone.now()
    _bulk(M, mundo.fA, mundo.bA, 1, agora)
    a = conta()
    _bulk(M, mundo.fA, mundo.bA, 200, agora)
    assert conta() == a


def test_hom08_queries_constantes_com_mais_fluxos_e_setores(mundo, M, mk_fluxo, mk_setor):
    """HOM-08: ranking e "Execuções por setor" sem N+1 (mais fluxos e setores, mesma contagem de queries)."""
    agora = timezone.now()
    _bulk(M, mundo.fA, mundo.bA, 5, agora)
    with CaptureQueriesContext(connection) as q:
        mundo.c["adm"].get(reverse("inicio"))
    a = len(q)
    for i in range(12):
        s = mk_setor(f"Setor Extra {i}")
        f = mk_fluxo(s, mundo.adm, f"Fluxo Extra {i}")
        _bulk(M, f, mundo.adm, 3, agora)
    with CaptureQueriesContext(connection) as q:
        mundo.c["adm"].get(reverse("inicio"))
    assert len(q) == a


def test_hom08_dez_mil_execucoes_abaixo_de_300ms(mundo, M):
    """HOM-08: Home < 300 ms com 10 mil execuções (após aquecimento)."""
    _bulk(M, mundo.fA, mundo.bA, 10000, timezone.now())
    mundo.c["adm"].get(reverse("inicio"))
    t = time.perf_counter()
    r = mundo.c["adm"].get(reverse("inicio"), {"periodo": "1a"})
    dt = time.perf_counter() - t
    assert r.status_code == 200 and dt < 0.3, f"{dt * 1000:.0f} ms"


def test_hom08_dados_via_json_script_sem_cdn(cenario):
    """HOM-08: dados dos gráficos via json_script e nenhuma biblioteca de CDN."""
    h = _h(_home(cenario.c["adm"]))
    assert _blocos_json(h)
    assert not re.search(r'(src|href)="https?://', h)


def test_hom08_indices(db):
    """HOM-08: índices em (setor, iniciada_em) e (status, iniciada_em) na tabela de execuções."""
    with connection.cursor() as c:
        c.execute("select indexdef from pg_indexes where tablename = 'execucoes_execucao'")
        defs = " ".join(r[0] for r in c.fetchall())
    assert re.search(r"\(setor_id, iniciada_em", defs), defs
    assert re.search(r"\(status, iniciada_em", defs), defs
