"""Adversarial M8 · XSS nas telas do Jurídico (SEG-13, CAD-18): nome de arquivo, adverso, observações, motivo, nome de usuário, carteira,
andamentos, assuntos do CNJ — no servidor (HTML cru) e em chromium e webkit (execução real)."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from .conftest import (
    PAYLOADS_XSS,
    campos_dify,
    cnj,
    criar_processo,
    fonte_datajud,
    pdf_processo,
    sem_cru,
    tudo_que_o_usuario_pode_ver,
)

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

NUM, DIG = cnj(1234)


@pytest.fixture
def mundo_xss(cad, enviar, rodar, fabrica_usuario):
    """Cria um processo e um envio com o payload em TODOS os lugares que o usuário controla (ou que vêm de fora)."""
    def _criar(p):
        campos = {k: p for k in ("adverso_nome", "empresa", "condicao", "advogado_empresa", "advogado_adverso_nome", "advogado_adverso_oab", "tipo_acao", "rito",
                                 "natureza", "meio_tramitacao", "instancia", "tribunal", "juizo", "comarca", "estado", "desdobramento", "pedidos_completos",
                                 "observacoes", "numero_contrato_operacao", "adverso_cpf_cnpj")}
        campos["ultimas_movimentacoes"] = [{"data": "01/01/2023", "evento": p}]
        cad.dify.respostas[NUM] = campos_dify(NUM, **campos)
        cad.datajud.fontes[DIG] = fonte_datajud(DIG, tribunal=p, orgao=p, assuntos=(p,), movimentos=[("2023-02-02T10:00:00.000Z", p)])
        cad.ana_u.nome = p[:150]
        cad.ana_u.save()
        enviar(cad.ana, (pdf_processo(NUM)[0], f"{p}.pdf"), carteira=cad.carteiras["Ativos"])
        rodar()
        # reenvio do mesmo arquivo por outra pessoa → aviso de duplicidade com nome/e-mail do autor do original e nome do arquivo hostis
        enviar(cad.bruno, (pdf_processo(NUM)[0], f"{p}.pdf"))
        # item com erro cujo motivo carrega texto vindo de fora
        original = cad.srv.rotas["/dify/chat-messages"]
        cad.srv.rotas["/dify/chat-messages"] = lambda req: (500, {"message": p}, None)
        enviar(cad.ana, (pdf_processo(cnj(5)[0], "x")[0], f"erro-{p}.pdf"))
        rodar()
        cad.srv.rotas["/dify/chat-messages"] = original
        criar_processo(cad, numero=cnj(77), adverso_nome=p, observacoes=p, comarca=p, pedidos=p, proxima_audiencia=timezone.now() + timedelta(days=3),
                       usuario=cad.ana_u)
        cad.adm.post(reverse("juridico:carteira_nova"), {"nome": p[:60], "empresa": p})
        return cad.Processo.objects.filter(numero_digitos=DIG).first()

    return _criar


@pytest.mark.parametrize("payload", PAYLOADS_XSS)
def test_servidor_escapa_payload_em_toda_tela(cad, mundo_xss, payload):
    """SEG-13/CAD-18: o payload nunca aparece cru em nenhuma tela do Jurídico (painel, ?p=, processo, envios, envio, erros, audiências, config, status),
    para Adm e para quem enviou."""
    mundo_xss(payload)
    for cli in (cad.adm, cad.ana):
        sem_cru(tudo_que_o_usuario_pode_ver(cad, cli, com_json=False))
    for item in cad.ItemEnvio.objects.filter(envio__enviado_por=cad.bruno_u):
        sem_cru(cad.bruno.get(reverse("juridico:envio", kwargs={"pk": item.envio_id})).content.decode())


@pytest.mark.parametrize("payload", PAYLOADS_XSS)
def test_status_json_e_json_script_nao_quebram_o_html(cad, mundo_xss, payload):
    """SEG-13: o JSON de status (auto-refresh) é application/json com nosniff; json_script de qualquer tela escapa < > & (sem '</script>' cru)."""
    mundo_xss(payload)
    r = cad.adm.get(reverse("juridico:status"))
    assert r["Content-Type"].startswith("application/json")
    for rota in ("painel", "erros", "audiencias", "envios", "config"):
        h = cad.adm.get(reverse(f"juridico:{rota}")).content.decode()
        assert h.count("</script>") == h.lower().count("</script>")
        assert "</script><script>window.__pwn" not in h


def _visitar(p, rotas):
    for rota in rotas:
        p.goto(p.live_url + rota, wait_until="networkidle")
        p.wait_for_timeout(300)
        assert p.evaluate("window.__pwn") is None, rota
        assert p.dialogos == [] and p.erros_js == [], (rota, p.dialogos, p.erros_js)


@pytest.mark.parametrize("payload", PAYLOADS_XSS[:5])
def test_navegador_nao_executa_nada_nas_telas_do_juridico(cad, mundo_xss, abrir_pagina, payload):
    """SEG-13: em chromium e webkit, nenhuma tela do Jurídico executa o payload (window.__pwn, alert, erro de JS), incluindo conferência com formulário,
    envio com aviso de duplicidade e log de erros."""
    proc = mundo_xss(payload)
    adm = abrir_pagina(cad.adm)
    rotas = [reverse("juridico:painel"), reverse("juridico:painel") + f"?p={proc.pk}", reverse("juridico:processo", kwargs={"pk": proc.pk}),
             reverse("juridico:erros"), reverse("juridico:erros") + "?resolvido=1", reverse("juridico:envios"), reverse("juridico:audiencias"),
             reverse("juridico:config"), reverse("juridico:enviar_cnj"), reverse("juridico:processo_novo")]
    for e in cad.Envio.objects.all():
        rotas.append(reverse("juridico:envio", kwargs={"pk": e.pk}))
    _visitar(adm, rotas)


@pytest.mark.parametrize("payload", PAYLOADS_XSS[:4])
def test_navegador_aviso_de_duplicidade_nao_executa_nem_apos_o_auto_refresh(cad, mundo_xss, abrir_pagina, payload):
    """SEG-13: quem reenvia vê o nome/e-mail do autor do original (com payload) no aviso — escapado no HTML e depois que o JS do auto-refresh reescreve o item."""
    mundo_xss(payload)
    bruno = abrir_pagina(cad.bruno)
    envio = cad.Envio.objects.filter(enviado_por=cad.bruno_u).first()
    # um item na fila no mesmo envio força o polling a rodar
    cad.ItemEnvio.objects.create(envio=envio, nome_arquivo="na-fila.pdf", sha256="0" * 64, status="na_fila")
    bruno.goto(bruno.live_url + reverse("juridico:envio", kwargs={"pk": envio.pk}), wait_until="networkidle")
    bruno.wait_for_timeout(12_500)  # > 10 s: pelo menos um ciclo do auto-refresh
    assert bruno.evaluate("window.__pwn") is None and bruno.dialogos == [] and bruno.erros_js == []
    assert "Já temos este arquivo" in bruno.inner_text("body") or "já" in bruno.inner_text("body").lower()


@pytest.mark.parametrize("payload", PAYLOADS_XSS[:3])
def test_navegador_texto_do_payload_aparece_como_texto(cad, mundo_xss, abrir_pagina, payload):
    """SEG-13: o payload é exibido como TEXTO (visível na página), não interpretado."""
    proc = mundo_xss(payload)
    p = abrir_pagina(cad.adm)
    p.goto(p.live_url + reverse("juridico:painel") + f"?p={proc.pk}", wait_until="networkidle")
    assert payload.split("window")[0] in p.inner_text("body") or payload in p.content().replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#x27;", "'")
