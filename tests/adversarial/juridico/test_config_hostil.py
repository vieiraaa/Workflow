"""Adversarial M8 · configuração hostil (CAD-07/07a/14, SEG-01..08, CRD-02): URLs internas, PEM, credenciais, testar conexão."""
import pytest
from django.urls import reverse

from tests.acceptance.juridico.test_cad_erros_envios_config import _gerar_certificado

from .conftest import (
    SEGREDO_DATAJUD,
    SEGREDO_DIFY,
    cnj,
    pdf_processo,
    sem_cru,
    tudo_no_banco,
    tudo_que_o_usuario_pode_ver,
)

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

NUM, DIG = cnj(1234)

INTERNAS = ["http://169.254.169.254/latest/meta-data/", "http://localhost/x", "http://localhost./x", "http://[::1]/x", "http://[::ffff:127.0.0.1]/x",
            "http://0.0.0.0/x", "http://0x7f.1/x", "http://0177.0.0.1/x", "http://2130706433/x", "http://127.1/x", "http://10.0.0.1/x",
            "http://192.168.0.1/x", "http://172.16.0.1/x", "http://[fd00::1]/x", "http://user:senha@127.0.0.1/x", "http://exemplo.test@127.0.0.1/x",
            "http://metadata.google.internal/x", "http://127.0.0.1:1/x"]


def _cfg(cad, **mudancas):
    base = {"dify_url": f"{cad.srv.base}/dify", "dify_credencial": "Dify chave", "dify_usuario": "construtor-espaider", "dify_ca_pem": "",
            "datajud_url": f"{cad.srv.base}/datajud", "datajud_credencial": "DataJud chave", "setores_com_acesso": [cad.setor_a.pk]}
    base.update(mudancas)
    return cad.adm.post(reverse("juridico:config"), base)


@pytest.mark.parametrize("alvo", INTERNAS)
def test_dify_url_interna_nunca_recebe_requisicao(cad, enviar, rodar, alvo):
    """CAD-07: dify_url para endereço interno/metadados (aceita ou não pela tela) → o worker nunca envia; o item termina em erro e nada vai a lugar algum."""
    _cfg(cad, dify_url=alvo)
    cad.Config.objects.filter(pk=cad.config.pk).update(dify_url=alvo)  # mesmo que a tela recuse, o banco poderia ter o valor
    enviar(cad.ana, pdf_processo(NUM))
    rodar()
    item = cad.ItemEnvio.objects.get()
    assert item.status == "erro" and cad.srv.requisicoes == []
    assert "169.254" not in (item.motivo or "") and "127.0.0.1" not in (item.motivo or "") and "10.0.0.1" not in (item.motivo or "")


@pytest.mark.parametrize("alvo", INTERNAS)
def test_datajud_url_interna_nunca_recebe_requisicao(cad, ingerir, alvo):
    """CAD-10: datajud_url interna → validação 'falhou', processo gravado, nenhum acesso."""
    cad.Config.objects.filter(pk=cad.config.pk).update(datajud_url=alvo)
    item, p = ingerir(cad.ana, NUM)
    assert p is not None and p.cnj_validacao == "falhou" and cad.datajud.buscas == []


@pytest.mark.parametrize("alvo", ["file:///etc/passwd", "gopher://127.0.0.1/x", "ftp://exemplo.test/x", "javascript:alert(1)", "data:text/plain,x", "//127.0.0.1/x",
                                  "http://exemplo.test/\r\nHost: evil", "http://" + "a" * 100_000 + ".test/", "http://‮.test/", ""])
def test_urls_com_esquema_ou_forma_hostil_sao_recusadas_na_tela(cad, alvo):
    """CAD-14: URL não http(s)/gigante/com CRLF/vazia → erro de campo (200); nada gravado."""
    antes = cad.config.dify_url
    r = _cfg(cad, dify_url=alvo)
    cad.config.refresh_from_db()
    assert r.status_code == 200 and cad.config.dify_url == antes


def test_testar_conexao_com_url_interna_nao_conecta_nem_revela_o_ip(cad, ver):
    """CAD-14/SEG-10: 'Testar conexão' com dify_url interna não envia nada e a mensagem não contém IP interno nem a resposta crua."""
    cad.Config.objects.filter(pk=cad.config.pk).update(dify_url="http://169.254.169.254/latest", datajud_url="http://10.0.0.5/x")
    r = cad.adm.post(reverse("juridico:testar_conexao"), follow=True)
    t = ver.texto(r)
    msg = t[t.index("Dify:"):] if "Dify:" in t else ""
    assert cad.srv.requisicoes == [] and "Dify: falhou" in msg and "DataJud: falhou" in msg
    assert "169.254.169.254" not in msg.split("Credencial")[0] and "10.0.0.5" not in msg.split("Credencial")[0]


def test_testar_conexao_escapa_e_nao_reflete_corpo_nem_chave(cad, ver):
    """CAD-14/18: Dify/DataJud devolvem HTML e a chave no erro → mensagem escapada, sem chave, sem corpo cru."""
    cad.srv.rotas["/dify/chat-messages"] = lambda req: (500, f"<script>window.__pwn=1</script>{SEGREDO_DIFY} {req['headers']['authorization']}".encode(), None)
    cad.srv.rotas["/datajud/api_publica_tjsp/_search"] = lambda req: (500, f"<img src=x onerror=1>{SEGREDO_DATAJUD}".encode(), None)
    r = cad.adm.post(reverse("juridico:testar_conexao"), follow=True)
    h = r.content.decode()
    sem_cru(h)
    assert SEGREDO_DIFY not in h and SEGREDO_DATAJUD not in h and "<img src=x onerror=1>" not in h


def test_testar_conexao_nao_vira_scanner_via_config(cad):
    """CAD-14/SEG: mesmo com dify_url apontando para o próprio servidor liberado em outra porta (não liberada), nada é contatado."""
    from .conftest import ServidorLocal  # noqa: F401  (servidor extra, NÃO liberado)
    extra = ServidorLocal()
    try:
        cad.Config.objects.filter(pk=cad.config.pk).update(dify_url=f"{extra.base}/dify", datajud_url=f"{extra.base}/datajud")
        cad.adm.post(reverse("juridico:testar_conexao"))
        assert extra.requisicoes == []
    finally:
        extra.parar()


# ---------------- credenciais ----------------

def test_credencial_de_outro_tipo_ou_de_setor_nao_serve_ao_dify(cad, criar_cred, enviar, rodar):
    """CAD-14: dify_credencial deve ser bearer SEM setor; header/basic/smtp/de setor → erro no item e a chave NUNCA é enviada ao Dify."""
    criar_cred(nome="Dify de setor", tipo="bearer", valor="SEGREDO-DE-SETOR-1234567", setor=cad.setor_a.pk)
    criar_cred(nome="Dify header", tipo="header", valor="SEGREDO-HEADER-1234567", header_nome="X-Key")
    criar_cred(nome="Dify basic", tipo="basic", usuario="u", valor="SEGREDO-BASIC-1234567")
    criar_cred(nome="Dify smtp", tipo="smtp", usuario="u", host="smtp.exemplo.test", porta="587", valor="SEGREDO-SMTP-1234567")
    for i, nome in enumerate(("Dify de setor", "Dify header", "Dify basic", "Dify smtp", "Nao existe", "")):
        cad.Config.objects.filter(pk=cad.config.pk).update(dify_credencial=nome)
        cad.srv.requisicoes.clear()
        enviar(cad.ana, pdf_processo(cnj(10 + i)[0], str(i)))
        rodar()
        item = cad.ItemEnvio.objects.order_by("pk").last()
        if nome != "Dify de setor":
            assert item.status == "erro", nome
        for r in cad.srv.requisicoes:
            assert not any(s in " ".join(r["headers"].values()) for s in ("SEGREDO-DE-SETOR", "SEGREDO-HEADER", "SEGREDO-BASIC", "SEGREDO-SMTP")), nome


def test_tela_de_config_lista_so_credenciais_do_tipo_e_sem_setor(cad, criar_cred):
    """CAD-14/19: nomes de credenciais de setor/de outro tipo nunca aparecem nas listas; valores nunca em lugar nenhum."""
    criar_cred(nome="So do setor A", tipo="bearer", valor="SEGREDO-SETORIAL-ABCDEFG", setor=cad.setor_a.pk)
    ctx = cad.adm.get(reverse("juridico:config")).context
    nomes = {getattr(c, "nome", c) for c in list(ctx["credenciais_bearer"]) + list(ctx["credenciais_header"])}
    assert "So do setor A" not in nomes and "SEGREDO-SETORIAL-ABCDEFG" not in cad.adm.get(reverse("juridico:config")).content.decode()


def test_post_de_config_com_credencial_inexistente_ou_de_setor_e_recusado(cad, criar_cred):
    """CAD-14: gravar dify_credencial com nome que não existe/é de setor → recusado na tela (200), config intacta."""
    criar_cred(nome="Setorial", tipo="bearer", valor="SEGREDO-SETORIAL-ABCDEFG", setor=cad.setor_a.pk)
    for nome in ("Setorial", "Fantasma", "x" * 5000, "<script>window.__pwn=1</script>"):
        r = _cfg(cad, dify_credencial=nome)
        cad.config.refresh_from_db()
        assert r.status_code == 200 and cad.config.dify_credencial == "Dify chave", nome
        sem_cru(r.content.decode())


def test_config_xss_em_usuario_e_pem_nao_executa(cad):
    """SEG-13: dify_usuario com HTML aparece escapado na tela de config e no `user` enviado ao Dify (como dado JSON)."""
    xss = "<script>window.__pwn=1</script>"
    _cfg(cad, dify_usuario=xss)
    cad.config.refresh_from_db()
    h = cad.adm.get(reverse("juridico:config")).content.decode()
    sem_cru(h)


def test_setores_com_acesso_com_ids_invalidos(cad):
    """CAD-02/14: ids inexistentes/lixo em setores_com_acesso → erro de campo; o acesso atual não é perdido nem ampliado."""
    for v in (["99999"], ["abc"], ["-1"], ["1;2"], [cad.setor_b.pk, "99999"]):
        r = _cfg(cad, setores_com_acesso=v)
        assert r.status_code in (200, 302)
    assert set(cad.config.setores_com_acesso.values_list("pk", flat=True)) == {cad.setor_a.pk}
    assert cad.carla.get(reverse("juridico:painel")).status_code == 403


# ---------------- PEM ----------------

def test_pem_com_chave_privada_nunca_e_guardado(cad, ver):
    """CAD-07a: dify_ca_pem só aceita CERTIFICADO; se colarem uma chave privada, é recusada e NÃO fica gravada nem aparece na tela."""
    cert, chave = _gerar_certificado("127.0.0.1")
    for pem in (chave, cert + "\n" + chave, chave + "\n" + cert):
        r = _cfg(cad, dify_ca_pem=pem)
        cad.config.refresh_from_db()
        assert "PRIVATE KEY" not in (cad.config.dify_ca_pem or "") and "PRIVATE KEY" not in tudo_no_banco()
        assert r.status_code in (200, 302) and "PRIVATE KEY" not in cad.adm.get(reverse("juridico:config")).content.decode()


@pytest.mark.parametrize("pem", ["-----BEGIN CERTIFICATE-----\n" + "A" * 1_000_000 + "\n-----END CERTIFICATE-----", "-----BEGIN CERTIFICATE-----\n\x00\n-----END CERTIFICATE-----",
                                 "-----BEGIN CERTIFICATE-----\n</textarea><script>window.__pwn=1</script>\n-----END CERTIFICATE-----",
                                 "-----END CERTIFICATE-----\n-----BEGIN CERTIFICATE-----", "-----BEGIN CERTIFICATE-----" * 5000, "x" * 2_000_000])
def test_pem_hostil_e_recusado_sem_derrubar_nem_executar(cad, pem):
    """CAD-07a: PEM gigante/com NUL/HTML/invertido → 'Certificado inválido…' (200), nada gravado, sem 500 nem eco cru."""
    r = _cfg(cad, dify_ca_pem=pem)
    cad.config.refresh_from_db()
    assert r.status_code == 200 and not cad.config.dify_ca_pem
    sem_cru(r.content.decode())


def test_pem_com_varias_cas_aceita_so_certificados_validos(cad):
    """CAD-07a: PEM com um certificado válido + lixo no meio é recusado por inteiro (não grava meia confiança)."""
    cert, _ = _gerar_certificado("127.0.0.1")
    r = _cfg(cad, dify_ca_pem=cert + "\n-----BEGIN CERTIFICATE-----\nlixo\n-----END CERTIFICATE-----\n")
    cad.config.refresh_from_db()
    assert r.status_code == 200 and not cad.config.dify_ca_pem


def test_ca_do_dify_nao_se_aplica_ao_datajud_nem_ao_motor(cad, tmp_path, settings):
    """CAD-07a: com a CA colada, um DataJud HTTPS assinado pela MESMA CA em outro host/porta continua recusado (confiança só para o host do dify_url)."""
    import ssl
    import threading
    from http.server import ThreadingHTTPServer

    from tests.acceptance.m5.conftest import _Handler
    cert, chave = _gerar_certificado("127.0.0.1")
    (tmp_path / "c.pem").write_text(cert)
    (tmp_path / "k.pem").write_text(chave)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "c.pem", tmp_path / "k.pem")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    class E:
        requisicoes, rotas = [], {}

        def hits(self, p=""):
            return []
    httpd.estado = E()
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    porta = httpd.server_address[1]
    try:
        settings.MOTOR_SSRF_LIBERAR = [*settings.MOTOR_SSRF_LIBERAR, f"127.0.0.1:{porta}"]
        cad.Config.objects.filter(pk=cad.config.pk).update(dify_ca_pem=cert, datajud_url=f"https://127.0.0.1:{porta}/datajud")
        from .conftest import fonte_datajud
        cad.datajud.fontes[DIG] = fonte_datajud(DIG)
        enviar_item = cad.ana.post(reverse("juridico:enviar_pdfs"), {"arquivos": [__import__("tests.acceptance.juridico.conftest", fromlist=["upload"]).upload(*pdf_processo(NUM))], "carteira": ""})
        assert enviar_item.status_code == 302
        from django.core.management import call_command
        call_command("processar_cadastros", "--uma-vez")
        p = cad.Processo.objects.get()
        assert p.cnj_validacao == "falhou" and E.requisicoes == []
    finally:
        httpd.shutdown()
        httpd.server_close()


# ---------------- carteiras (XSS e limites) ----------------

@pytest.mark.parametrize("nome", ["<script>window.__pwn=1</script>", "<img src=x onerror=window.__pwn=1>", "\"><svg onload=window.__pwn=1>"])
def test_nome_de_carteira_hostil_nao_executa_em_nenhuma_tela(cad, nome):
    """SEG-13: nome/empresa de carteira com HTML (cabe em 60) aparece escapado no painel, formulários e telas de envio."""
    cad.adm.post(reverse("juridico:carteira_nova"), {"nome": nome[:60], "empresa": nome})
    sem_cru(tudo_que_o_usuario_pode_ver(cad, cad.adm))
    sem_cru(tudo_que_o_usuario_pode_ver(cad, cad.ana))


def test_carteira_com_nome_vazio_espacos_e_unicode_confuso(cad):
    """CAD-14: nomes vazios/espaços/homóglifos não criam carteira duplicada de 'Ativos' (único sem diferenciar maiúsculas)."""
    for nome in ("", "   ", "ATIVOS", "ativos", "Ａtivos", "Ativos​", "Ativos "):
        cad.adm.post(reverse("juridico:carteira_nova"), {"nome": nome, "empresa": "x"})
    nomes = [c.nome.strip().lower() for c in cad.Carteira.objects.all()]
    assert nomes.count("ativos") == 1 and "" not in nomes
