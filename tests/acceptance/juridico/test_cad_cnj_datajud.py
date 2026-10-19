"""Aceite M8 · validação no CNJ / DataJud falso (CAD-10, CAD-09 lado CNJ, CAD-13). Só pela spec."""
import json
import time

import pytest
from django.urls import reverse

from .conftest import SEGREDO_DATAJUD, cnj, fonte_datajud

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

NUM, DIG = cnj(1234)


def _cadastrar(cad, ingerir, numero=NUM, dig=DIG, fonte=None, campos=None, variante="a"):
    if fonte is not False:
        cad.datajud.fontes[dig] = fonte if fonte is not None else fonte_datajud(dig)
    return ingerir(cad.ana, numero, variante=variante, campos=campos, carteira=cad.carteiras["Ativos"])


def test_confere_quando_tribunal_data_e_comarca_batem(cad, ingerir):
    """CAD-10: tudo igual → cnj_validacao=confere, sem divergências, cnj_consultado_em preenchido."""
    _, p = _cadastrar(cad, ingerir)
    assert p.cnj_validacao == "confere" and p.cnj_divergencias == [] and p.cnj_consultado_em is not None
    assert p.status == "CONFERIR" and not any("Divergência" in x for x in p.pendencias)


def test_requisicao_ao_datajud_segue_a_spec(cad, ingerir):
    """CAD-10: POST {datajud_url}/api_publica_tjsp/_search com {query:{match:{numeroProcesso}}, size:1} e a chave só via credencial."""
    _cadastrar(cad, ingerir)
    (req,) = cad.datajud.buscas
    assert req["metodo"] == "POST" and req["rota"] == "/datajud/api_publica_tjsp/_search"
    assert json.loads(req["corpo"]) == {"query": {"match": {"numeroProcesso": DIG}}, "size": 1}
    assert req["headers"]["authorization"] == f"APIKey {SEGREDO_DATAJUD}"


@pytest.mark.parametrize("j,tr,alias", [(8, 26, "tjsp"), (8, 19, "tjrj"), (4, 3, "trf3"), (4, 1, "trf1"), (5, 2, "trt2"), (5, 15, "trt15"), (6, 26, "tre-sp")])
def test_alias_do_tribunal_pelo_numero(cad, enviar_cnj, rodar, j, tr, alias):
    """CAD-10: J=8 → tj<uf>, 4 → trfN, 5 → trtN, 6 → tre-<uf>; a busca vai para api_publica_<alias>."""
    n, d = cnj(500 + tr, j=j, tr=tr)
    cad.datajud.fontes[d] = fonte_datajud(d)
    enviar_cnj(cad.ana, n, cad.carteiras["Ativos"])
    rodar()
    assert [b["rota"] for b in cad.datajud.buscas] == [f"/datajud/api_publica_{alias}/_search"]


@pytest.mark.parametrize("j,tr", [(1, 0), (3, 0), (7, 0), (2, 0), (9, 99)])
def test_tribunal_sem_alias_e_falhou_sem_consultar(cad, ingerir, j, tr):
    """CAD-10: sem alias → cnj_validacao=falhou com 'Tribunal não suportado no DataJud.', e nenhuma consulta."""
    n, d = cnj(600 + j, j=j, tr=tr)
    _, p = ingerir(cad.ana, n, campos={"tribunal": "XYZ"})
    assert p is not None and p.cnj_validacao == "falhou" and cad.datajud.buscas == []
    item = cad.ItemEnvio.objects.order_by("pk").last()
    onde = " ".join(p.cnj_divergencias) + " ".join(p.pendencias) + (item.motivo or "") + \
        cad.ana.get(reverse("juridico:processo", kwargs={"pk": p.pk})).content.decode() + cad.adm.get(reverse("juridico:erros")).content.decode()
    assert "Tribunal não suportado no DataJud." in onde


@pytest.mark.parametrize("pdf_trib", ["TJSP", "tjsp", "TJ-SP", "TJ SP", "T.J.S.P."])
def test_tribunal_igual_ignorando_caixa_espacos_hifen_e_ponto(cad, ingerir, pdf_trib):
    """CAD-23(6): tribunal igual depois de maiúsculas e sem espaço, hífen e ponto."""
    n = cnj(700 + len(pdf_trib))
    cad.datajud.fontes[n[1]] = fonte_datajud(n[1])
    _, p = ingerir(cad.ana, n[0], variante=pdf_trib, campos={"tribunal": pdf_trib})
    assert p.cnj_validacao == "confere", pdf_trib


def test_divergencia_de_tribunal(cad, ingerir):
    """CAD-10: diferente → divergente + pendência 'Divergência com o CNJ: <campo> (PDF: x · CNJ: y)'; processo segue gravado."""
    _, p = _cadastrar(cad, ingerir, fonte=fonte_datajud(DIG, tribunal="TJRJ"))
    assert p.cnj_validacao == "divergente" and p.status == "COM_PENDENCIAS"
    pend = [x for x in p.pendencias if x.startswith("Divergência com o CNJ: ")]
    assert len(pend) == 1 and "(PDF: TJSP · CNJ: TJRJ)" in pend[0] and p.cnj_divergencias and p.tribunal == "TJSP"


def test_divergencia_de_data_distribuicao(cad, ingerir):
    """CAD-23(6): data do PDF vs parte de data de dataAjuizamento, sem fuso."""
    _, p = _cadastrar(cad, ingerir, fonte=fonte_datajud(DIG, ajuizamento="2021-01-10T00:00:00.000Z"))
    assert p.cnj_validacao == "divergente" and any("2022" in x or "15/03/2022" in x for x in p.pendencias + p.cnj_divergencias)


def test_data_do_cnj_com_hora_tarde_nao_muda_o_dia(cad, ingerir):
    """CAD-23(6): sem conversão de fuso — '2022-03-15T23:30:00.000Z' ainda é 15/03/2022 → confere."""
    _, p = _cadastrar(cad, ingerir, fonte=fonte_datajud(DIG, ajuizamento="2022-03-15T23:30:00.000Z"))
    assert p.cnj_validacao == "confere"


def test_comarca_contida_no_orgao_julgador_sem_acento_e_caixa(cad, ingerir):
    """CAD-10/23(6): comarca do PDF normalizada contida no nome do órgão julgador normalizado → confere; senão diverge."""
    _, p = _cadastrar(cad, ingerir, campos={"comarca": "SAO PAULO"})
    assert p.cnj_validacao == "confere"
    n2 = cnj(1235)
    cad.datajud.fontes[n2[1]] = fonte_datajud(n2[1], orgao="2ª Vara Cível de Campinas")
    _, p2 = _cadastrar(cad, ingerir, numero=n2[0], dig=n2[1], fonte=False, variante="z")
    assert p2.cnj_validacao == "divergente" and any("comarca" in x.lower() for x in p2.pendencias)


def test_campo_vazio_no_pdf_nao_diverge(cad, ingerir):
    """CAD-23(6): só compara campo que o PDF trouxe; vazio não é divergência."""
    _, p = _cadastrar(cad, ingerir, campos={"comarca": "", "tribunal": "", "distribuido_em": ""})
    assert p.cnj_validacao in ("confere", "divergente") and not any("Divergência" in x for x in p.pendencias)


def test_nao_encontrado_e_alerta_sem_pendencia(cad, ingerir, ver):
    """CAD-10: não achou → nao_encontrado; alerta 'Não encontrado no DataJud: segredo de justiça ou ainda não indexado.'; sem pendência."""
    _, p = _cadastrar(cad, ingerir, fonte=False)
    assert p.cnj_validacao == "nao_encontrado" and not any("DataJud" in x for x in p.pendencias) and p.status == "CONFERIR"
    t = ver.texto(cad.ana.get(reverse("juridico:processo", kwargs={"pk": p.pk})))
    assert "Não encontrado no DataJud: segredo de justiça ou ainda não indexado." in t


@pytest.mark.parametrize("status", [401, 403])
def test_chave_do_datajud_recusada(cad, ingerir, ver, status):
    """CAD-10: 401/403 → falhou; erro no Log 'Chave do DataJud recusada: atualize a credencial em Configuração.'; processo gravado."""
    cad.datajud.status = status
    item, p = _cadastrar(cad, ingerir, fonte=False)
    assert p is not None and p.cnj_validacao == "falhou" and item.status == "concluido"
    assert item.etapa_erro == "CNJ (DataJud)" and item.motivo == "Chave do DataJud recusada: atualize a credencial em Configuração."
    assert "Chave do DataJud recusada: atualize a credencial em Configuração." in ver.texto(cad.adm.get(reverse("juridico:erros")))


def test_aviso_de_chave_recusada_so_no_painel_do_adm(cad, ingerir, ver):
    """CAD-10/19: aviso no painel para o Adm (contexto aviso_datajud só Adm)."""
    cad.datajud.status = 401
    _cadastrar(cad, ingerir, fonte=False)
    r_adm = cad.adm.get(reverse("juridico:painel"))
    r_base = cad.ana.get(reverse("juridico:painel"))
    assert r_adm.context["aviso_datajud"] and not r_base.context["aviso_datajud"]
    assert "DataJud" in ver.texto(r_adm)


def test_outras_falhas_do_datajud_gravam_o_processo(cad, ingerir):
    """CAD-10: outras falhas (500) → falhou, processo gravado mesmo assim."""
    cad.datajud.status = 500
    item, p = _cadastrar(cad, ingerir, fonte=False)
    assert p is not None and p.cnj_validacao == "falhou" and item.status == "concluido"


def test_datajud_inacessivel_e_timeout_nao_perdem_o_processo(cad, ingerir, settings):
    """CAD-10: prazo (JURIDICO_DATAJUD_TIMEOUT_S) estourado → falhou, processo gravado."""
    settings.JURIDICO_DATAJUD_TIMEOUT_S = 1
    cad.datajud.atraso = 3
    item, p = _cadastrar(cad, ingerir, fonte=False)
    assert p is not None and p.cnj_validacao == "falhou" and item.status == "concluido"


def test_no_maximo_uma_consulta_a_cada_1_5s(cad, enviar_cnj, rodar, settings):
    """CAD-10: intervalo mínimo de 1,5 s entre consultas ao DataJud (JURIDICO_DATAJUD_INTERVALO_S)."""
    settings.JURIDICO_DATAJUD_INTERVALO_S = 1.5
    nums = [cnj(800 + i) for i in range(3)]
    for _n, d in nums:
        cad.datajud.fontes[d] = fonte_datajud(d)
    enviar_cnj(cad.ana, "\n".join(n for n, _ in nums), cad.carteiras["Ativos"])
    inicio = time.monotonic()
    rodar()
    ts = cad.datajud.instantes
    assert len(ts) == 3 and all(b - a >= 1.45 for a, b in zip(ts, ts[1:], strict=False)) and time.monotonic() - inicio >= 2.9


def test_datajud_url_interna_e_bloqueada(cad, ingerir):
    """CAD-07/10 (SSRF): datajud_url para endereço interno → falhou, nada enviado; processo gravado."""
    cad.config.datajud_url = "http://169.254.169.254/datajud"
    cad.config.save()
    _, p = _cadastrar(cad, ingerir, fonte=False)
    assert p is not None and p.cnj_validacao == "falhou" and cad.datajud.buscas == []


def test_chave_do_datajud_nunca_aparece_em_nada(cad, ingerir):
    """CAD-18: valor da credencial do DataJud fora de motivos, pendências e itens."""
    cad.datajud.status = 401
    item, p = _cadastrar(cad, ingerir, fonte=False)
    blob = json.dumps([item.motivo, item.resposta_ia, p.pendencias, p.cnj_divergencias, p.observacoes], default=str)
    assert SEGREDO_DATAJUD not in blob


# ---------------- caminho CNJ (sem PDF) ----------------

def test_cadastro_so_pelo_numero_usa_empresa_da_carteira(cad, enviar_cnj, rodar):
    """CAD-05/10 + modelo Carteira.empresa: cadastro só do CNJ → Processo criado_via=cnj, empresa da carteira escolhida, dados do DataJud."""
    cad.datajud.fontes[DIG] = fonte_datajud(DIG, assuntos=("Obrigações", "Cobrança"))
    enviar_cnj(cad.ana, NUM, cad.carteiras["Ailos"])
    rodar()
    item = cad.ItemEnvio.objects.get()
    p = item.processo
    assert item.status == "concluido" and item.acao == "novo" and p.criado_via == "cnj" and p.criado_por == cad.ana_u
    assert p.empresa == cad.carteiras["Ailos"].empresa and p.carteira == cad.carteiras["Ailos"] and p.numero == NUM
    assert p.tribunal == "TJSP" and str(p.distribuido_em) == "2022-03-15" and p.cnj_validacao == "confere"
    assert "Obrigações" in p.assuntos_cnj and "Obrigações" not in (p.pedidos or "")


def test_cnj_andamentos_com_fonte_cnj(cad, enviar_cnj, rodar):
    """CAD-11: andamentos vindos do DataJud entram com fonte 'cnj'."""
    cad.datajud.fontes[DIG] = fonte_datajud(DIG, movimentos=[("2023-01-05T10:00:00.000Z", "Juntada de petição")])
    enviar_cnj(cad.ana, NUM, cad.carteiras["Ativos"])
    rodar()
    p = cad.Processo.objects.get()
    assert any(a["fonte"] == "cnj" and "Juntada" in a["evento"] for a in p.andamentos)


def test_consultar_cnj_de_novo(cad, ingerir):
    """CAD-15: 'Consultar CNJ de novo' (POST) refaz a validação e atualiza cnj_validacao/consultado_em."""
    _, p = _cadastrar(cad, ingerir, fonte=False)
    assert p.cnj_validacao == "nao_encontrado"
    cad.datajud.fontes[DIG] = fonte_datajud(DIG)
    antes = p.cnj_consultado_em
    r = cad.ana.post(reverse("juridico:consultar_cnj", kwargs={"pk": p.pk}))
    p.refresh_from_db()
    assert r.status_code == 302 and p.cnj_validacao == "confere" and p.cnj_consultado_em > antes
