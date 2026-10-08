"""Aceite M3 · "o fluxo que aconteceu" (T-036). Fonte: EXE-15 (+ SEG-09, SEG-13, PRM-02/04, EXE-03, EXE-09). TEL-06/TEL-07.

Só pela spec: sem seletores definidos, verificamos conteúdo no HTML servido (texto, links, escape), não classes CSS.
"""

import copy
import re
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m3")]

MASCARA = "••••"
XSS = "<script>alert('xss-titulo')</script>"
IMG = '<img src=x onerror="alert(1)">'


def _h(r):
    return r.content.decode()


def _detalhe(cliente, e):
    r = cliente.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk}))
    assert r.status_code == 200
    return _h(r)


@pytest.fixture
def fabrica_execucao(modelos, usuario_adm):
    def _criar(grafo, executado_por=None, nome="Fluxo X", status="sucesso", fluxo=None, nos=()):
        inicio = timezone.now() - timedelta(minutes=1)
        e = modelos.Execucao.objects.create(
            fluxo=fluxo,
            fluxo_nome=nome,
            grafo_snapshot=grafo,
            executado_por=executado_por or usuario_adm,
            status=status,
            iniciada_em=inicio,
            finalizada_em=inicio + timedelta(seconds=2),
            erro_resumo="",
        )
        for ordem, (no_id, tipo, titulo, st) in enumerate(nos, 1):
            modelos.ExecucaoNo.objects.create(
                execucao=e,
                no_id=no_id,
                no_tipo=tipo,
                no_titulo=titulo,
                ordem=ordem,
                status=st,
                entrada={},
                saida={},
                erro_categoria=None,
                erro_mensagem="",
                duracao_ms=10,
            )
        return e

    return _criar


def _grafo(titulos):
    nos = [
        {
            "id": "g",
            "tipo": "gatilho",
            "titulo": titulos[0],
            "posicao": {"x": 0, "y": 0},
            "config": {},
        },
        {
            "id": "h1",
            "tipo": "http",
            "titulo": titulos[1],
            "posicao": {"x": 200, "y": 0},
            "config": {
                "metodo": "GET",
                "url": "https://api.exemplo.test/x",
                "headers": [],
                "query": [],
                "corpo": "",
            },
        },
        {
            "id": "s",
            "tipo": "saida",
            "titulo": titulos[2],
            "posicao": {"x": 400, "y": 0},
            "config": {},
        },
    ]
    return {
        "versao": 1,
        "nos": nos,
        "arestas": [{"de": "g", "para": "h1"}, {"de": "h1", "para": "s"}],
    }


# ---------- (a) linha clicável ----------


def test_cada_linha_do_historico_tem_link_para_o_detalhe(cliente_adm, fabrica_execucao):
    """EXE-15(a): cada execução listada tem link para o próprio detalhe (linha clicável, não só o nome)."""
    g = _grafo(["A", "B", "C"])
    es = [fabrica_execucao(g, nome=f"Linha {i}") for i in range(3)]
    h = _h(cliente_adm.get(reverse("execucoes:lista")))
    for e in es:
        assert reverse("execucoes:detalhe", kwargs={"pk": e.pk}) in h


def test_linha_do_historico_clicavel_para_base_nas_proprias(
    cliente_base, usuario_base, fabrica_execucao
):
    """EXE-15(a)/PRM-04: Base também clica na própria execução e abre o detalhe (200)."""
    e = fabrica_execucao(_grafo(["A", "B", "C"]), executado_por=usuario_base)
    url = reverse("execucoes:detalhe", kwargs={"pk": e.pk})
    assert url in _h(cliente_base.get(reverse("execucoes:lista")))
    assert cliente_base.get(url).status_code == 200


def test_historico_com_varias_execucoes_do_mesmo_fluxo_tem_links_distintos(
    cliente_adm, fabrica_execucao
):
    """EXE-15(a): execuções do mesmo fluxo não compartilham link; cada linha aponta para a sua."""
    g = _grafo(["A", "B", "C"])
    e1, e2 = fabrica_execucao(g, nome="Mesmo"), fabrica_execucao(g, nome="Mesmo")
    h = _h(cliente_adm.get(reverse("execucoes:lista")))
    u1, u2 = (reverse("execucoes:detalhe", kwargs={"pk": e.pk}) for e in (e1, e2))
    assert u1 != u2 and u1 in h and u2 in h


# ---------- (b) desenho = snapshot ----------


def test_detalhe_desenha_o_snapshot_nao_o_grafo_atual(cliente_adm, fabrica_fluxo, fabrica_execucao):
    """EXE-15(b,e)/EXE-03: depois de editar o fluxo, o detalhe segue mostrando os títulos do snapshot e não os atuais."""
    antigo = _grafo(["Inicio Antigo", "Buscar Antigo", "Saida Antiga"])
    f = fabrica_fluxo(grafo=antigo, status="ativo")
    e = fabrica_execucao(antigo, fluxo=f, nome=f.nome)
    novo = copy.deepcopy(antigo)
    novo["nos"][1]["titulo"] = "TITULO-ATUAL-NOVO"
    f.grafo = novo
    f.save()
    h = _detalhe(cliente_adm, e)
    assert "TITULO-ATUAL-NOVO" not in h
    for t in ("Inicio Antigo", "Buscar Antigo", "Saida Antiga"):
        assert t in h


def test_desenho_vem_do_snapshot_mesmo_sem_registros_de_no(cliente_adm, fabrica_execucao):
    """EXE-15(b): o desenho usa o grafo_snapshot; um título que só existe no snapshot aparece no detalhe."""
    e = fabrica_execucao(_grafo(["Marca Gatilho Zq", "Marca Http Zq", "Marca Saida Zq"]), nos=())
    h = _detalhe(cliente_adm, e)
    assert all(t in h for t in ("Marca Gatilho Zq", "Marca Http Zq", "Marca Saida Zq"))


def test_detalhe_do_fluxo_excluido_ainda_desenha_o_snapshot(
    cliente_adm, fabrica_fluxo, fabrica_execucao
):
    """EXE-15(e)/EXE-03: excluído o fluxo, o desenho do histórico permanece."""
    g = _grafo(["Gat Excl", "Http Excl", "Sai Excl"])
    f = fabrica_fluxo(grafo=g)
    e = fabrica_execucao(g, fluxo=f, nome=f.nome)
    f.delete()
    h = _detalhe(cliente_adm, e)
    assert "Http Excl" in h


def test_detalhe_mostra_status_por_no_e_ordem(cliente_adm, fabrica_execucao):
    """EXE-15(b)/EXE-05: nós com sucesso, erro e não executado aparecem no detalhe, na ordem de execução."""
    g = _grafo(["Gat Ord", "Http Ord", "Sai Ord"])
    e = fabrica_execucao(
        g,
        status="erro",
        nos=[
            ("g", "gatilho", "Gat Ord", "sucesso"),
            ("h1", "http", "Http Ord", "erro"),
            ("s", "saida", "Sai Ord", "nao_executado"),
        ],
    )
    pagina = _detalhe(cliente_adm, e)
    inicio = pagina.find("Nós executados")
    assert inicio >= 0, 'lista "Nós executados" (EXE-09) ausente'
    h = pagina[inicio:].lower()
    assert h.index("gat ord") < h.index("http ord") < h.index("sai ord")
    assert "sucesso" in h and "erro" in h and re.search(r"n[ãa]o[ _]executado", h)


def test_desenho_do_http_traz_metodo_host_e_status(
    cliente_coordenador, liberado, executar, cadeia, cfg_http
):
    """EXE-15(b): no nó HTTP, método + host + status HTTP no detalhe de uma execução real."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/ok")))
    h = _detalhe(cliente_coordenador, e)
    assert "GET" in h and "127.0.0.1" in h and "200" in h


# ---------- (d) resumo ----------


def test_resumo_de_sucesso_em_texto(cliente_coordenador, liberado, executar, cadeia, cfg_http):
    """EXE-15(d): '3 de 3 nós executados com sucesso em X s · GET host → 200'."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/ok")))
    h = _detalhe(cliente_coordenador, e)
    assert re.search(r"3 de 3 n[óo]s executados com sucesso em \d+[,.]\d+ s", h), (
        "resumo de sucesso ausente"
    )
    assert re.search(r"GET\s+127\.0\.0\.1\S*\s*→\s*200", h)


def test_resumo_de_erro_aponta_o_no_que_parou(
    cliente_coordenador, liberado, executar, cadeia, cfg_http
):
    """EXE-15(d): erro HTTP → 'Parou no nó 2 (<título>)'."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/status/503")))
    h = _detalhe(cliente_coordenador, e)
    assert re.search(r"Parou no n[óo] 2 \(H1\)", h)


def test_resumo_de_bloqueio_ssrf_em_texto(
    cliente_coordenador, servidor, executar, cadeia, cfg_http
):
    """EXE-15(d): destino bloqueado (servidor local não liberado) → 'Parou no nó 2 (…): destino bloqueado por segurança'."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{servidor.base}/ok")))
    h = _detalhe(cliente_coordenador, e)
    assert re.search(
        r"Parou no n[óo] 2 \(H1\).{0,40}destino bloqueado por seguran[çc]a", h, re.S | re.I
    )
    assert servidor.contagem("/ok") == 0


# ---------- SEG-09 no desenho ----------


def test_segredo_do_header_nao_aparece_no_detalhe_nem_no_desenho(
    cliente_coordenador, liberado, executar, cadeia, cfg_http
):
    """EXE-15(b)/SEG-09: segredo digitado em header/query do nó não vaza em nenhum ponto da página (desenho incluso)."""
    cfg = cfg_http(
        f"{liberado.base}/ok",
        headers=[{"nome": "Authorization", "valor": "Bearer SEGREDO-DESENHO-1"}],
        query=[{"nome": "api-key", "valor": "SEGREDO-DESENHO-2"}],
    )
    _, e, _ = executar(cliente_coordenador, cadeia(cfg))
    h = _detalhe(cliente_coordenador, e)
    assert "SEGREDO-DESENHO-1" not in h and "SEGREDO-DESENHO-2" not in h
    assert MASCARA in h


# ---------- SEG-13 ----------


def test_titulos_hostis_do_snapshot_sao_escapados(cliente_adm, fabrica_execucao):
    """EXE-15/SEG-13: título de nó com <script>/<img onerror> vira texto; nenhuma tag crua na página."""
    g = _grafo([XSS, IMG, "Saida"])
    e = fabrica_execucao(
        g,
        nome=XSS,
        nos=[
            ("g", "gatilho", XSS, "sucesso"),
            ("h1", "http", IMG, "sucesso"),
            ("s", "saida", "Saida", "sucesso"),
        ],
    )
    h = _detalhe(cliente_adm, e)
    assert XSS not in h and IMG not in h and "alert('xss-titulo')</script>" not in h
    assert "<script>alert" not in h and "<img src=x" not in h


def test_titulos_hostis_escapados_na_linha_do_historico(cliente_adm, fabrica_execucao):
    """EXE-15(a)/SEG-13: nome do fluxo hostil na lista é escapado."""
    fabrica_execucao(_grafo(["A", "B", "C"]), nome=XSS)
    h = _h(cliente_adm.get(reverse("execucoes:lista")))
    assert XSS not in h


# ---------- (e) link do editor ----------


@pytest.mark.parametrize("cliente", ["cliente_adm", "cliente_coordenador"])
def test_link_do_editor_para_quem_pode_editar(request, cliente, fabrica_fluxo, fabrica_execucao):
    """EXE-15(e)/PRM-02: Adm e Coordenador veem 'Abrir fluxo no editor' apontando ao fluxo atual."""
    g = _grafo(["A", "B", "C"])
    f = fabrica_fluxo(grafo=g, status="ativo")
    e = fabrica_execucao(g, fluxo=f, nome=f.nome)
    h = _detalhe(request.getfixturevalue(cliente), e)
    assert "Abrir fluxo no editor" in h
    assert reverse("fluxos:editor", kwargs={"pk": f.pk}) in h


def test_base_nao_ve_link_do_editor(cliente_base, usuario_base, fabrica_fluxo, fabrica_execucao):
    """EXE-15(e)/PRM-02: Base (fluxos.editar = nenhum) não recebe o link do editor."""
    g = _grafo(["A", "B", "C"])
    f = fabrica_fluxo(grafo=g, status="ativo")
    e = fabrica_execucao(g, fluxo=f, nome=f.nome, executado_por=usuario_base)
    h = _detalhe(cliente_base, e)
    assert "Abrir fluxo no editor" not in h
    assert reverse("fluxos:editor", kwargs={"pk": f.pk}) not in h


def test_sem_link_do_editor_quando_o_fluxo_foi_excluido(
    cliente_adm, fabrica_fluxo, fabrica_execucao
):
    """EXE-15(e): fluxo inexistente → sem 'Abrir fluxo no editor' (nem link quebrado)."""
    g = _grafo(["A", "B", "C"])
    f = fabrica_fluxo(grafo=g)
    pk = f.pk
    e = fabrica_execucao(g, fluxo=f, nome=f.nome)
    f.delete()
    h = _detalhe(cliente_adm, e)
    assert "Abrir fluxo no editor" not in h
    assert reverse("fluxos:editor", kwargs={"pk": pk}) not in h


def test_link_do_editor_leva_a_pagina_que_abre_para_quem_edita(
    cliente_coordenador, fabrica_fluxo, fabrica_execucao
):
    """EXE-15(e): o link do detalhe abre o editor (200) para o Coordenador."""
    g = _grafo(["A", "B", "C"])
    f = fabrica_fluxo(grafo=g, status="ativo")
    e = fabrica_execucao(g, fluxo=f, nome=f.nome)
    assert "Abrir fluxo no editor" in _detalhe(cliente_coordenador, e)
    assert cliente_coordenador.get(reverse("fluxos:editor", kwargs={"pk": f.pk})).status_code == 200


# ---------- escopo ----------


def test_detalhe_alheio_continua_404_para_base(cliente_base, usuario_coordenador, fabrica_execucao):
    """EXE-11/PRM-03: o desenho não abre brecha; execução de outro usuário → 404 para Base."""
    e = fabrica_execucao(_grafo(["Segredo Alheio", "B", "C"]), executado_por=usuario_coordenador)
    r = cliente_base.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk}))
    assert r.status_code == 404 and "Segredo Alheio" not in _h(r)
