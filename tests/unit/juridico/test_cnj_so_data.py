"""D-062: divergência só na data de distribuição não tira o "confere"; fica como aviso."""

import importlib
from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps
from django.urls import reverse

from apps.juridico import apresentacao, cnj, mescla
from apps.juridico.models import Processo

pytestmark = pytest.mark.modulo("m8")

DATA = "distribuído em (PDF: 15/03/2022 · CNJ: 10/01/2021)"
COMARCA = "comarca (PDF: Santos · CNJ: 2ª Vara Cível de Campinas)"


def _processo(seq=1, **campos):
    numero = cnj.numero_valido_de(seq, 2022, 8, 26, 100)
    dados = {
        "tribunal": "TJSP", "comarca": "São Paulo", "juizo": "1ª Vara", "adverso_nome": "Fulano",
        "valor_causa": Decimal("1234.56"), "distribuido_em": "2022-03-15", "status": "CONFERIR",
    }  # fmt: skip
    dados.update(campos)
    return Processo.objects.create(
        numero=numero, numero_digitos=cnj.so_digitos(numero), numero_valido=True,
        origem_campos={}, **dados,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("divergencias", "situacao"),
    [
        ([], "confere"),
        ([DATA], "confere"),
        ([COMARCA], "divergente"),
        ([DATA, COMARCA], "divergente"),
    ],
)
def test_situacao_pela_divergencia(divergencias, situacao):
    assert mescla.situacao_cnj(divergencias) == situacao


def test_comparar_so_data_registra_e_confere():
    p = Processo(tribunal="TJSP", comarca="São Paulo", distribuido_em=date(2022, 3, 15))
    fonte = {
        "tribunal": "TJSP",
        "dataAjuizamento": "2021-01-10T00:00:00.000Z",
        "orgaoJulgador": {"nome": "1ª Vara Cível de São Paulo"},
    }
    divergencias = mescla.comparar(p, fonte)
    assert divergencias == [DATA] and mescla.situacao_cnj(divergencias) == "confere"


def test_selo_verde_com_a_data_no_title():
    p = Processo(cnj_validacao="confere", cnj_divergencias=[DATA], status="CONFERIR")
    selo = apresentacao.selos_integracao(p)[0]
    assert selo["estado"] == "ok" and selo["texto"] == "✓ DataJud"
    assert selo["titulo"] == f"CNJ: confere (DataJud); só difere: {DATA}"


@pytest.mark.django_db
def test_lista_verde_e_ficha_com_o_aviso(cliente_adm):
    p = _processo(cnj_validacao="confere", cnj_divergencias=[DATA])
    resposta = cliente_adm.get(reverse("juridico:painel"), {"p": p.pk})
    html = resposta.content.decode()
    assert "✓ DataJud" in html and "! DataJud diverge" not in html
    assert 'data-cnj="confere"' in html and "Confere com o CNJ" in html
    assert f'<span class="faixa-cnj__aviso">{DATA} · vale o PDF</span>' in html
    confere = cliente_adm.get(reverse("juridico:painel"), {"cnj": "confere"}).context["processos"]
    assert [x.pk for x in confere] == [p.pk]


@pytest.mark.django_db
def test_conferencia_mostra_o_aviso(cliente_adm):
    p = _processo(cnj_validacao="confere", cnj_divergencias=[DATA])
    html = cliente_adm.get(reverse("juridico:processo", kwargs={"pk": p.pk})).content.decode()
    assert "Os dados conferem com o DataJud." in html and f"Só difere: {DATA} (vale o PDF)" in html


@pytest.mark.django_db
def test_migracao_passa_so_data_para_confere():
    so_data = _processo(1, cnj_validacao="divergente", cnj_divergencias=[DATA])
    mista = _processo(2, cnj_validacao="divergente", cnj_divergencias=[DATA, COMARCA])
    so_comarca = _processo(3, cnj_validacao="divergente", cnj_divergencias=[COMARCA])
    migracao = importlib.import_module("apps.juridico.migrations.0006_cnj_so_data_confere")
    migracao.para_confere(apps, None)
    situacoes = dict(Processo.objects.values_list("pk", "cnj_validacao"))
    assert situacoes == {so_data.pk: "confere", mista.pk: "divergente", so_comarca.pk: "divergente"}
    assert migracao.SO_AVISO == mescla.SO_AVISO
