"""Aceite M8 · painel v2 do Cadastro (CAD-24, CAD-25, CAD-26, CAD-27 + bloco `contrato.9_painel_v2`). Só pela spec."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .conftest import campos_dify, cnj, criar_processo

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

SP = ZoneInfo("America/Sao_Paulo")
PAINEL = "juridico:painel"


def _painel(c, **q):
    return c.get(reverse(PAINEL), q)


def _n(i, **kw):
    return cnj(7000 + i, **kw)


def _item(cad, processo=None, status="concluido", etapa=None, resolvido=False, usuario=None, arquivo="", origem="pdf", sha=None, **kw):
    """Prepara um ItemEnvio pelo ORM (CAD-23 permite preparar estado)."""
    e = cad.Envio.objects.create(origem=origem, enviado_por=usuario or cad.ana_u)
    n = cad.ItemEnvio.objects.count() + 1
    return cad.ItemEnvio.objects.create(envio=e, nome_arquivo=f"arq{n}.pdf" if arquivo else "", sha256=sha or f"{n:064d}", status=status, etapa_erro=etapa,
                                        resolvido=resolvido, processo=processo, arquivo=arquivo, **kw)


def _em_sp(ano, mes, dia, h, m):
    return datetime(ano, mes, dia, h, m, tzinfo=SP)


# ---------------- CAD-24/27 · fluxo do cadastro ----------------

def test_contexto_tem_as_chaves_novas_da_cad_27(cad):
    """CAD-27: fluxo, clientes, filtro_audiencia, atualizado_em, selecionado — e nada da CAD-19 foi removido."""
    criar_processo(cad, numero=_n(1))
    ctx = _painel(cad.ana).context
    for k in ("fluxo", "clientes", "filtro_audiencia", "atualizado_em", "selecionado", "resumo", "ultimos_envios", "processos", "filtros", "carteiras",
              "aviso_datajud", "atualizar_auto", "url_status"):
        assert k in ctx, k
    assert {"em_leitura", "erros_leitura", "url_erros", "com_pendencias", "conferir", "cadastrados", "total", "pct_cadastrados"} <= set(ctx["fluxo"])
    assert ctx["filtro_audiencia"] is False and re.fullmatch(r"\d{2}:\d{2}", ctx["atualizado_em"])


def test_em_leitura_conta_na_fila_e_processando_de_todos_os_usuarios_com_acesso(cad, ver):
    """CAD-24a: 'N em leitura' = ItemEnvio na_fila + processando de TODOS os usuários (concluido/erro/ignorado não contam)."""
    _item(cad, status="na_fila", usuario=cad.ana_u, arquivo="juridico/2026/10/a.pdf")
    _item(cad, status="processando", usuario=cad.bruno_u, arquivo="juridico/2026/10/b.pdf")
    _item(cad, status="na_fila", usuario=cad.adm_u, arquivo="juridico/2026/10/c.pdf")
    for st in ("concluido", "erro", "ignorado"):
        _item(cad, status=st, usuario=cad.ana_u, arquivo="juridico/2026/10/d.pdf")
    for c in (cad.ana, cad.bruno, cad.adm):
        r = _painel(c)
        assert r.context["fluxo"]["em_leitura"] == 3
        assert re.search(r"\b3 em leitura\b", ver.texto(r))


def test_erros_de_leitura_so_leitura_e_envio_do_pdf_nao_resolvidos(cad, ver):
    """CAD-24a: 'N com erro de leitura · ver log' = etapa_erro 'Leitura do PDF' ou 'Envio do PDF' com resolvido=false; link para juridico:erros."""
    _item(cad, status="erro", etapa="Leitura do PDF")
    _item(cad, status="erro", etapa="Envio do PDF")
    _item(cad, status="concluido", etapa="Leitura do PDF")                       # também conta (etapa_erro preenchida)
    _item(cad, status="erro", etapa="Leitura do PDF", resolvido=True)            # resolvido: não conta
    _item(cad, status="erro", etapa="IA (Dify)")                                 # outra etapa: não conta
    _item(cad, status="erro", etapa="CNJ (DataJud)")
    _item(cad, status="concluido", etapa="Dados incompletos")
    r = _painel(cad.ana)
    assert r.context["fluxo"]["erros_leitura"] == 3 and r.context["fluxo"]["url_erros"] == reverse("juridico:erros")
    t = ver.texto(r)
    assert re.search(r"\b3 com erro de leitura\b", t) and "ver log" in t and reverse("juridico:erros") in ver.html(r)


def test_fluxo_zerado(cad, ver):
    """CAD-24: sem itens e sem processos tudo zera (pct 0, sem divisão por zero)."""
    f = _painel(cad.ana).context["fluxo"]
    assert (f["em_leitura"], f["erros_leitura"], f["com_pendencias"], f["conferir"], f["cadastrados"], f["total"], f["pct_cadastrados"]) == (0, 0, 0, 0, 0, 0, 0)


def test_esteira_conta_por_status_e_ignora_excluidos(cad, ver):
    """CAD-24b/27: total = com_pendencias + conferir + cadastrados, sem excluídos; título 'N processos extraídos'."""
    for i in range(2):
        criar_processo(cad, numero=_n(i), status="COM_PENDENCIAS", pendencias=["Verificar: Juízo"])
    for i in range(3):
        criar_processo(cad, numero=_n(10 + i), status="CONFERIR")
    criar_processo(cad, numero=_n(20), status="CADASTRADO")
    criar_processo(cad, numero=_n(21), status="CADASTRADO", excluido_em=timezone.now(), excluido_por=cad.adm_u)
    criar_processo(cad, numero=_n(22), status="CONFERIR", excluido_em=timezone.now(), excluido_por=cad.adm_u)
    r = _painel(cad.ana)
    f = r.context["fluxo"]
    assert (f["com_pendencias"], f["conferir"], f["cadastrados"], f["total"]) == (2, 3, 1, 6)
    assert f["total"] == f["com_pendencias"] + f["conferir"] + f["cadastrados"]
    t = ver.texto(r)
    assert re.search(r"\b6 processos extraídos\b", t) and re.search(r"\b17% já cadastrados no Espaider\b", t)


@pytest.mark.parametrize("cadastrados,total,pct", [(1, 8, 13), (1, 3, 33), (2, 3, 67), (0, 5, 0), (5, 5, 100), (1, 200, 1), (1, 40, 3), (3, 8, 38), (1, 6, 17)])
def test_percentual_cadastrado_arredonda_meio_para_cima(cad, ver, cadastrados, total, pct):
    """CAD-27 (contrato): pct_cadastrados = int(round_half_up(cadastrados*100/total)) — 12,5 → 13; 2,5 → 3; 37,5 → 38."""
    for i in range(cadastrados):
        criar_processo(cad, numero=_n(i), status="CADASTRADO")
    for i in range(total - cadastrados):
        criar_processo(cad, numero=_n(100 + i), status="CONFERIR")
    r = _painel(cad.ana)
    assert r.context["fluxo"]["pct_cadastrados"] == pct and isinstance(r.context["fluxo"]["pct_cadastrados"], int)
    assert f"{pct}% já cadastrados no Espaider" in ver.texto(r)


def test_tres_etapas_clicaveis_com_numero_nome_e_legenda(cad, ver):
    """CAD-24b: três ETAPAS (button, aria-pressed) com número, nome e legenda; ordem Com pendências → Conferir → Cadastrado."""
    criar_processo(cad, numero=_n(1), status="COM_PENDENCIAS", pendencias=["Verificar: Juízo"])
    for i in range(2):
        criar_processo(cad, numero=_n(10 + i), status="CONFERIR")
    h = ver.html(_painel(cad.ana))
    botoes = re.findall(r"<button\b[^>]*aria-pressed=\"(?:true|false)\"[^>]*>.*?</button>", h, re.S)
    etapas = [b for b in botoes if any(leg in b for leg in ("falta campo obrigatório", "7 de 7 campos, revisão humana", "lançado no Espaider"))]
    assert len(etapas) == 3
    legendas = [next(leg for leg in ("falta campo obrigatório", "7 de 7 campos, revisão humana", "lançado no Espaider") if leg in b) for b in etapas]
    assert legendas == ["falta campo obrigatório", "7 de 7 campos, revisão humana", "lançado no Espaider"]
    txt = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", b)).strip() for b in etapas]
    assert re.search(r"\b1\b", txt[0]) and "Com pendências" in txt[0]
    assert re.search(r"\b2\b", txt[1]) and "Conferir" in txt[1]
    assert re.search(r"\b0\b", txt[2]) and "Cadastrado" in txt[2]


@pytest.mark.parametrize("status,indice", [("COM_PENDENCIAS", 0), ("CONFERIR", 1), ("CADASTRADO", 2)])
def test_etapa_ativa_tem_aria_pressed_true_e_filtra_a_lista(cad, ver, status, indice):
    """CAD-24b: ?status= marca SÓ a etapa correspondente com aria-pressed=true e filtra a lista; sem filtro todas false."""
    criar_processo(cad, numero=_n(1), status="COM_PENDENCIAS", pendencias=["Verificar: Juízo"])
    criar_processo(cad, numero=_n(2), status="CONFERIR")
    criar_processo(cad, numero=_n(3), status="CADASTRADO")
    legendas = ("falta campo obrigatório", "7 de 7 campos, revisão humana", "lançado no Espaider")

    def estados(r):
        h = ver.html(r)
        bs = [b for b in re.findall(r"<button\b[^>]*aria-pressed=\"(?:true|false)\"[^>]*>.*?</button>", h, re.S) if any(leg in b for leg in legendas)]
        return [re.search(r'aria-pressed="(true|false)"', b).group(1) for b in bs]
    assert estados(_painel(cad.ana)) == ["false"] * 3
    r = _painel(cad.ana, status=status)
    esperado = ["false"] * 3
    esperado[indice] = "true"
    assert estados(r) == esperado
    assert [p["status"] for p in r.context["processos"]] == [status]


def test_barra_em_escala_tem_um_segmento_por_etapa_proporcional(cad, ver):
    """CAD-24b: barra com um segmento por etapa, ordem Com pendências → Conferir → Cadastrado, largura proporcional (1:2:1 → 25%/50%/25%)."""
    criar_processo(cad, numero=_n(1), status="COM_PENDENCIAS", pendencias=["x"])
    for i in range(2):
        criar_processo(cad, numero=_n(10 + i), status="CONFERIR")
    criar_processo(cad, numero=_n(20), status="CADASTRADO")
    h = ver.html(_painel(cad.ana))
    larguras = re.findall(r"width:\s*([\d.]+)%", h)
    esperadas = [25.0, 50.0, 25.0]
    achado = [float(x) for x in larguras]
    # os três segmentos aparecem nessa ordem, em algum ponto da página
    for i in range(len(achado) - 2):
        if all(abs(achado[i + k] - esperadas[k]) < 0.6 for k in range(3)):
            break
    else:
        pytest.fail(f"segmentos 25/50/25 não encontrados em ordem: {achado}")


def test_topo_com_titulo_atualizado_botoes(cad, ver):
    """CAD-24: topo com título, 'Atualizado às HH:MM', 'Audiências (n)' (aria-pressed), 'Menu' e '+ Enviar PDFs'."""
    r = _painel(cad.ana)
    t = ver.texto(r)
    assert "Painel de Processos" in t and "Menu" in t and "+ Enviar PDFs" in t and "Audiências (0)" in t
    assert re.search(r"Atualizado às \d{2}:\d{2}", t) and f"Atualizado às {r.context['atualizado_em']}" in t
    h = ver.html(r)
    botao = re.search(r"<(?:a|button)\b[^>]*>\s*(?:<[^>]+>\s*)*Audiências \(0\)", h)
    assert botao and "aria-pressed" in botao.group(0)
    assert reverse("juridico:enviar_pdfs") in h


def test_atualizado_em_e_a_hora_local_da_renderizacao(cad):
    """CAD-27 (contrato): atualizado_em = 'HH:MM' no fuso local."""
    antes = timezone.localtime().strftime("%H:%M")
    r = _painel(cad.ana)
    depois = timezone.localtime().strftime("%H:%M")
    assert r.context["atualizado_em"] in {antes, depois}


# ---------------- filtros ----------------

def test_filtro_audiencia_so_futuras_e_marca_o_botao(cad, ver):
    """CAD-24/27: ?audiencia=1 → só processos com proxima_audiencia >= agora; filtro_audiencia=True; botão aria-pressed=true."""
    a = criar_processo(cad, numero=_n(1), proxima_audiencia=timezone.now() + timedelta(days=3))
    criar_processo(cad, numero=_n(2), proxima_audiencia=timezone.now() - timedelta(days=3))
    criar_processo(cad, numero=_n(3), proxima_audiencia=None)
    r = _painel(cad.ana, audiencia=1)
    assert [p["pk"] for p in r.context["processos"]] == [a.pk] and r.context["filtro_audiencia"] is True
    h = ver.html(r)
    assert re.search(r'aria-pressed="true"[^>]*>\s*(?:<[^>]+>\s*)*Audiências \(1\)|Audiências \(1\)[^<]*</[^>]+>.*?aria-pressed="true"', h, re.S) or \
        re.search(r'<(?:a|button)\b[^>]*aria-pressed="true"[^>]*>(?:(?!</(?:a|button)>).)*Audiências \(1\)', h, re.S)
    assert _painel(cad.ana).context["filtro_audiencia"] is False


def test_filtros_combinam_em_and(cad):
    """CAD-27 (contrato): ?status, ?carteira, ?audiencia, ?q, ?cnj combinam em AND; excluídos nunca entram."""
    fut = timezone.now() + timedelta(days=5)
    alvo = criar_processo(cad, numero=_n(1), status="CONFERIR", carteira=cad.carteiras["Ailos"], proxima_audiencia=fut, adverso_nome="Zé Alvo", cnj_validacao="confere")
    criar_processo(cad, numero=_n(2), status="CONFERIR", carteira=cad.carteiras["Ailos"], proxima_audiencia=None, adverso_nome="Zé Alvo")
    criar_processo(cad, numero=_n(3), status="CADASTRADO", carteira=cad.carteiras["Ailos"], proxima_audiencia=fut, adverso_nome="Zé Alvo")
    criar_processo(cad, numero=_n(4), status="CONFERIR", carteira=cad.carteiras["Ativos"], proxima_audiencia=fut, adverso_nome="Zé Alvo")
    criar_processo(cad, numero=_n(5), status="CONFERIR", carteira=cad.carteiras["Ailos"], proxima_audiencia=fut, adverso_nome="Outro")
    criar_processo(cad, numero=_n(6), status="CONFERIR", carteira=cad.carteiras["Ailos"], proxima_audiencia=fut, adverso_nome="Zé Alvo", excluido_em=timezone.now(), excluido_por=cad.adm_u)
    r = _painel(cad.ana, status="CONFERIR", carteira=cad.carteiras["Ailos"].pk, audiencia=1, q="Alvo", cnj="confere")
    assert [p["pk"] for p in r.context["processos"]] == [alvo.pk]


def test_filtro_carteira_outros_e_so_sem_carteira(cad):
    """CAD-27 (contrato): ?carteira=outros → processos SEM carteira; combina com os demais filtros."""
    sem = criar_processo(cad, numero=_n(1), carteira=None, status="CONFERIR")
    criar_processo(cad, numero=_n(2), carteira=None, status="CADASTRADO")
    criar_processo(cad, numero=_n(3), carteira=cad.carteiras["Ativos"], status="CONFERIR")
    assert len(_painel(cad.ana, carteira="outros").context["processos"]) == 2
    assert [p["pk"] for p in _painel(cad.ana, carteira="outros", status="CONFERIR").context["processos"]] == [sem.pk]


def test_vazio_com_filtros(cad, ver):
    """CAD-24: sem resultados nos filtros → 'Nenhum processo com esses filtros. Limpe a busca ou escolha outro cliente.'"""
    criar_processo(cad, numero=_n(1), status="CONFERIR")
    t = ver.texto(_painel(cad.ana, status="CADASTRADO"))
    assert "Nenhum processo com esses filtros" in t and "Limpe a busca ou escolha outro cliente." in t


# ---------------- clientes ----------------

def test_clientes_ordem_e_estrutura(cad):
    """CAD-24/27: clientes = ['Todos'] + carteiras ativas (por nome) + ['Outros'], cada {pk, nome, total, cadastrados, pct, url, ativo}."""
    cad.Carteira.objects.filter(pk=cad.carteiras["Volvo"].pk).update(ativa=False)
    for i in range(2):
        criar_processo(cad, numero=_n(i), carteira=cad.carteiras["Ativos"], status="CONFERIR")
    criar_processo(cad, numero=_n(10), carteira=cad.carteiras["Ativos"], status="CADASTRADO")
    criar_processo(cad, numero=_n(20), carteira=None, status="CADASTRADO")
    cl = _painel(cad.ana).context["clientes"]
    for c in cl:
        assert {"pk", "nome", "total", "cadastrados", "pct", "url", "ativo"} <= set(c)
    nomes = [c["nome"] for c in cl]
    assert nomes[0] == "Todos" and nomes[-1] == "Outros" and "Volvo" not in nomes
    meio = nomes[1:-1]
    assert meio == sorted(meio, key=str.lower) and {"Ailos", "Ativos"} <= set(meio)
    assert cl[0]["pk"] is None and cl[-1]["pk"] == "outros"
    por = {c["nome"]: c for c in cl}
    assert (por["Todos"]["total"], por["Todos"]["cadastrados"]) == (4, 2)
    assert (por["Ativos"]["total"], por["Ativos"]["cadastrados"], por["Ativos"]["pct"], por["Ativos"]["pk"]) == (3, 1, 33, cad.carteiras["Ativos"].pk)
    assert (por["Outros"]["total"], por["Outros"]["cadastrados"], por["Outros"]["pct"]) == (1, 1, 100)
    assert (por["Ailos"]["total"], por["Ailos"]["cadastrados"], por["Ailos"]["pct"]) == (0, 0, 0)
    assert por["Todos"]["pct"] == 50


def test_clientes_nao_contam_excluidos(cad):
    """CAD-24/27: totais e cadastrados dos clientes desconsideram excluídos."""
    criar_processo(cad, numero=_n(1), carteira=cad.carteiras["Ativos"], status="CADASTRADO")
    criar_processo(cad, numero=_n(2), carteira=cad.carteiras["Ativos"], status="CADASTRADO", excluido_em=timezone.now(), excluido_por=cad.adm_u)
    por = {c["nome"]: c for c in _painel(cad.ana).context["clientes"]}
    assert (por["Ativos"]["total"], por["Ativos"]["cadastrados"]) == (1, 1) and por["Todos"]["total"] == 1


def test_clientes_texto_cadastrados_sobre_total(cad, ver):
    """CAD-24: cada cliente mostra 'cadastrados/total' (ex.: 1/3) e a minibarra de progresso."""
    for i in range(2):
        criar_processo(cad, numero=_n(i), carteira=cad.carteiras["Ativos"], status="CONFERIR")
    criar_processo(cad, numero=_n(10), carteira=cad.carteiras["Ativos"], status="CADASTRADO")
    r = _painel(cad.ana)
    assert re.search(r"Ativos\s*1\s*/\s*3", ver.texto(r))
    assert re.search(r"width:\s*33(\.\d+)?%", ver.html(r))


def test_clientes_urls_e_ativo(cad):
    """CAD-27 (contrato): Todos sem ?carteira; carteira ?carteira=<pk>; Outros ?carteira=outros; ativo = filtro corrente; URLs preservam ?status/?audiencia e removem ?p e ?page."""
    ativos = cad.carteiras["Ativos"]
    r0 = _painel(cad.ana)
    por = {c["nome"]: c for c in r0.context["clientes"]}
    assert "carteira" not in por["Todos"]["url"] and por["Todos"]["ativo"] is True and por["Ativos"]["ativo"] is False
    assert f"carteira={ativos.pk}" in por["Ativos"]["url"] and "carteira=outros" in por["Outros"]["url"]
    r = _painel(cad.ana, carteira=ativos.pk, status="CONFERIR", audiencia=1, p=5, page=2)
    por = {c["nome"]: c for c in r.context["clientes"]}
    assert por["Ativos"]["ativo"] is True and por["Todos"]["ativo"] is False and por["Outros"]["ativo"] is False
    for c in r.context["clientes"]:
        assert "status=CONFERIR" in c["url"] and "audiencia=1" in c["url"] and "p=" not in re.sub(r"\bpage=", "", c["url"]).replace("pagina=", "") and "page=" not in c["url"]
    assert _painel(cad.ana, carteira="outros").context["clientes"][-1]["ativo"] is True


# ---------------- lista ----------------

def test_lista_chip_com_a_quantidade_de_obrigatorios_faltando(cad, ver):
    """CAD-24: chip do status com a quantidade de obrigatórios faltando ('Com pendências · 2')."""
    criar_processo(cad, numero=_n(1), status="COM_PENDENCIAS", pendencias=["Verificar: Comarca, Juízo"], comarca="", juizo="")
    t = ver.texto(_painel(cad.ana))
    assert "Com pendências · 2" in t


def test_lista_valor_ausente_mostra_sem_valor_da_causa(cad, ver):
    """CAD-24: valor ausente → 'sem valor da causa'; presente → 'R$ 1.234,56'."""
    criar_processo(cad, numero=_n(1), valor_causa=None, status="COM_PENDENCIAS", pendencias=["x"], adverso_nome="Sem Valor SA")
    criar_processo(cad, numero=_n(2), valor_causa="1234.56", adverso_nome="Com Valor SA")
    t = ver.texto(_painel(cad.ana))
    assert "sem valor da causa" in t and "R$ 1.234,56" in t


def test_linha_selecionada_tem_aria_current(cad, ver):
    """CAD-24: a linha selecionada leva aria-current (uma só)."""
    a = criar_processo(cad, numero=_n(1))
    b = criar_processo(cad, numero=_n(2))
    h = ver.html(_painel(cad.ana, p=a.pk))
    assert len(re.findall(r"aria-current=", h)) >= 1
    trecho = re.search(r"<[^>]*aria-current=[^>]*>.*?</(?:a|li|tr|div)>", h, re.S).group(0)
    assert a.numero in trecho and b.numero not in trecho


def test_lista_mostra_o_sequencial_do_numero(cad, ver):
    """CAD-24: número com o sequencial em destaque (o sequencial NNNNNNN aparece isolado em elemento próprio)."""
    p = criar_processo(cad, numero=cnj(1234))
    h = ver.html(_painel(cad.ana))
    assert re.search(r">\s*0001234\s*<", h) and p.numero in re.sub(r"<[^>]+>", "", h)


# ---------------- CAD-25 · ficha ----------------

def _sel(cad, p, cliente=None, **q):
    r = (cliente or cad.ana).get(reverse(PAINEL), {"p": p.pk, **q})
    assert r.status_code == 200
    return r, r.context["selecionado"]


def test_ficha_padrao_e_o_primeiro_e_p_seleciona(cad):
    """CAD-16/27: selecionado = ?p=<pk>; sem ?p é o 1º da lista."""
    a = criar_processo(cad, numero=_n(1))
    b = criar_processo(cad, numero=_n(2))
    assert _painel(cad.ana).context["selecionado"]["processo"].pk == b.pk  # mais recente primeiro
    assert _painel(cad.ana, p=a.pk).context["selecionado"]["processo"].pk == a.pk


def test_ficha_vazia_sem_processos(cad):
    """CAD-27: sem processos, selecionado é vazio (None)."""
    assert not _painel(cad.ana).context["selecionado"]


def test_ficha_linha_carteira_tribunal_fase(cad, ver):
    """CAD-25a: 'carteira · tribunal · fase <fase>'."""
    p = criar_processo(cad, numero=_n(1), carteira=cad.carteiras["Ailos"], tribunal="TJRJ", fase_atual="RECURSAL")
    t = ver.texto(_sel(cad, p)[0])
    assert re.search(r"Ailos · TJRJ · fase Recursal", t, re.I)


@pytest.mark.parametrize("kw,partes,sigla", [
    (dict(seq=1234, ano=2022, j=8, tr=26, orgao=100), [("0001234", "sequencial"), ("42", "dígito"), ("2022", "ano"), ("8", "estadual"), ("26", "TJSP"), ("0100", "origem")], "TJSP"),
    (dict(seq=77, ano=2021, j=8, tr=7, orgao=1), [("0000077", "sequencial"), (None, "dígito"), ("2021", "ano"), ("8", "estadual"), ("07", "TJDFT"), ("0001", "origem")], "TJDFT"),
    (dict(seq=5, ano=2020, j=4, tr=3, orgao=34), [("0000005", "sequencial"), (None, "dígito"), ("2020", "ano"), ("4", "federal"), ("03", "TRF3"), ("0034", "origem")], "TRF3"),
    (dict(seq=9, ano=2023, j=5, tr=2, orgao=15), [("0000009", "sequencial"), (None, "dígito"), ("2023", "ano"), ("5", "trabalho"), ("02", "TRT2"), ("0015", "origem")], "TRT2"),
    (dict(seq=10, ano=2019, j=6, tr=26, orgao=1), [("0000010", "sequencial"), (None, "dígito"), ("2019", "ano"), ("6", "eleitoral"), ("26", "TRE-SP"), ("0001", "origem")], "TRE-SP"),
])
def test_ficha_numero_cnj_decomposto(cad, kw, partes, sigla):
    """CAD-25b/27: número válido → 6 partes na ordem NNNNNNN, DD, AAAA, J, TR, OOOO, cada uma com legenda (justiça em minúsculas; TR com a sigla) + sigla."""
    p = criar_processo(cad, numero=cnj(**kw))
    _, sel = _sel(cad, p)
    cnj_ = sel["cnj"]
    assert cnj_["valido"] is True and cnj_["sigla"] == sigla and len(cnj_["partes"]) == 6
    for parte, (valor, legenda) in zip(cnj_["partes"], partes, strict=True):
        assert parte["legenda"] == legenda
        if valor is not None:
            assert parte["valor"] == valor
    assert "".join(x["valor"] for x in cnj_["partes"]) == p.numero_digitos


@pytest.mark.parametrize("j,legenda", [(1, "STF"), (2, "CNJ"), (3, "STJ"), (4, "federal"), (5, "trabalho"), (6, "eleitoral"), (7, "militar da União"), (8, "estadual"), (9, "militar estadual")])
def test_ficha_legenda_da_justica(cad, j, legenda):
    """CAD-25b (contrato): legenda da justiça por J (1 STF, 2 CNJ, 3 STJ, 4 federal, 5 trabalho, 6 eleitoral, 7 militar da União, 8 estadual, 9 militar estadual)."""
    p = criar_processo(cad, numero=cnj(1, j=j, tr=0 if j in (1, 2, 3, 7, 9) else 1))
    assert _sel(cad, p)[1]["cnj"]["partes"][3]["legenda"] == legenda


@pytest.mark.parametrize("j,tr", [(1, 0), (2, 0), (3, 0), (7, 0), (9, 21), (8, 99), (4, 90), (5, 99), (6, 99)])
def test_ficha_segmentos_sem_sigla_ou_tr_fora_do_mapa_mostram_traco(cad, j, tr):
    """CAD-25b (contrato): demais segmentos ou TR fora do mapa → sigla '—'."""
    p = criar_processo(cad, numero=cnj(2, j=j, tr=tr))
    cnj_ = _sel(cad, p)[1]["cnj"]
    assert cnj_["valido"] is True and cnj_["sigla"] == "—" and cnj_["partes"][4]["legenda"] == "—"


def test_ficha_sigla_dos_27_tj_e_dos_trf_trt_tre_completos(cad):
    """CAD-25b: mapa COMPLETO — todos os TJ (TR 01..27), TRF 1..6, TRT 1..24 e TRE (01..27) resolvem para uma sigla (nunca '—')."""
    faltando = []
    for j, rng, prefixo in ((8, range(1, 28), "TJ"), (4, range(1, 7), "TRF"), (5, range(1, 25), "TRT"), (6, range(1, 28), "TRE")):
        for tr in rng:
            p = criar_processo(cad, numero=cnj(300 + tr, j=j, tr=tr))
            s = _sel(cad, p)[1]["cnj"]["sigla"]
            if not s.startswith(prefixo):
                faltando.append((j, tr, s))
    assert faltando == []


def test_ficha_numero_invalido_nao_decompoe_e_mostra_como_veio(cad, ver):
    """CAD-25b/27: dígito verificador inválido → {valido: False, partes: [], sigla: ''} e a tela mostra o texto como veio."""
    p = criar_processo(cad, numero=("Proc 123/2020 (orig.)", "12320200000000000000"), valido=False)
    r, sel = _sel(cad, p)
    assert sel["cnj"] == {"valido": False, "partes": [], "sigla": ""}
    assert "Proc 123/2020 (orig.)" in ver.texto(r)


def test_ficha_sete_obrigatorios_na_ordem(cad):
    """CAD-25c/27: lista de 7 {campo, rotulo, ok}, nessa ordem; numero.ok = numero_valido; demais ok = preenchido."""
    p = criar_processo(cad, numero=_n(1), comarca="", juizo="", valor_causa=None)
    sel = _sel(cad, p)[1]
    esperado = [("numero", "Número", True), ("tribunal", "Tribunal", True), ("comarca", "Comarca", False), ("juizo", "Juízo", False),
                ("adverso_nome", "Adverso", True), ("valor_causa", "Valor da causa", False), ("distribuido_em", "Distribuído em", True)]
    assert [(o["campo"], o["rotulo"], o["ok"]) for o in sel["obrigatorios"]] == esperado
    assert sel["obrig_ok"] == 4 and isinstance(sel["obrig_ok"], int)


def test_ficha_numero_invalido_conta_como_faltando(cad):
    """CAD-27 (contrato): numero ok = numero_valido — número inválido NÃO está ok."""
    p = criar_processo(cad, numero=cnj(3, dv_errado=True), valido=False)
    sel = _sel(cad, p)[1]
    assert sel["obrigatorios"][0] == {"campo": "numero", "rotulo": "Número", "ok": False} and sel["obrig_ok"] == 6


@pytest.mark.parametrize("vazio", ["tribunal", "comarca", "juizo", "adverso_nome", "valor_causa", "distribuido_em"])
def test_ficha_cada_obrigatorio_vazio_fica_nao_ok(cad, vazio):
    """CAD-25c/27: cada um dos 6 campos preenchíveis vazio → ok False (e só ele)."""
    p = criar_processo(cad, numero=_n(1), **{vazio: None if vazio in ("valor_causa", "distribuido_em") else ""})
    sel = _sel(cad, p)[1]
    assert [o["campo"] for o in sel["obrigatorios"] if not o["ok"]] == [vazio] and sel["obrig_ok"] == 6


def test_ficha_marcadores_e_contagem_na_tela(cad, ver):
    """CAD-25c: 'N de 7 campos obrigatórios' e 7 marcadores (preenchido/faltando)."""
    p = criar_processo(cad, numero=_n(1), comarca="", juizo="", status="COM_PENDENCIAS", pendencias=["Verificar: Comarca, Juízo"])
    r, _ = _sel(cad, p)
    t = ver.texto(r)
    assert "5 de 7 campos obrigatórios" in t
    h = ver.html(r)
    assert len(re.findall(r"marcador|obrig-ponto|data-obrig", h)) >= 7 or len(re.findall(r'aria-label="[^"]*(?:preenchido|faltando|encontrado)', h)) >= 7


def test_ficha_completa_e_sete_de_sete(cad, ver):
    """CAD-25c: processo completo → '7 de 7 campos obrigatórios'."""
    p = criar_processo(cad, numero=_n(1))
    r, sel = _sel(cad, p)
    assert sel["obrig_ok"] == 7 and "7 de 7 campos obrigatórios" in ver.texto(r)


def test_ficha_acao_conferir(cad, ver):
    """CAD-25d: CONFERIR → acao 'conferir'; botões 'Marcar cadastrado no Espaider' (POST marcar_cadastrado) + 'Editar'; urls do contexto."""
    p = criar_processo(cad, numero=_n(1), status="CONFERIR")
    r, sel = _sel(cad, p)
    assert sel["acao"] == "conferir" and sel["url_editar"] == reverse("juridico:processo", kwargs={"pk": p.pk})
    assert sel["url_marcar"] == reverse("juridico:marcar_cadastrado", kwargs={"pk": p.pk})
    t = ver.texto(r)
    assert "Marcar cadastrado no Espaider" in t and "Editar" in t and "Completar campos" not in t
    assert f'action="{sel["url_marcar"]}"' in ver.html(r)


def test_ficha_acao_pendencias_com_e_sem_pdf(cad, ver):
    """CAD-25d: COM_PENDENCIAS → 'Completar campos' (abre juridico:processo) + 'Abrir PDF' (juridico:pdf do último item com arquivo); sem PDF → botão ausente."""
    p = criar_processo(cad, numero=_n(1), status="COM_PENDENCIAS", pendencias=["Verificar: Juízo"], juizo="")
    r, sel = _sel(cad, p)
    t = ver.texto(r)
    assert sel["acao"] == "pendencias" and sel["url_pdf"] is None and "Completar campos" in t and "Abrir PDF" not in t
    assert reverse("juridico:processo", kwargs={"pk": p.pk}) in ver.html(r)
    antigo = _item(cad, processo=p, arquivo="juridico/2026/10/antigo.pdf")
    novo = _item(cad, processo=p, arquivo="juridico/2026/10/novo.pdf")
    _item(cad, processo=p, arquivo="", origem="cnj")   # item CNJ mais recente, sem arquivo: não conta
    r, sel = _sel(cad, p)
    assert sel["url_pdf"] == reverse("juridico:pdf", kwargs={"pk": novo.pk}) and sel["url_pdf"] != reverse("juridico:pdf", kwargs={"pk": antigo.pk})
    assert "Abrir PDF" in ver.texto(r) and sel["url_pdf"] in ver.html(r)


def test_ficha_acao_cadastrado(cad, ver):
    """CAD-25d: CADASTRADO → texto '✓ Cadastrado no Espaider em DD/MM/AAAA' + 'Editar' (sem botão de marcar)."""
    quando = timezone.now() - timedelta(days=2)
    p = criar_processo(cad, numero=_n(1), status="CADASTRADO", cadastrado_espaider_em=quando, cadastrado_espaider_por=cad.ana_u)
    r, sel = _sel(cad, p)
    t = ver.texto(r)
    assert sel["acao"] == "cadastrado" and f"Cadastrado no Espaider em {timezone.localtime(quando):%d/%m/%Y}" in t
    assert "Editar" in t and "Marcar cadastrado no Espaider" not in t and "Completar campos" not in t


def test_ficha_partes_e_processo_com_campos_obrigatorios_marcados(cad, ver):
    """CAD-25e: grupos 'Partes' (Empresa, Adverso · CPF/CNPJ mascarado, Condição) e 'Processo' (Comarca, Juízo, Distribuído em, Valor da causa) com 'obrigatório'."""
    p = criar_processo(cad, numero=_n(1), empresa="ATIVOS S.A.", adverso_nome="Maria Adversa", adverso_cpf_cnpj="123.456.789-09", condicao="Autor",
                       comarca="Campinas", juizo="2ª Vara Cível", distribuido_em="2022-03-15", valor_causa="1234.56")
    r, _ = _sel(cad, p)
    t = ver.texto(r)
    for rotulo in ("Partes", "Processo", "Empresa", "Adverso", "Condição", "Comarca", "Juízo", "Distribuído em", "Valor da causa"):
        assert rotulo in t, rotulo
    assert "ATIVOS S.A." in t and "Maria Adversa" in t and "***.456.789-**" in t and "Autor" in t
    assert "Campinas" in t and "2ª Vara Cível" in t and "15/03/2022" in t and "R$ 1.234,56" in t
    assert len(re.findall(r"\bobrigatório\b", t)) >= 5
    h = ver.html(r)
    ficha = h[h.index("Partes"):] if "Partes" in h else h
    assert "123.456.789-09" not in ficha


def test_ficha_campo_vazio_mostra_nao_encontrado_no_pdf(cad, ver):
    """CAD-25e: campo vazio → 'não encontrado no PDF'; tantos quanto campos vazios exibidos."""
    p = criar_processo(cad, numero=_n(1), comarca="", juizo="", valor_causa=None, status="COM_PENDENCIAS", pendencias=["x"])
    t = ver.texto(_sel(cad, p)[0])
    assert t.count("não encontrado no PDF") >= 3
    cheio = criar_processo(cad, numero=_n(2), status="CONFERIR")
    # (a ficha completa não pode exibir o aviso nos 7 campos obrigatórios)
    assert ver.texto(_sel(cad, cheio)[0]).count("não encontrado no PDF") < 3


def test_ficha_audiencia_futura_com_tipo(cad, ver):
    """CAD-25f/27: audiencia {dia '05', mes_ano 'out 2030', hora '14:30', tipo 'Audiência de conciliação', local 'Campinas · 2ª Vara'} e aviso de agenda manual."""
    p = criar_processo(cad, numero=_n(1), comarca="Campinas", juizo="2ª Vara", proxima_audiencia=_em_sp(2030, 10, 5, 14, 30), proxima_audiencia_tipo="conciliação")
    r, sel = _sel(cad, p)
    assert sel["audiencia"] == {"dia": "05", "mes_ano": "out 2030", "hora": "14:30", "tipo": "Audiência de conciliação", "local": "Campinas · 2ª Vara"}
    t = ver.texto(r)
    assert "Audiência de conciliação" in t and "14:30" in t and "Campinas · 2ª Vara" in t and "Agenda manual: crie a agenda da audiência no Espaider." in t
    assert "out 2030" in t.lower() and re.search(r"\b05\b", t)


@pytest.mark.parametrize("mes,abrev", [(1, "jan"), (2, "fev"), (3, "mar"), (4, "abr"), (5, "mai"), (6, "jun"), (7, "jul"), (8, "ago"), (9, "set"), (10, "out"), (11, "nov"), (12, "dez")])
def test_ficha_mes_abreviado_em_minusculas(cad, mes, abrev):
    """CAD-27 (contrato): mes_ano = mês abreviado minúsculo pt-BR + espaço + ano."""
    p = criar_processo(cad, numero=_n(mes), proxima_audiencia=_em_sp(2031, mes, 9, 8, 5))
    a = _sel(cad, p)[1]["audiencia"]
    assert a["mes_ano"] == f"{abrev} 2031" and a["dia"] == "09" and a["hora"] == "08:05"


def test_ficha_audiencia_hora_no_fuso_de_sao_paulo(cad):
    """CAD-27 (contrato): hora em America/Sao_Paulo (instante UTC 02:30 do dia 6 = 23:30 do dia 5 em SP)."""
    p = criar_processo(cad, numero=_n(1), proxima_audiencia=datetime(2030, 10, 6, 2, 30, tzinfo=ZoneInfo("UTC")))
    a = _sel(cad, p)[1]["audiencia"]
    assert (a["dia"], a["hora"], a["mes_ano"]) == ("05", "23:30", "out 2030")


def test_ficha_audiencia_sem_tipo_e_local_sem_separador_sobrando(cad):
    """CAD-25f/27: sem tipo → 'Audiência'; partes vazias do local omitidas, sem ' · ' sobrando."""
    futuro = _em_sp(2030, 11, 12, 9, 0)
    p1 = criar_processo(cad, numero=_n(1), comarca="", juizo="3ª Vara", proxima_audiencia=futuro, proxima_audiencia_tipo="")
    p2 = criar_processo(cad, numero=_n(2), comarca="Santos", juizo="", proxima_audiencia=futuro)
    p3 = criar_processo(cad, numero=_n(3), comarca="", juizo="", proxima_audiencia=futuro)
    a1, a2, a3 = (_sel(cad, p)[1]["audiencia"] for p in (p1, p2, p3))
    assert (a1["tipo"], a1["local"]) == ("Audiência", "3ª Vara") and a2["local"] == "Santos" and a3["local"] == ""


def test_ficha_audiencia_passada_ou_ausente_e_none(cad, ver):
    """CAD-27 (contrato): só se proxima_audiencia >= agora; senão None — e a tela não mostra o bloco nem o aviso de agenda manual."""
    p = criar_processo(cad, numero=_n(1), proxima_audiencia=timezone.now() - timedelta(hours=1), proxima_audiencia_tipo="instrução")
    q = criar_processo(cad, numero=_n(2), proxima_audiencia=None)
    for x in (p, q):
        r, sel = _sel(cad, x)
        assert sel["audiencia"] is None and "Agenda manual" not in ver.texto(r)


@pytest.mark.parametrize("tipo,exibicao", [("conciliação", "Audiência de conciliação"), ("instrução e julgamento", "Audiência de instrução e julgamento"),
                                           ("mediação", "Audiência de mediação"), ("una", "Audiência de una"), ("", "Audiência")])
def test_ficha_tipo_de_exibicao(cad, tipo, exibicao):
    """CAD-26/27: exibição = 'Audiência de ' + tipo (ou 'Audiência' se vazio)."""
    p = criar_processo(cad, numero=_n(1), proxima_audiencia=timezone.now() + timedelta(days=9), proxima_audiencia_tipo=tipo)
    assert _sel(cad, p)[1]["audiencia"]["tipo"] == exibicao


def test_ficha_faixa_confere_com_o_cnj(cad, ver):
    """CAD-25g: cnj_validacao=confere → faixa 'Confere com o CNJ' com tribunal, distribuição e comarca; cnj_situacao='confere'."""
    p = criar_processo(cad, numero=_n(1), cnj_validacao="confere", cnj_consultado_em=timezone.now(), tribunal="TJSP", comarca="Campinas", distribuido_em="2022-03-15")
    r, sel = _sel(cad, p)
    t = ver.texto(r)
    assert sel["cnj_situacao"] == "confere" and "Confere com o CNJ" in t
    faixa = t[t.index("Confere com o CNJ"):][:400]
    assert "TJSP" in faixa and "15/03/2022" in faixa and "Campinas" in faixa


def test_ficha_faixa_divergente_lista_as_divergencias(cad, ver):
    """CAD-25g: divergente → faixa com as divergências (sem o texto de 'Confere')."""
    p = criar_processo(cad, numero=_n(1), cnj_validacao="divergente", cnj_divergencias=["tribunal (PDF: TJSP · CNJ: TJRJ)", "comarca (PDF: Santos · CNJ: Osasco)"])
    r, sel = _sel(cad, p)
    t = ver.texto(r)
    assert sel["cnj_situacao"] == "divergente" and "tribunal (PDF: TJSP · CNJ: TJRJ)" in t and "comarca (PDF: Santos · CNJ: Osasco)" in t
    assert "Confere com o CNJ" not in t


@pytest.mark.parametrize("situacao", ["nao_consultado", "falhou", "nao_encontrado"])
def test_ficha_cnj_neutro_nos_demais_casos(cad, ver, situacao):
    """CAD-25g: não consultado/falhou/não encontrado → texto neutro (sem 'Confere com o CNJ'), cnj_situacao refletindo o estado."""
    p = criar_processo(cad, numero=_n(1), cnj_validacao=situacao)
    r, sel = _sel(cad, p)
    assert sel["cnj_situacao"] == situacao and "Confere com o CNJ" not in ver.texto(r)


# ---------------- CAD-26 · tipo da audiência ----------------

@pytest.mark.parametrize("trecho,tipo", [
    ("Audiência de conciliação designada para {d} às 14:30.", "conciliação"),
    ("audiência de instrução e julgamento marcada para {d}, 09h15.", "instrução e julgamento"),
    ("Audiência de mediação redesignada para {d} às 10:00.", "mediação"),
    ("AUDIÊNCIA DE CONCILIAÇÃO DESIGNADA PARA {d} ÀS 10:00.", "conciliação"),
    ("Audiência de   instrução   designada para {d} às 10:00.", "instrução"),
    ("Audiência designada para {d} às 10:00.", ""),
])
def test_tipo_extraido_junto_com_a_data(cad, ingerir, trecho, tipo):
    """CAD-26/20: 'audiência de <tipo>' é extraído do mesmo trecho da data e gravado só como o complemento, minúsculo e sem espaços sobrando."""
    d = timezone.localdate() + timedelta(days=12)
    _, p = ingerir(cad.ana, cnj(40 + len(tipo))[0], variante=tipo or "sem", campos={"observacoes": trecho.format(d=f"{d:%d/%m/%Y}")})
    assert p.proxima_audiencia is not None and p.proxima_audiencia_tipo == tipo


def test_tipo_vem_do_trecho_da_audiencia_escolhida(cad, ingerir):
    """CAD-26: com várias audiências, o tipo é o do trecho da futura MAIS PRÓXIMA (não o de outra)."""
    hoje = timezone.localdate()
    obs = (f"Audiência de instrução designada para {hoje + timedelta(days=40):%d/%m/%Y} às 10:00. "
           f"Audiência de conciliação marcada para {hoje + timedelta(days=8):%d/%m/%Y} às 14:00. "
           f"Audiência de mediação marcada para {hoje - timedelta(days=5):%d/%m/%Y} às 09:00.")
    _, p = ingerir(cad.ana, cnj(5)[0], campos={"observacoes": obs})
    assert p.proxima_audiencia_tipo == "conciliação" and timezone.localtime(p.proxima_audiencia).date() == hoje + timedelta(days=8)


def test_tipo_tambem_vem_dos_andamentos(cad, ingerir):
    """CAD-26/20: extração nos andamentos do PDF também traz o tipo."""
    d = timezone.localdate() + timedelta(days=6)
    movs = [{"data": "01/01/2023", "evento": f"Audiência de mediação designada para {d:%d/%m/%Y} às 13:00"}]
    _, p = ingerir(cad.ana, cnj(6)[0], campos={"ultimas_movimentacoes": movs})
    assert p.proxima_audiencia_tipo == "mediação"


def test_sem_audiencia_futura_tipo_vazio(cad, ingerir):
    """CAD-26: só audiência passada ou nenhuma → proxima_audiencia e tipo vazios."""
    passada = timezone.localdate() - timedelta(days=4)
    _, p = ingerir(cad.ana, cnj(7)[0], campos={"observacoes": f"Audiência de conciliação designada para {passada:%d/%m/%Y} às 10:00."})
    assert p.proxima_audiencia is None and p.proxima_audiencia_tipo == ""


def test_tipo_editavel_na_conferencia_e_vira_manual(cad):
    """CAD-26: POST da conferência com proxima_audiencia_tipo junto com a data; fica minúsculo/aparado e a edição vira origem manual."""
    p = criar_processo(cad, numero=_n(1))
    d = timezone.localdate() + timedelta(days=15)
    r = cad.ana.post(reverse("juridico:processo", kwargs={"pk": p.pk}), {"proxima_audiencia": f"{d:%Y-%m-%d}T15:45", "proxima_audiencia_tipo": "  Instrução e Julgamento  "})
    p.refresh_from_db()
    assert r.status_code in (200, 302) and p.proxima_audiencia_tipo == "instrução e julgamento"
    assert p.origem_campos["proxima_audiencia"] == "manual"
    assert _sel(cad, p)[1]["audiencia"]["tipo"] == "Audiência de instrução e julgamento"


def test_tipo_ate_80_caracteres_e_acima_e_erro(cad, ver):
    """CAD-26: max 80; 81 → erro 'Máximo de 80 caracteres.' e nada gravado."""
    p = criar_processo(cad, numero=_n(1), proxima_audiencia_tipo="una")
    ok = "a" * 80
    cad.ana.post(reverse("juridico:processo", kwargs={"pk": p.pk}), {"proxima_audiencia_tipo": ok})
    p.refresh_from_db()
    assert p.proxima_audiencia_tipo == ok
    r = cad.ana.post(reverse("juridico:processo", kwargs={"pk": p.pk}), {"proxima_audiencia_tipo": "a" * 81})
    p.refresh_from_db()
    assert r.status_code == 200 and "Máximo de 80 caracteres." in ver.texto(r) and p.proxima_audiencia_tipo == ok


def test_tipo_vazio_e_permitido_e_campo_ausente_nao_muda(cad):
    """CAD-26/23: vazio é permitido (limpa); campo ausente no POST não muda."""
    p = criar_processo(cad, numero=_n(1), proxima_audiencia_tipo="mediação")
    cad.ana.post(reverse("juridico:processo", kwargs={"pk": p.pk}), {"comarca": "Outra"})
    p.refresh_from_db()
    assert p.proxima_audiencia_tipo == "mediação"
    cad.ana.post(reverse("juridico:processo", kwargs={"pk": p.pk}), {"proxima_audiencia_tipo": ""})
    p.refresh_from_db()
    assert p.proxima_audiencia_tipo == ""


def test_tipo_e_escapado_na_ficha(cad, ver):
    """SEG-13: tipo com HTML (cabe em 80) aparece escapado na ficha."""
    p = criar_processo(cad, numero=_n(1), proxima_audiencia=timezone.now() + timedelta(days=9), proxima_audiencia_tipo="<img src=x onerror=1>")
    h = ver.html(_sel(cad, p)[0])
    assert "<img src=x onerror=1>" not in h


# ---------------- permissões e custo ----------------

def test_painel_v2_respeita_acesso(cad):
    """CAD-02: sem acesso → 403; anônimo → login (o painel v2 não abre exceção)."""
    assert _painel(cad.carla).status_code == 403
    r = _painel(cad.anonimo)
    assert r.status_code == 302 and reverse("login") in r["Location"]


def test_em_leitura_e_clientes_aparecem_para_base_e_coordenador_com_acesso(cad):
    """CAD-24/02: Base e Coordenador do setor com acesso veem as contagens de TODOS (o cadastro é do escritório)."""
    _item(cad, status="na_fila", usuario=cad.adm_u, arquivo="juridico/2026/10/z.pdf")
    criar_processo(cad, numero=_n(1), usuario=cad.adm_u)
    for c in (cad.ana, cad.bruno):
        ctx = _painel(c).context
        assert ctx["fluxo"]["em_leitura"] == 1 and ctx["fluxo"]["total"] == 1


def test_queries_constantes_com_o_painel_v2(cad):
    """CAD-24/27: número de queries do painel não cresce com processos, itens, carteiras nem audiências (contagens agregadas no banco)."""
    def montar(a, b):
        for i in range(a, b):
            p = criar_processo(cad, numero=_n(i), carteira=[cad.carteiras["Ativos"], cad.carteiras["Ailos"], None][i % 3],
                               status=["CONFERIR", "COM_PENDENCIAS", "CADASTRADO"][i % 3], proxima_audiencia=timezone.now() + timedelta(days=1 + i))
            _item(cad, processo=p, arquivo=f"juridico/2026/10/{i}.pdf", status=["na_fila", "concluido", "erro"][i % 3],
                  etapa="Leitura do PDF" if i % 3 == 2 else None)

    montar(0, 12)
    with CaptureQueriesContext(connection) as q1:
        _painel(cad.ana)
    with CaptureQueriesContext(connection) as q2:
        _painel(cad.ana, audiencia=1, status="CONFERIR")
    montar(12, 60)
    with CaptureQueriesContext(connection) as q3:
        _painel(cad.ana)
    with CaptureQueriesContext(connection) as q4:
        _painel(cad.ana, audiencia=1, status="CONFERIR")
    assert len(q3) == len(q1) and len(q4) == len(q2)


def test_dinheiro_e_datas_no_formato_brasileiro_em_toda_a_ficha(cad, ver):
    """CAD-27: datas DD/MM/AAAA e dinheiro R$ 1.234,56 (nunca ISO nem ponto decimal) na ficha e na lista."""
    p = criar_processo(cad, numero=_n(1), valor_causa="1234567.89", distribuido_em="2022-03-15", data_citacao="2022-04-20")
    t = ver.texto(_sel(cad, p)[0])
    assert "R$ 1.234.567,89" in t and "15/03/2022" in t and "2022-03-15" not in t and "1234567.89" not in t
