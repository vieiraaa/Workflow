"""Aceite M8 · mesclagem e conferência do processo (CAD-11, CAD-12, CAD-15, TEL-28). Só pela spec."""
import re
from decimal import Decimal

import pytest
from django.urls import reverse

from .conftest import cnj, criar_processo, fonte_datajud

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

NUM, DIG = cnj(1234)


def _url(p):
    return reverse("juridico:processo", kwargs={"pk": p.pk})


def _salvar(c, p, **campos):
    return c.post(_url(p), campos, follow=True)


# ---------------- mesclagem (CAD-11) ----------------

def test_pdf_substitui_campo_preenchido_e_diferente(cad, ingerir):
    """CAD-11: o PDF substitui todo campo que trouxer preenchido e diferente; os demais ficam."""
    _, p = ingerir(cad.ana, NUM, variante="a")
    _, p2 = ingerir(cad.bruno, NUM, variante="b", campos={"comarca": "Campinas", "juizo": "", "valor_causa": "R$ 9.999,99"})
    assert p2.pk == p.pk and p2.comarca == "Campinas" and p2.valor_causa == Decimal("9999.99")
    assert p2.juizo == "1ª Vara Cível"   # vazio no novo PDF não apaga
    assert p2.origem_campos["comarca"] == "pdf"


def test_pdf_vence_edicao_manual_em_campo_comum(cad, ingerir):
    """CAD-11: prioridade PDF > manual > CNJ — o PDF novo substitui um campo editado à mão."""
    _, p = ingerir(cad.ana, NUM, variante="a")
    _salvar(cad.ana, p, comarca="Manual City")
    p.refresh_from_db()
    assert p.comarca == "Manual City" and p.origem_campos["comarca"] == "manual"
    _, p2 = ingerir(cad.bruno, NUM, variante="b", campos={"comarca": "Do PDF"})
    assert p2.comarca == "Do PDF" and p2.origem_campos["comarca"] == "pdf"


def test_cnj_so_preenche_campo_vazio_e_nunca_sobrescreve_pdf(cad, ingerir):
    """CAD-11: o CNJ SÓ preenche campo vazio; nunca sobrescreve PDF (tribunal do PDF TJSP vs CNJ TJRJ)."""
    cad.datajud.fontes[DIG] = fonte_datajud(DIG, tribunal="TJRJ")
    _, p = ingerir(cad.ana, NUM, campos={"tribunal": "TJSP"})
    assert p.tribunal == "TJSP" and p.origem_campos["tribunal"] == "pdf"


def test_cnj_preenche_o_que_o_pdf_deixou_vazio(cad, ingerir):
    """CAD-11: campo vazio no PDF é preenchido pelo CNJ, com origem 'cnj'."""
    cad.datajud.fontes[DIG] = fonte_datajud(DIG, tribunal="TJSP", ajuizamento="2020-02-02T00:00:00.000Z")
    _, p = ingerir(cad.ana, NUM, campos={"tribunal": "", "distribuido_em": ""})
    assert p.tribunal == "TJSP" and str(p.distribuido_em) == "2020-02-02"
    assert p.origem_campos["tribunal"] == "cnj" and p.origem_campos["distribuido_em"] == "cnj"


def test_cnj_nao_sobrescreve_edicao_manual(cad, ingerir):
    """CAD-11: nem a 'Consultar CNJ de novo' sobrescreve campo editado à mão."""
    cad.datajud.fontes[DIG] = fonte_datajud(DIG, tribunal="TJSP", ajuizamento="2020-02-02T00:00:00.000Z")
    _, p = ingerir(cad.ana, NUM, campos={"tribunal": "", "distribuido_em": ""})
    _salvar(cad.ana, p, distribuido_em="2019-01-01")
    cad.ana.post(reverse("juridico:consultar_cnj", kwargs={"pk": p.pk}))
    p.refresh_from_db()
    assert str(p.distribuido_em) == "2019-01-01" and p.origem_campos["distribuido_em"] == "manual"


def test_cadastrado_nunca_volta_sozinho_e_preserva_campos_de_controle(cad, ingerir):
    """CAD-11/12: nunca mexe em status CADASTRADO, observações manuais, campos 'manuais' nem cadastrado_espaider_*."""
    _, p = ingerir(cad.ana, NUM, variante="a", carteira=cad.carteiras["Ativos"])
    _salvar(cad.ana, p, observacoes="Nota manual importante", responsavel="Fulana", gerencia="G1")
    cad.ana.post(reverse("juridico:marcar_cadastrado", kwargs={"pk": p.pk}))
    p.refresh_from_db()
    assert p.status == "CADASTRADO"
    quando, quem = p.cadastrado_espaider_em, p.cadastrado_espaider_por
    cad.dify.respostas[NUM] = None
    _, p2 = ingerir(cad.bruno, NUM, variante="b", campos={"comarca": "Nova Comarca", "tribunal": ""})
    assert p2.status == "CADASTRADO" and p2.cadastrado_espaider_em == quando and p2.cadastrado_espaider_por == quem
    assert "Nota manual importante" in p2.observacoes and p2.comarca == "Nova Comarca"
    assert p2.responsavel == "Fulana" and p2.gerencia == "G1"


def test_cadastrado_nao_e_recalculado_com_pendencia_nova(cad, ingerir):
    """CAD-12: 'recalculado a cada gravação, exceto quando CADASTRADO' — PDF que traz campo vazio/pendência não desmarca."""
    _, p = ingerir(cad.ana, NUM, variante="a", carteira=cad.carteiras["Ativos"])
    cad.ana.post(reverse("juridico:marcar_cadastrado", kwargs={"pk": p.pk}))
    _, p2 = ingerir(cad.bruno, NUM, variante="b", campos={"valor_causa": "ilegível total"})
    assert p2.status == "CADASTRADO"


def test_observacoes_ganham_a_linha_de_atualizacao_pelo_pdf(cad, ingerir):
    """CAD-11: Observações ganha 'Atualizado pelo PDF em DD/MM/AAAA HH:MM: <campos>.' sem apagar o que já havia."""
    _, p = ingerir(cad.ana, NUM, variante="a")
    _salvar(cad.ana, p, observacoes="Observação humana")
    _, p2 = ingerir(cad.bruno, NUM, variante="b", campos={"comarca": "Outra Comarca"})
    assert "Observação humana" in p2.observacoes
    assert re.search(r"Atualizado pelo PDF em \d{2}/\d{2}/\d{4} \d{2}:\d{2}: .*comarca.*\.", p2.observacoes, re.I)


def test_andamentos_pdf_ate_5_cnj_15_sem_repetir_em_ordem_decrescente(cad, ingerir):
    """CAD-11: andamentos = PDF (até 5) + CNJ (15 mais recentes), sem repetir (mesma data e texto), ordem decrescente."""
    pdf_movs = [{"data": f"{d:02d}/06/2023", "evento": f"Evento PDF {d}"} for d in range(1, 9)]  # 8 → entram 5
    cnj_movs = [(f"2023-{m:02d}-{d:02d}T10:00:00.000Z", f"Evento CNJ {m}-{d}") for m in (7, 8) for d in range(1, 11)]  # 20 → entram 15
    cnj_movs.append(("2023-06-01T10:00:00.000Z", "Evento PDF 1"))  # repete um do PDF (mesma data e texto)
    cad.datajud.fontes[DIG] = fonte_datajud(DIG, movimentos=cnj_movs)
    _, p = ingerir(cad.ana, NUM, campos={"ultimas_movimentacoes": pdf_movs})
    pdf = [a for a in p.andamentos if a["fonte"] == "pdf"]
    cn = [a for a in p.andamentos if a["fonte"] == "cnj"]
    assert len(pdf) == 5 and len(cn) <= 15 and len(cn) >= 14
    chaves = [(a["data"], a["evento"]) for a in p.andamentos]
    assert len(chaves) == len(set(chaves))

    def iso(d):
        d = str(d)[:10]
        return d if d[4] == "-" else f"{d[6:10]}-{d[3:5]}-{d[0:2]}"
    datas = [iso(a["data"]) for a in p.andamentos]
    assert datas == sorted(datas, reverse=True)


# ---------------- status e edição (CAD-12 / CAD-15) ----------------

def test_salvar_edicao_vira_manual_e_recalcula_status(cad, ingerir):
    """CAD-15: 'Salvar' → mensagem 'Processo salvo.', origem manual do campo editado, status recalculado (CAD-12)."""
    _, p = ingerir(cad.ana, NUM, carteira=cad.carteiras["Ativos"], campos={"comarca": ""})
    assert p.status == "COM_PENDENCIAS"
    r = _salvar(cad.ana, p, comarca="Preenchida à mão")
    p.refresh_from_db()
    assert "Processo salvo." in re.sub(r"\s+", " ", r.content.decode())
    assert p.comarca == "Preenchida à mão" and p.origem_campos["comarca"] == "manual"
    assert p.status == "CONFERIR" and not any(x.startswith("Verificar:") for x in p.pendencias)


def test_apagar_obrigatorio_volta_para_com_pendencias(cad):
    """CAD-12: remover um obrigatório na edição → pendência 'Verificar: …' e COM_PENDENCIAS."""
    p = criar_processo(cad)
    _salvar(cad.ana, p, juizo="")
    p.refresh_from_db()
    assert p.status == "COM_PENDENCIAS" and any(x.startswith("Verificar:") and "Juízo" in x for x in p.pendencias)


def test_campo_ausente_no_post_nao_muda(cad):
    """CAD-23 POST_processo: campo ausente = não muda."""
    p = criar_processo(cad, adverso_nome="Fulano", comarca="Rio")
    _salvar(cad.ana, p, comarca="Niterói")
    p.refresh_from_db()
    assert p.adverso_nome == "Fulano" and p.comarca == "Niterói"


@pytest.mark.parametrize("entrada", ["1234,56", "1.234,56", "1234.56"])
def test_valor_da_causa_aceita_os_tres_formatos(cad, entrada):
    """CAD-23: valor_causa '1234,56', '1.234,56' ou '1234.56'."""
    p = criar_processo(cad)
    _salvar(cad.ana, p, valor_causa=entrada)
    p.refresh_from_db()
    assert p.valor_causa == Decimal("1234.56")


def test_campos_invalidos_na_edicao_dao_erro_de_campo_sem_500(cad, ver):
    """CAD-15: data/valor/fase inválidos → 200 com erro no formulário; nada gravado."""
    p = criar_processo(cad, comarca="Rio")
    r = cad.ana.post(_url(p), {"comarca": "Mudou", "distribuido_em": "31/31/2022", "valor_causa": "abc", "fase_atual": "INVENTADA"})
    assert r.status_code == 200
    p.refresh_from_db()
    assert p.comarca == "Rio"


def test_fase_e_datas_editaveis(cad):
    """CAD-23: fase_atual (token), distribuido_em e data_citacao (AAAA-MM-DD), proxima_audiencia (AAAA-MM-DDTHH:MM)."""
    p = criar_processo(cad)
    _salvar(cad.ana, p, fase_atual="RECURSAL", data_citacao="2023-05-06", distribuido_em="2021-02-03")
    p.refresh_from_db()
    assert p.fase_atual == "RECURSAL" and str(p.data_citacao) == "2023-05-06" and str(p.distribuido_em) == "2021-02-03"


def test_marcar_cadastrado_so_com_status_conferir(cad, ver):
    """CAD-15: exige CONFERIR; com pendências → 'Resolva as pendências antes de marcar como cadastrado.' e nada muda."""
    p = criar_processo(cad, status="COM_PENDENCIAS", pendencias=["Verificar: Comarca"])
    r = cad.ana.post(reverse("juridico:marcar_cadastrado", kwargs={"pk": p.pk}), follow=True)
    p.refresh_from_db()
    assert "Resolva as pendências antes de marcar como cadastrado." in ver.texto(r) and p.status == "COM_PENDENCIAS"
    assert p.cadastrado_espaider_em is None


def test_marcar_cadastrado_grava_quem_e_quando(cad):
    """CAD-15: status CADASTRADO, cadastrado_espaider_por=quem clicou, _em=agora."""
    from django.utils import timezone
    p = criar_processo(cad)
    r = cad.bruno.post(reverse("juridico:marcar_cadastrado", kwargs={"pk": p.pk}))
    p.refresh_from_db()
    assert r.status_code == 302 and p.status == "CADASTRADO" and p.cadastrado_espaider_por == cad.bruno_u
    assert abs((timezone.now() - p.cadastrado_espaider_em).total_seconds()) < 60


def test_desfazer_cadastrado_so_adm_limpa_e_recalcula(cad):
    """CAD-15: 'Desfazer cadastrado' (Adm) tira de CADASTRADO e limpa quem/quando; status volta a ser calculado."""
    p = criar_processo(cad)
    cad.ana.post(reverse("juridico:marcar_cadastrado", kwargs={"pk": p.pk}))
    cad.adm.post(reverse("juridico:desfazer_cadastrado", kwargs={"pk": p.pk}))
    p.refresh_from_db()
    assert p.status == "CONFERIR" and p.cadastrado_espaider_em is None and p.cadastrado_espaider_por is None


def test_detalhe_mostra_cabecalho_chip_cnj_pendencias_e_origens(cad, ver):
    """CAD-15/TEL-28: número, chip de status, carteira, Baixar PDF, caixa Validação no CNJ, pendências, origem por campo."""
    p = criar_processo(cad, status="COM_PENDENCIAS", pendencias=["Verificar: Juízo"], cnj_validacao="divergente",
                       cnj_divergencias=["tribunal (PDF: TJSP · CNJ: TJRJ)"], origem_campos={"comarca": "pdf", "tribunal": "cnj", "juizo": "manual"},
                       andamentos=[{"data": "2023-01-05", "evento": "Juntada de petição", "fonte": "pdf"}])
    r = cad.ana.get(_url(p))
    t = ver.texto(r)
    assert p.numero in t and "Com pendências" in t and "Ativos" in t and "Validação no CNJ" in t and "diverge" in t.lower()
    assert "Verificar: Juízo" in t and "tribunal (PDF: TJSP · CNJ: TJRJ)" in t
    for rotulo in ("PDF", "CNJ", "manual"):
        assert rotulo.lower() in t.lower()
    for grupo in ("Identificação", "Cliente", "Adverso", "Jurisdição", "Datas e valores", "Pedidos", "Andamentos", "Controle"):
        assert grupo in t, grupo
    assert r.context["processo"].pk == p.pk and "form" in r.context and r.context["pendencias"] == ["Verificar: Juízo"]
    assert r.context["cnj"]["situacao"] == "divergente" and r.context["cnj"]["divergencias"] == ["tribunal (PDF: TJSP · CNJ: TJRJ)"]
    assert r.context["origem_campos"]["comarca"] == "pdf"


@pytest.mark.parametrize("status,rotulo", [("CONFERIR", "Conferir"), ("COM_PENDENCIAS", "Com pendências"), ("CADASTRADO", "Cadastrado no Espaider")])
def test_rotulos_do_status(cad, ver, status, rotulo):
    """modelo Processo.status: rótulos 'Com pendências' / 'Conferir' / 'Cadastrado no Espaider'."""
    p = criar_processo(cad, status=status)
    assert rotulo in ver.texto(cad.ana.get(_url(p)))


def test_flags_do_contexto_por_papel_e_estado(cad):
    """CAD-19: pode_editar, pode_marcar, pode_desfazer (desfazer só Adm e só se CADASTRADO)."""
    p = criar_processo(cad)
    c = cad.ana.get(_url(p)).context
    assert c["pode_editar"] is True and c["pode_marcar"] is True and c["pode_desfazer"] is False
    cad.ana.post(reverse("juridico:marcar_cadastrado", kwargs={"pk": p.pk}))
    assert cad.adm.get(_url(p)).context["pode_desfazer"] is True and cad.ana.get(_url(p)).context["pode_desfazer"] is False
    q = criar_processo(cad, status="COM_PENDENCIAS", pendencias=["Verificar: Juízo"])
    assert cad.ana.get(_url(q)).context["pode_marcar"] is False


def test_baixar_pdf_aparece_so_quando_ha_pdf(cad, ver, enviar, rodar):
    """CAD-15: 'Baixar PDF' só com item de origem PDF; processo manual não tem."""
    from .conftest import pdf_processo
    enviar(cad.ana, pdf_processo(NUM))
    rodar()
    p = cad.Processo.objects.get()
    assert "Baixar PDF" in ver.texto(cad.ana.get(_url(p)))
    q = criar_processo(cad, via="manual")
    assert "Baixar PDF" not in ver.texto(cad.ana.get(_url(q)))


def test_processo_inexistente_ou_excluido_da_404(cad):
    """TEL-28: pk inexistente → 404; processo excluído some (404 na conferência)."""
    from django.utils import timezone
    assert cad.ana.get(reverse("juridico:processo", kwargs={"pk": 99999})).status_code == 404
    p = criar_processo(cad, excluido_em=timezone.now(), excluido_por=cad.adm_u)
    assert cad.ana.get(_url(p)).status_code == 404
