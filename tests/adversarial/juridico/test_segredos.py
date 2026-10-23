"""Adversarial M8 · as chaves do Dify e do DataJud nunca aparecem (CAD-18, CRD-02, SEG-09/11): tela, log, resposta_ia, motivo, JSON de status, banco."""
import json
import logging

import pytest
from django.urls import reverse

from .conftest import (
    SEGREDO_DATAJUD,
    SEGREDO_DIFY,
    cnj,
    fonte_datajud,
    pdf_processo,
    tudo_que_o_usuario_pode_ver,
)

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

NUM, DIG = cnj(1234)
SEGREDOS = (SEGREDO_DIFY, SEGREDO_DATAJUD)


def _limpo(texto):
    for s in SEGREDOS:
        assert s not in texto, s
    assert "APIKey " + SEGREDO_DATAJUD not in texto and f"Bearer {SEGREDO_DIFY}" not in texto


def test_cenario_completo_com_todas_as_falhas_nao_vaza_chave(cad, enviar, rodar, caplog):
    """CAD-18: roda sucesso, 401/403/500 do Dify, timeout, 401/500 do DataJud, testar conexão, tentar de novo e erro de config; varre TUDO."""
    caplog.set_level(logging.DEBUG)
    cad.dify.eco_chave = True
    cad.datajud.fontes[DIG] = fonte_datajud(DIG)
    enviar(cad.ana, pdf_processo(NUM, "ok"))
    rodar()
    for modo in ("401", "403", "500", "invalido"):
        cad.dify.modo = modo
        enviar(cad.ana, pdf_processo(cnj(20 + len(modo))[0], modo))
        rodar()
    cad.dify.modo = None
    cad.datajud.status = 401
    enviar(cad.bruno, pdf_processo(cnj(40)[0], "dj401"))
    rodar()
    cad.datajud.status = 500
    enviar(cad.bruno, pdf_processo(cnj(41)[0], "dj500"))
    rodar()
    cad.datajud.status = 200
    cad.adm.post(reverse("juridico:testar_conexao"))
    for it in cad.ItemEnvio.objects.filter(status="erro"):
        cad.adm.post(reverse("juridico:tentar_de_novo", kwargs={"pk": it.pk}))
    cad.Config.objects.filter(pk=cad.config.pk).update(dify_credencial="Fantasma")
    enviar(cad.ana, pdf_processo(cnj(60)[0], "semcred"))
    rodar()
    _limpo("".join(f"{i.motivo}{i.resposta_ia}" for i in cad.ItemEnvio.objects.all()))
    _limpo(caplog.text)
    for cli in (cad.adm, cad.ana, cad.bruno):
        _limpo(tudo_que_o_usuario_pode_ver(cad, cli))
    for env in cad.Envio.objects.all():
        _limpo(json.dumps(cad.adm.get(reverse("juridico:status") + f"?envio={env.pk}").json()))


def test_nenhum_campo_do_banco_do_juridico_guarda_a_chave(cad, enviar, rodar):
    """CAD-18/CAD-01 (modelo): o banco do Jurídico guarda só dados extraídos — nunca o valor da credencial (ConfigCadastro guarda só o NOME)."""
    cad.dify.eco_chave = True
    cad.dify.extra = {"vazou": f"Bearer {SEGREDO_DIFY}"}
    enviar(cad.ana, pdf_processo(NUM))
    rodar()
    cfg = cad.Config.objects.get()
    assert cfg.dify_credencial == "Dify chave" and cfg.datajud_credencial == "DataJud chave"
    item = cad.ItemEnvio.objects.get()
    assert SEGREDO_DIFY not in (item.resposta_ia or "") and "••••" in (item.resposta_ia or "")
    for cmpo in ("dify_url", "dify_credencial", "dify_usuario", "dify_ca_pem", "datajud_url", "datajud_credencial"):
        assert not any(s in str(getattr(cfg, cmpo) or "") for s in SEGREDOS), cmpo


def test_chave_nao_vai_para_quem_nao_e_o_destino(cad, enviar, rodar):
    """CAD-18/SEG-01: o Authorization do Dify só chega ao host do dify_url (nunca ao DataJud) e o do DataJud só ao seu host."""
    cad.datajud.fontes[DIG] = fonte_datajud(DIG)
    enviar(cad.ana, pdf_processo(NUM))
    rodar()
    for r in cad.srv.requisicoes:
        auth = r["headers"].get("authorization", "")
        if r["rota"].startswith("/dify"):
            assert auth == f"Bearer {SEGREDO_DIFY}" and SEGREDO_DATAJUD not in json.dumps(r["headers"])
        if r["rota"].startswith("/datajud"):
            assert auth == f"APIKey {SEGREDO_DATAJUD}" and SEGREDO_DIFY not in json.dumps(r["headers"])


def test_chave_nao_vai_na_url_nem_no_corpo(cad, enviar, rodar):
    """SEG-09/11: a chave viaja só em header (nunca em query string, caminho ou corpo)."""
    cad.datajud.fontes[DIG] = fonte_datajud(DIG)
    enviar(cad.ana, pdf_processo(NUM))
    rodar()
    for r in cad.srv.requisicoes:
        assert SEGREDO_DIFY not in r["path"] + r["corpo"] and SEGREDO_DATAJUD not in r["path"] + r["corpo"]


def test_erro_inesperado_do_worker_nao_imprime_a_chave(cad, enviar, rodar, capsys, caplog):
    """SEG-11: mesmo com o Dify devolvendo lixo/stack, stdout/stderr/log do worker não contêm a chave."""
    caplog.set_level(logging.DEBUG)
    cad.srv.rotas["/dify/chat-messages"] = lambda req: (500, f"Traceback (most recent call last): Authorization: {req['headers']['authorization']}".encode(), None)
    enviar(cad.ana, pdf_processo(NUM))
    rodar()
    saida = capsys.readouterr()
    _limpo(saida.out + saida.err + caplog.text)
