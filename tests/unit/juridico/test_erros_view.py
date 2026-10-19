"""T-078: contexto do Log de erros (CAD-17)."""

import pytest
from django.urls import reverse

from apps.juridico.models import ConfigCadastro, Envio, ItemEnvio

pytestmark = [pytest.mark.modulo("m8"), pytest.mark.django_db]


def test_cartoes_do_log_com_unidade_e_etapas(cliente_adm, usuario_adm):
    ConfigCadastro.obter()
    for etapa, status in ((None, "concluido"), ("IA (Dify)", "erro")):
        envio = Envio.objects.create(origem="pdf", enviado_por=usuario_adm)
        ItemEnvio.objects.create(
            envio=envio, nome_arquivo="a.pdf", status=status, etapa_erro=etapa, motivo="m"
        )
    contexto = cliente_adm.get(reverse("juridico:erros")).context
    cartoes = contexto["cartoes"]
    assert cartoes["execucoes"] == {"envios": "2 envios", "casos": "2 casos"}
    assert cartoes["casos_erro"]["n"] == 1 and cartoes["erros_pendentes"] == 1
    assert [e["total"] for e in contexto["erros_por_etapa"]] == [0, 0, 0, 0, 1]
    assert contexto["casos_por_dia"][0]["erro"] == 1 and contexto["casos_por_dia"][0]["ok"] == 1
    assert len(contexto["itens"]) == 1 and contexto["filtro_resolvido"] is False


def test_html_mostra_execucoes(cliente_adm, usuario_adm):
    envio = Envio.objects.create(origem="pdf", enviado_por=usuario_adm)
    ItemEnvio.objects.create(envio=envio, nome_arquivo="a.pdf", status="concluido")
    html = cliente_adm.get(reverse("juridico:erros")).content.decode()
    assert "1 envio · 1 caso" in html


def test_valor_da_causa_abre_em_formato_brasileiro_e_salva_igual(cliente_adm, usuario_adm):
    from decimal import Decimal

    from apps.juridico import cnj
    from apps.juridico.forms import ProcessoForm, texto_valor
    from apps.juridico.models import Processo

    assert texto_valor(Decimal("12500")) == "12.500,00" and texto_valor(None) == ""
    numero = cnj.numero_valido_de(77, 2023, 8, 26, 1)
    processo = Processo.objects.create(
        numero=numero,
        numero_digitos=cnj.so_digitos(numero),
        numero_valido=True,
        valor_causa=Decimal("12500.00"),
    )
    assert ProcessoForm(instance=processo)["valor_causa"].value() == "12.500,00"
    resposta = cliente_adm.get(reverse("juridico:processo", kwargs={"pk": processo.pk}))
    assert 'value="12.500,00"' in resposta.content.decode()
    for texto in ("12.500,00", "12500,00", "12500.00"):
        cliente_adm.post(
            reverse("juridico:processo", kwargs={"pk": processo.pk}), {"valor_causa": texto}
        )
        processo.refresh_from_db()
        assert processo.valor_causa == Decimal("12500.00"), texto
