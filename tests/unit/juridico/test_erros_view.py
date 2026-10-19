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
