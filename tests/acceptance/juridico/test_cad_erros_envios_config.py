"""Aceite M8 · Log de erros, envios, configuração e segurança (CAD-13, CAD-14, CAD-17, CAD-18, CAD-19; TEL-31/32/33)."""
import json
import re
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from .conftest import SEGREDO_DATAJUD, SEGREDO_DIFY, cnj, criar_processo, pdf_processo

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

NUM, DIG = cnj(1234)


def _erro(cad, ingerir, modo="500", numero=NUM, variante="a", usuario=None):
    cad.dify.modo = modo
    item, _ = ingerir(usuario or cad.ana, numero, variante=variante)
    cad.dify.modo = None
    return item


# ---------------- travado e tentar de novo (CAD-13) ----------------

def test_item_travado_volta_para_a_fila_uma_vez(cad, enviar, rodar, settings):
    """CAD-13: item em 'processando' além do prazo (JURIDICO_TRAVADO_MIN) volta para a fila e é processado."""
    settings.JURIDICO_TRAVADO_MIN = 15
    enviar(cad.ana, pdf_processo(NUM))
    cad.ItemEnvio.objects.update(status="processando", tentativas=0, iniciado_em=timezone.now() - timedelta(minutes=40))
    rodar()
    item = cad.ItemEnvio.objects.get()
    assert item.status == "concluido" and cad.Processo.objects.count() == 1


def test_item_travado_pela_segunda_vez_vira_erro(cad, enviar, rodar, settings):
    """CAD-13: na 2ª vez travado → erro 'Processamento interrompido.'; não é reprocessado."""
    settings.JURIDICO_TRAVADO_MIN = 15
    enviar(cad.ana, pdf_processo(NUM))
    cad.ItemEnvio.objects.update(status="processando", tentativas=2, iniciado_em=timezone.now() - timedelta(minutes=40))
    rodar()
    item = cad.ItemEnvio.objects.get()
    assert item.status == "erro" and item.motivo == "Processamento interrompido." and cad.dify.chats == []


def test_item_em_processando_recente_nao_e_tocado(cad, enviar, rodar, settings):
    """CAD-13: dentro do prazo (15 min) o item em processando fica como está."""
    settings.JURIDICO_TRAVADO_MIN = 15
    enviar(cad.ana, pdf_processo(NUM))
    cad.ItemEnvio.objects.update(status="processando", iniciado_em=timezone.now() - timedelta(minutes=2))
    rodar()
    assert cad.ItemEnvio.objects.get().status == "processando" and cad.dify.chats == []


def test_tentar_de_novo_volta_para_a_fila_e_processa(cad, ingerir, rodar):
    """CAD-13: 'Tentar de novo' (POST) em item com erro → na_fila; ao processar de novo conclui."""
    item = _erro(cad, ingerir)
    assert item.status == "erro"
    r = cad.ana.post(reverse("juridico:tentar_de_novo", kwargs={"pk": item.pk}))
    item.refresh_from_db()
    assert r.status_code == 302 and item.status == "na_fila"
    rodar()
    item.refresh_from_db()
    assert item.status == "concluido" and item.processo_id


def test_tentar_de_novo_so_quem_enviou_ou_adm(cad, ingerir):
    """CAD-13: só quem enviou ou o Adm; outro usuário com acesso → 403/404 e o item segue em erro."""
    item = _erro(cad, ingerir)
    assert cad.bruno.post(reverse("juridico:tentar_de_novo", kwargs={"pk": item.pk})).status_code in (403, 404)
    assert cad.carla.post(reverse("juridico:tentar_de_novo", kwargs={"pk": item.pk})).status_code == 403
    item.refresh_from_db()
    assert item.status == "erro"
    assert cad.adm.post(reverse("juridico:tentar_de_novo", kwargs={"pk": item.pk})).status_code == 302
    item.refresh_from_db()
    assert item.status == "na_fila"


def test_tentar_de_novo_em_item_sem_erro_nao_muda_nada(cad, ingerir):
    """CAD-13: o botão é para item com erro — item concluído não volta para a fila."""
    item, _ = ingerir(cad.ana, NUM)
    r = cad.ana.post(reverse("juridico:tentar_de_novo", kwargs={"pk": item.pk}))
    item.refresh_from_db()
    assert r.status_code < 500 and item.status == "concluido"


# ---------------- Log de erros (CAD-17 / TEL-32) ----------------

def test_log_lista_erros_pendentes_com_etapa_e_motivo(cad, ingerir, ver):
    """CAD-17/23(5): Log = itens com etapa_erro preenchida (erro OU concluído com ressalva), com arquivo/CNJ, etapa e motivo."""
    e1 = _erro(cad, ingerir, "401", cnj(1)[0], "a")
    item2, _ = ingerir(cad.ana, cnj(2)[0], variante="b", campos={"comarca": ""})
    r = cad.adm.get(reverse("juridico:erros"))
    t = ver.texto(r)
    assert r.status_code == 200 and e1.nome_arquivo in t and "IA (Dify)" in t and e1.motivo in t
    assert "Dados incompletos" in t and item2.motivo in t and "Resolvido" in t
    assert set(ver.pks(r.context["itens"])) >= {e1.pk, item2.pk}


def test_log_mostra_cartoes_e_secoes(cad, ingerir, ver):
    """CAD-17: cartões e seções do desempenho (últimos 30 dias)."""
    ingerir(cad.ana, cnj(1)[0], variante="a")
    _erro(cad, ingerir, "500", cnj(2)[0], "b")
    t = ver.texto(cad.adm.get(reverse("juridico:erros")))
    for s in ("Última execução", "Execuções", "Casos com erro", "Tempo médio", "Erros pendentes", "Casos por dia", "Erros pendentes por etapa", "Envios"):
        assert s in t, s
    assert re.search(r"2 envios", t) and re.search(r"2 casos", t)


def test_marcar_resolvido_some_da_lista_e_volta_com_mostrar_resolvidos(cad, ingerir, ver):
    """CAD-17/13: 'Resolvido' (POST) marca resolvido=true; sai dos pendentes; ?resolvido=1 mostra os resolvidos."""
    e = _erro(cad, ingerir, "500")
    r = cad.ana.post(reverse("juridico:resolver", kwargs={"pk": e.pk}))
    e.refresh_from_db()
    assert r.status_code == 302 and e.resolvido is True
    pend = cad.adm.get(reverse("juridico:erros"))
    assert e.pk not in ver.pks(pend.context["itens"]) and pend.context["filtro_resolvido"] is False
    com = cad.adm.get(reverse("juridico:erros") + "?resolvido=1")
    assert e.pk in ver.pks(com.context["itens"]) and com.context["filtro_resolvido"] is True


def test_log_vazio(cad, ver):
    """TEL-32: estado vazio sem erro."""
    r = cad.adm.get(reverse("juridico:erros"))
    assert r.status_code == 200 and list(r.context["itens"]) == []


def test_log_nao_conta_erro_resolvido_em_erros_pendentes_do_painel(cad, ingerir):
    """CAD-17/19: resumo.erros = pendentes (não resolvidos)."""
    e = _erro(cad, ingerir, "500")
    assert cad.adm.get(reverse("juridico:painel")).context["resumo"]["erros"] == 1
    cad.adm.post(reverse("juridico:resolver", kwargs={"pk": e.pk}))
    assert cad.adm.get(reverse("juridico:painel")).context["resumo"]["erros"] == 0


def test_log_paginado(cad):
    """CAD-17/19: lista paginada (itens = página)."""
    envio = cad.Envio.objects.create(origem="cnj", enviado_por=cad.ana_u)
    for i in range(30):
        cad.ItemEnvio.objects.create(envio=envio, nome_arquivo="", sha256="", numero_informado=f"x{i}", status="erro", etapa_erro="CNJ (DataJud)", motivo=f"m{i}")
    r = cad.adm.get(reverse("juridico:erros"))
    assert 1 <= len(r.context["itens"]) <= 30


def test_log_exige_acesso(cad):
    """CAD-02: log de erros respeita o acesso."""
    assert cad.carla.get(reverse("juridico:erros")).status_code == 403
    assert cad.ana.post(reverse("juridico:resolver", kwargs={"pk": 1})).status_code in (404, 403)


# ---------------- envios (TEL-31) ----------------

def test_lista_de_envios_mais_recentes_primeiro_e_clicavel(cad, enviar, ver):
    """CAD-17/TEL-31: lista completa, recentes primeiro, com link para o envio."""
    enviar(cad.ana, pdf_processo(cnj(1)[0], "a"))
    enviar(cad.ana, pdf_processo(cnj(2)[0], "b"))
    e1, e2 = cad.Envio.objects.order_by("pk")
    r = cad.adm.get(reverse("juridico:envios"))
    h = ver.html(r)
    assert h.index(reverse("juridico:envio", kwargs={"pk": e2.pk})) < h.index(reverse("juridico:envio", kwargs={"pk": e1.pk}))


def test_detalhe_do_envio_mostra_itens_status_processo_e_tentar_de_novo(cad, ingerir, enviar, rodar, ver):
    """CAD-17: cada item com status, processo gerado, motivo do erro e 'Tentar de novo'; contexto envio/itens/url_status."""
    ok, p = ingerir(cad.ana, cnj(1)[0], variante="a")
    erro = _erro(cad, ingerir, "500", cnj(2)[0], "b")
    for item in (ok, erro):
        r = cad.ana.get(reverse("juridico:envio", kwargs={"pk": item.envio_id}))
        assert r.status_code == 200 and r.context["envio"].pk == item.envio_id and item.pk in ver.pks(r.context["itens"])
        assert r.context["url_status"].startswith(reverse("juridico:status"))
    t_ok = ver.texto(cad.ana.get(reverse("juridico:envio", kwargs={"pk": ok.envio_id})))
    assert "Concluído" in t_ok and reverse("juridico:processo", kwargs={"pk": p.pk}) in ver.html(cad.ana.get(reverse("juridico:envio", kwargs={"pk": ok.envio_id})))
    t_err = ver.texto(cad.ana.get(reverse("juridico:envio", kwargs={"pk": erro.envio_id})))
    assert erro.motivo in t_err and "Tentar de novo" in t_err


def test_status_json_do_envio_acompanha_a_fila(cad, enviar, rodar):
    """CAD-23 (8b): ?envio=<pk> devolve itens [{pk, status, processo_url|null, aviso|null, motivo|null}] e muda após o worker."""
    enviar(cad.ana, pdf_processo(NUM))
    item = cad.ItemEnvio.objects.get()
    url = reverse("juridico:status") + f"?envio={item.envio_id}"
    antes = cad.ana.get(url).json()["itens"][0]
    assert antes["status"] == "na_fila" and antes["processo_url"] is None and antes["motivo"] is None
    rodar()
    depois = cad.ana.get(url).json()["itens"][0]
    assert depois["status"] == "concluido" and depois["processo_url"] == reverse("juridico:processo", kwargs={"pk": cad.Processo.objects.get().pk})
    assert set(depois) >= {"pk", "status", "processo_url", "aviso", "motivo"}


# ---------------- Configuração (CAD-14 / TEL-33) ----------------

CFG_BASE = lambda cad: {  # noqa: E731
    "dify_url": f"{cad.srv.base}/dify", "dify_credencial": "Dify chave", "dify_usuario": "usuario-novo",
    "dify_ca_pem": "", "datajud_url": f"{cad.srv.base}/datajud", "datajud_credencial": "DataJud chave",
    "setores_com_acesso": [cad.setor_a.pk]}


def test_config_salva_campos_e_setores(cad):
    """CAD-14: URLs, nomes das credenciais, usuário do Dify e setores com acesso."""
    cad.adm.post(reverse("juridico:config"), {**CFG_BASE(cad), "setores_com_acesso": [cad.setor_a.pk, cad.setor_b.pk]})
    cad.config.refresh_from_db()
    assert cad.config.dify_usuario == "usuario-novo" and set(cad.config.setores_com_acesso.values_list("pk", flat=True)) == {cad.setor_a.pk, cad.setor_b.pk}
    assert cad.carla.get(reverse("juridico:painel")).status_code == 200


def test_config_contexto_so_lista_credenciais_sem_setor_do_tipo_certo(cad, criar_cred):
    """CAD-14/19: credenciais_bearer (bearer sem setor), credenciais_header (header sem setor) — com setor ou de outro tipo ficam de fora."""
    criar_cred(nome="Bearer de setor", tipo="bearer", valor="x" * 12, setor=cad.setor_a.pk)
    criar_cred(nome="Basica global", tipo="basic", usuario="u", valor="y" * 12)
    ctx = cad.adm.get(reverse("juridico:config")).context
    nomes = lambda lista: {getattr(c, "nome", c) for c in lista}  # noqa: E731
    assert "Dify chave" in nomes(ctx["credenciais_bearer"]) and "Bearer de setor" not in nomes(ctx["credenciais_bearer"])
    assert "DataJud chave" in nomes(ctx["credenciais_header"]) and "Dify chave" not in nomes(ctx["credenciais_header"])
    assert "Basica global" not in nomes(ctx["credenciais_bearer"]) | nomes(ctx["credenciais_header"])
    for k in ("form", "carteiras", "setores"):
        assert k in ctx


def test_config_nunca_exibe_valores_de_chave(cad, ver):
    """CAD-14/18: a tela só mostra NOMES de credencial; o valor nunca aparece."""
    h = ver.html(cad.adm.get(reverse("juridico:config")))
    assert SEGREDO_DIFY not in h and SEGREDO_DATAJUD not in h and "Dify chave" in h


def test_config_pem_invalido(cad, ver):
    """CAD-07a: PEM inválido → 'Certificado inválido: cole o PEM completo (BEGIN/END CERTIFICATE).' e nada gravado."""
    for pem in ("isto não é um certificado", "-----BEGIN CERTIFICATE-----\nlixo\n-----END CERTIFICATE-----", "-----BEGIN CERTIFICATE-----\nsemfim"):
        r = cad.adm.post(reverse("juridico:config"), {**CFG_BASE(cad), "dify_ca_pem": pem})
        assert r.status_code == 200 and "Certificado inválido: cole o PEM completo (BEGIN/END CERTIFICATE)." in ver.texto(r)
        cad.config.refresh_from_db()
        assert cad.config.dify_ca_pem in ("", None)


def test_config_pem_valido_e_salvo_e_vazio_limpa(cad):
    """CAD-07a: PEM válido é aceito; vazio = cadeia pública padrão."""
    pem = _gerar_certificado("127.0.0.1")[0]
    r = cad.adm.post(reverse("juridico:config"), {**CFG_BASE(cad), "dify_ca_pem": pem})
    cad.config.refresh_from_db()
    assert r.status_code == 302 and "BEGIN CERTIFICATE" in cad.config.dify_ca_pem
    cad.adm.post(reverse("juridico:config"), {**CFG_BASE(cad), "dify_ca_pem": ""})
    cad.config.refresh_from_db()
    assert cad.config.dify_ca_pem in ("", None)


def test_config_urls_invalidas_e_obrigatorias(cad):
    """CAD-14: URL vazia/sem esquema http(s) → erro de campo, nada gravado."""
    antes = cad.config.dify_url
    for ruim in ("", "ftp://x/y", "javascript:alert(1)", "sem-esquema"):
        assert cad.adm.post(reverse("juridico:config"), {**CFG_BASE(cad), "dify_url": ruim}).status_code == 200
    cad.config.refresh_from_db()
    assert cad.config.dify_url == antes


# ---------------- carteiras (CAD-14) ----------------

def test_carteira_nova_renomear_e_desativar(cad, ver):
    """CAD-14: adicionar, renomear, ativar/desativar carteiras (Adm)."""
    cad.adm.post(reverse("juridico:carteira_nova"), {"nome": "Nova Carteira", "empresa": "Nova Empresa Ltda"})
    c = cad.Carteira.objects.get(nome="Nova Carteira")
    assert c.empresa == "Nova Empresa Ltda" and c.ativa is True
    cad.adm.post(reverse("juridico:carteira_editar", kwargs={"pk": c.pk}), {"nome": "Renomeada", "empresa": "Nova Empresa Ltda", "ativa": "on"})
    c.refresh_from_db()
    assert c.nome == "Renomeada" and c.ativa is True
    cad.adm.post(reverse("juridico:carteira_editar", kwargs={"pk": c.pk}), {"nome": "Renomeada", "empresa": "Nova Empresa Ltda"})
    c.refresh_from_db()
    assert c.ativa is False


def test_carteira_nome_unico_sem_diferenciar_maiusculas_e_max_60(cad):
    """modelo Carteira: nome único (sem diferenciar maiúsculas), até 60 caracteres."""
    assert cad.adm.post(reverse("juridico:carteira_nova"), {"nome": "ATIVOS", "empresa": "x"}).status_code in (200, 302)
    assert cad.adm.post(reverse("juridico:carteira_nova"), {"nome": "y" * 61, "empresa": "x"}).status_code in (200, 302)
    assert cad.Carteira.objects.filter(nome__iexact="ativos").count() == 1 and not cad.Carteira.objects.filter(nome="y" * 61).exists()


def test_carteira_so_adm(cad):
    """cadastro.configurar: carteiras só Adm."""
    assert cad.ana.post(reverse("juridico:carteira_nova"), {"nome": "Intrusa", "empresa": "x"}).status_code == 403
    assert cad.bruno.post(reverse("juridico:carteira_editar", kwargs={"pk": cad.carteiras["Ativos"].pk}), {"nome": "Hackeada"}).status_code == 403
    cad.carteiras["Ativos"].refresh_from_db()
    assert cad.carteiras["Ativos"].nome == "Ativos" and not cad.Carteira.objects.filter(nome="Intrusa").exists()


def test_carteira_desativada_sai_da_lista_de_envio(cad, ver):
    """CAD-05/14: carteira desativada deixa de ser opção no formulário CNJ."""
    cad.adm.post(reverse("juridico:carteira_editar", kwargs={"pk": cad.carteiras["Ailos"].pk}), {"nome": "Ailos", "empresa": "x"})
    assert "Ailos" not in ver.html(cad.ana.get(reverse("juridico:enviar_cnj")))


# ---------------- testar conexão (CAD-14) ----------------

def test_testar_conexao_ok(cad, ver):
    """CAD-14: Dify com query 'ping' e DataJud com um número de exemplo → 'Dify: ok · DataJud: ok' (sem expor valores)."""
    r = cad.adm.post(reverse("juridico:testar_conexao"), follow=True)
    t = ver.texto(r)
    assert "Dify: ok" in t and "DataJud: ok" in t
    assert cad.dify.chats and cad.dify.chats[-1]["query"] == "ping" and cad.datajud.buscas
    assert SEGREDO_DIFY not in ver.html(r) and SEGREDO_DATAJUD not in ver.html(r)


def test_testar_conexao_falhou_mostra_motivo_sem_valores(cad, ver):
    """CAD-14: falha → 'Dify: falhou (<motivo>) · DataJud: …' sem expor a chave."""
    cad.dify.modo = "401"
    cad.datajud.status = 401
    r = cad.adm.post(reverse("juridico:testar_conexao"), follow=True)
    t = ver.texto(r)
    assert re.search(r"Dify: falhou \(.+\)", t) and "DataJud: falhou" in t
    assert SEGREDO_DIFY not in ver.html(r) and SEGREDO_DATAJUD not in ver.html(r)


def test_testar_conexao_um_ok_e_um_falhou(cad, ver):
    """CAD-14: resultados independentes por serviço."""
    cad.datajud.status = 500
    t = ver.texto(cad.adm.post(reverse("juridico:testar_conexao"), follow=True))
    assert "Dify: ok" in t and "DataJud: falhou" in t


# ---------------- TLS do Dify (CAD-07a) ----------------

def _gerar_certificado(ip):
    """Certificado autoassinado FICTÍCIO (CA=true) para 127.0.0.1 → (pem_cert, pem_chave)."""
    import datetime
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    chave = ec.generate_private_key(ec.SECP256R1())
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CA Ficticia de Teste")])
    agora = datetime.datetime.now(datetime.UTC)
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(agora - datetime.timedelta(days=1)).not_valid_after(agora + datetime.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(chave.public_key()), critical=False)
            .sign(chave, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM).decode(),
            chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())


@pytest.fixture
def dify_https(cad, tmp_path):
    """Dify FALSO por HTTPS com certificado autoassinado (local, 127.0.0.1) — liberado só no teste."""
    import ssl
    import threading
    from http.server import ThreadingHTTPServer

    from tests.acceptance.m5.conftest import _Handler

    pem, chave = _gerar_certificado("127.0.0.1")
    (tmp_path / "c.pem").write_text(pem)
    (tmp_path / "k.pem").write_text(chave)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(tmp_path / "c.pem", tmp_path / "k.pem")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    httpd.daemon_threads = True
    httpd.estado = _Estado()
    from .conftest import DifyFalso
    falso = DifyFalso(httpd.estado, "/dify")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    porta = httpd.server_address[1]
    yield SimpleNamespace_(pem=pem, porta=porta, dify=falso, srv=httpd.estado)
    httpd.shutdown()
    httpd.server_close()


class _Estado:
    def __init__(self):
        self.requisicoes, self.rotas = [], {}

    def hits(self, prefixo=""):
        return [r for r in self.requisicoes if r["rota"].startswith(prefixo)]


class SimpleNamespace_:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_certificado_desconhecido_e_recusado_com_mensagem_propria(cad, dify_https, ingerir, settings):
    """CAD-07a: verificação TLS NUNCA desligada — servidor com certificado de CA desconhecida → erro 'Não foi possível validar o certificado do Dify. …'."""
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{cad.srv.porta}", f"127.0.0.1:{dify_https.porta}"]
    cad.config.dify_url = f"https://127.0.0.1:{dify_https.porta}/dify"
    cad.config.dify_ca_pem = ""
    cad.config.save()
    item, p = ingerir(cad.ana, NUM)
    assert item.status == "erro" and p is None and dify_https.srv.requisicoes == []
    assert item.motivo == "Não foi possível validar o certificado do Dify. Peça à TI um certificado válido ou cadastre a CA em Configuração."


def test_ca_cadastrada_vale_so_para_o_host_do_dify(cad, dify_https, ingerir, settings):
    """CAD-07a: com dify_ca_pem preenchido o cliente confia nessa CA (além da padrão) — e a requisição chega ao Dify."""
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{cad.srv.porta}", f"127.0.0.1:{dify_https.porta}"]
    cad.config.dify_url = f"https://127.0.0.1:{dify_https.porta}/dify"
    cad.config.dify_ca_pem = dify_https.pem
    cad.config.save()
    item, p = ingerir(cad.ana, NUM)
    assert item.status == "concluido" and p is not None and len(dify_https.dify.chats) == 1


def test_ca_do_dify_nao_vale_para_o_datajud(cad, dify_https, ingerir, settings):
    """CAD-07a: a CA colada vale SÓ para o host do dify_url — o DataJud em outro host HTTPS com o mesmo certificado continua recusado."""
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{cad.srv.porta}", f"127.0.0.1:{dify_https.porta}"]
    cad.config.dify_ca_pem = dify_https.pem
    cad.config.datajud_url = f"https://127.0.0.1:{dify_https.porta}/datajud"
    cad.config.save()
    _, p = ingerir(cad.ana, NUM)
    assert p is not None and p.cnj_validacao == "falhou" and dify_https.srv.requisicoes == []


def test_nao_ha_caminho_que_desliga_a_verificacao(cad, dify_https, ingerir, settings):
    """CAD-07a: nenhuma configuração torna o certificado desconhecido aceito sem a CA (PEM de OUTRA CA também falha)."""
    outro_pem = _gerar_certificado("127.0.0.1")[0]
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{cad.srv.porta}", f"127.0.0.1:{dify_https.porta}"]
    cad.config.dify_url = f"https://127.0.0.1:{dify_https.porta}/dify"
    cad.config.dify_ca_pem = outro_pem
    cad.config.save()
    item, _ = ingerir(cad.ana, NUM)
    assert item.status == "erro" and dify_https.srv.requisicoes == []


# ---------------- segurança (CAD-18) ----------------

def test_chaves_nunca_aparecem_em_telas_respostas_logs_e_banco(cad, ingerir, ver, caplog):
    """CAD-18: valor das credenciais fora de qualquer tela do Jurídico, do JSON de status, dos logs e dos campos do item/processo."""
    caplog.set_level("DEBUG")
    cad.dify.eco_chave = True
    cad.datajud.status = 401
    item, p = ingerir(cad.ana, NUM)
    rotas = [("juridico:painel", None), ("juridico:erros", None), ("juridico:envios", None), ("juridico:enviar_pdfs", None), ("juridico:enviar_cnj", None),
             ("juridico:config", None), ("juridico:audiencias", None), ("juridico:envio", item.envio_id), ("juridico:processo", p.pk if p else 1)]
    for nome, pk in rotas:
        r = cad.adm.get(reverse(nome, kwargs={"pk": pk}) if pk else reverse(nome))
        for s in (SEGREDO_DIFY, SEGREDO_DATAJUD):
            assert s not in r.content.decode(), (nome, s)
    assert SEGREDO_DIFY not in json.dumps(cad.adm.get(reverse("juridico:status") + f"?envio={item.envio_id}").json())
    blob = json.dumps([item.motivo, item.resposta_ia, getattr(p, "observacoes", ""), getattr(p, "pendencias", [])], default=str)
    assert SEGREDO_DIFY not in blob and SEGREDO_DATAJUD not in blob
    assert SEGREDO_DIFY not in caplog.text and SEGREDO_DATAJUD not in caplog.text


def test_resposta_ia_so_o_adm_ve(cad, ingerir, ver):
    """CAD-12 (modelo)/18: a resposta bruta do Dify só aparece para o Adm — quem enviou NÃO a vê na tela."""
    cad.dify.extra = {"marcador_bruto": "MARCADOR-SO-NA-RESPOSTA-IA"}
    item, _ = ingerir(cad.ana, NUM)
    assert "MARCADOR-SO-NA-RESPOSTA-IA" in item.resposta_ia
    url = reverse("juridico:envio", kwargs={"pk": item.envio_id})
    assert "MARCADOR-SO-NA-RESPOSTA-IA" not in cad.ana.get(url).content.decode()


def test_motivo_de_erro_e_escapado_em_tela(cad, ingerir, ver):
    """CAD-18: texto do PDF/IA é DADO — mesmo no motivo do erro, nada é avaliado/HTML cru."""
    xss = "<script>alert(1)</script>"
    cad.dify.respostas[NUM] = '{"numero_cnj": "' + xss + '"}'
    item, _ = ingerir(cad.ana, NUM)
    for rota in (reverse("juridico:erros"), reverse("juridico:envio", kwargs={"pk": item.envio_id})):
        assert "<script>alert(1)</script>" not in cad.adm.get(rota).content.decode()


def test_nome_do_arquivo_e_escapado(cad, enviar, ver):
    """CAD-18: nome original do PDF com HTML é escapado nas telas do envio e do log."""
    enviar(cad.ana, (pdf_processo(NUM)[0], "<img src=x onerror=alert(1)>.pdf"))
    item = cad.ItemEnvio.objects.get()
    assert "<img src=x" not in cad.ana.get(reverse("juridico:envio", kwargs={"pk": item.envio_id})).content.decode()


def test_processo_de_outro_setor_com_acesso_e_visivel_mas_detalhe_de_envio_nao(cad, ingerir):
    """permissoes.yaml: o cadastro é do escritório (processo visível), mas o detalhe do Envio/Item é de quem enviou."""
    item, p = ingerir(cad.ana, NUM)
    assert cad.bruno.get(reverse("juridico:processo", kwargs={"pk": p.pk})).status_code == 200
    assert cad.bruno.get(reverse("juridico:envio", kwargs={"pk": item.envio_id})).status_code in (403, 404)
    criar_processo(cad)  # sanidade do helper
