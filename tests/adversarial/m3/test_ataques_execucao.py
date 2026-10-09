"""Adversarial M3: IDOR, SSRF de ponta a ponta, placeholders hostis, vazamento, limites, CSRF. Só servidor local e DNS simulado."""

import json
import re
import threading
import time
from urllib.parse import quote

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m3")]

CATEGORIAS = {"bloqueado_ssrf", "timeout", "dns", "conexao", "tls", "resposta_grande", "redirect_excessivo", "http_4xx", "http_5xx", "placeholder", "json_invalido"}


def _h(r):
    return r.content.decode()


# ---------- IDOR ----------


@pytest.fixture
def fabrica_execucao(modelos, usuario_adm):
    from datetime import timedelta

    from django.utils import timezone

    def _criar(executado_por, nome="Fluxo X", status="sucesso"):
        inicio = timezone.now() - timedelta(minutes=1)
        return modelos.Execucao.objects.create(
            fluxo=None, fluxo_nome=nome, grafo_snapshot={"versao": 1, "nos": [], "arestas": []},
            executado_por=executado_por, status=status, iniciada_em=inicio, finalizada_em=inicio + timedelta(seconds=1), erro_resumo="",
        )

    return _criar


def test_base_nao_ve_execucoes_alheias_por_nenhum_caminho(cliente_base, usuario_base, usuario_coordenador, fabrica_execucao):
    """PRM-03/04: lista, filtros, ordenação hostil e paginação nunca mostram execução de outra pessoa a Base."""
    fabrica_execucao(usuario_base, "Propria Unica")
    for i in range(30):
        fabrica_execucao(usuario_coordenador, f"Alheia {i:02d}")
    url = reverse("execucoes:lista")
    for params in ({}, {"q": "Alheia"}, {"q": "alheia 0"}, {"pagina": 2}, {"pagina": 999}, {"status": "sucesso"}, {"status": ["sucesso", "erro"]},
                   {"ordem": "executado_por"}, {"ordem": "-executado_por__email"}, {"ordem": "fluxo_nome"}, {"ordem": "-iniciada_em"}):
        h = _h(cliente_base.get(url, params))
        assert not re.search(r"Alheia \d\d", h), params
    assert "Propria Unica" in _h(cliente_base.get(url))


@pytest.mark.parametrize("pk", ["999999", "abc", "-1", "0", "1.5", "99999999999999999999", "%00", "1%20OR%201=1"])
def test_detalhe_com_pk_hostil_e_404(cliente_base, pk):
    """PRM-03: pk inexistente/malformado → 404 (nunca 500)."""
    url = reverse("execucoes:detalhe", kwargs={"pk": 1}).replace("/1/", f"/{pk}/")
    assert cliente_base.get(url).status_code == 404


def test_base_nao_abre_detalhe_de_outros_nem_enumera_por_diferenca(cliente_base, usuario_coordenador, fabrica_execucao):
    """PRM-03: execução alheia e pk inexistente respondem IGUAL (404, mesmo tamanho de corpo ±) — sem oráculo de existência."""
    alheia = fabrica_execucao(usuario_coordenador, "Segredo Alheio")
    r1 = cliente_base.get(reverse("execucoes:detalhe", kwargs={"pk": alheia.pk}))
    r2 = cliente_base.get(reverse("execucoes:detalhe", kwargs={"pk": alheia.pk + 1000}))
    assert r1.status_code == r2.status_code == 404
    assert "Segredo Alheio" not in _h(r1)
    assert abs(len(r1.content) - len(r2.content)) < 200


def test_base_executa_ativo_de_outro_dono_mas_nunca_rascunho(cliente_base, usuario_coordenador, liberado, fabrica_fluxo, cadeia, cfg_http, modelos):
    """PRM-03: Base executa fluxo ativo (de qualquer dono); rascunho → 404 igual ao pk inexistente; nada criado."""
    g = cadeia(cfg_http(f"{liberado.base}/ok"))
    ativo = fabrica_fluxo(grafo=g, status="ativo", dono=usuario_coordenador)
    rasc = fabrica_fluxo(grafo=g, status="rascunho", dono=usuario_coordenador)
    assert cliente_base.post(reverse("fluxos:executar", kwargs={"pk": ativo.pk})).status_code == 302
    n = modelos.Execucao.objects.count()
    for pk in (rasc.pk, 999999, "abc"):
        url = reverse("fluxos:executar", kwargs={"pk": 1}).replace("/1/", f"/{pk}/")
        assert cliente_base.post(url).status_code == 404
    assert modelos.Execucao.objects.count() == n


def test_execucao_de_base_nao_vaza_para_outro_base(cliente_base, usuario_base, liberado, fabrica_fluxo, cadeia, cfg_http, fabrica_usuario):
    """PRM-04/SET-06: dois Base do MESMO setor (Geral) não veem as execuções um do outro."""
    from django.apps import apps

    geral = apps.get_model("contas", "Setor").objects.get(nome="Geral")
    usuario_base.setor = geral
    usuario_base.save()
    outro = fabrica_usuario(papel="Base")
    outro.setor = geral
    outro.save()
    c2 = Client()
    c2.force_login(outro)
    f = fabrica_fluxo(grafo=cadeia(cfg_http(f"{liberado.base}/ok")), status="ativo", nome="Fluxo Compartilhado")
    f.setor = geral
    f.save()
    r = c2.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    pk = int(r.url.rstrip("/").rsplit("/", 1)[1]) if r.url.rstrip("/").rsplit("/", 1)[1].isdigit() else None
    assert pk is not None
    assert cliente_base.get(r.url).status_code == 404
    assert "Fluxo Compartilhado" not in _h(cliente_base.get(reverse("execucoes:lista")))


# ---------- CSRF e duplo envio ----------


def test_executar_sem_csrf_ou_token_forjado(usuario_coordenador, liberado, fabrica_fluxo, cadeia, cfg_http, modelos):
    """SEG-12: POST de executar sem token / com token forjado → 403 e nada executa."""
    f = fabrica_fluxo(grafo=cadeia(cfg_http(f"{liberado.base}/ok")), status="ativo")
    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_coordenador)
    url = reverse("fluxos:executar", kwargs={"pk": f.pk})
    assert c.post(url).status_code == 403
    assert c.post(url, {"csrfmiddlewaretoken": "x" * 64}, HTTP_X_CSRFTOKEN="y" * 64).status_code == 403
    assert modelos.Execucao.objects.count() == 0 and liberado.hits == []


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_duplo_envio_concorrente_nao_da_500(usuario_coordenador, liberado, fabrica_fluxo, cadeia, cfg_http, modelos):
    """EXE-13: dois POSTs simultâneos no mesmo fluxo terminam sem 500 e cada um deixa uma execução consistente."""
    f = fabrica_fluxo(grafo=cadeia(cfg_http(f"{liberado.base}/lento?s=1")), status="ativo")
    url = reverse("fluxos:executar", kwargs={"pk": f.pk})
    codigos = []

    def disparar():
        c = Client()
        c.force_login(usuario_coordenador)
        codigos.append(c.post(url).status_code)

    ts = [threading.Thread(target=disparar) for _ in range(2)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert len(codigos) == 2 and all(c < 500 for c in codigos), codigos
    assert all(e.status in ("sucesso", "erro") for e in modelos.Execucao.objects.all())


# ---------- SSRF de ponta a ponta ----------


def _executar_h2(cliente, executar, liberado, cadeia, cfg_http, url_h2, caminho_h1="/alvo?v="):
    g = cadeia(cfg_http(f"{liberado.base}{caminho_h1}"), cfg_http(url_h2))
    return executar(cliente, g)[1]


@pytest.mark.parametrize("valor", [
    "169.254.169.254", "127.0.0.1", "localhost", "0x7f.1", "2130706433", "[::1]", "[::ffff:127.0.0.1]", "10.0.0.1",
    "127.0.0.1%23@exemplo.test", "exemplo.test%2F@127.0.0.1", "127.0.0.1:1", "127.0.0.1%3A80",
])
def test_host_montado_por_placeholder_nunca_chega_ao_servidor_interno(valor, cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-02/SEG-03/PLH-04: o host vem da SAÍDA do nó anterior; a URL final é validada de ponta a ponta."""
    g = cadeia(cfg_http(f"{liberado.base}/alvo?v={quote(valor, safe='')}"), cfg_http("http://{{ anterior.corpo.v }}/x"))
    _, e, _ = executar(cliente_coordenador, g)
    assert e is not None
    h2 = no(e, "h2")
    assert h2.status == "erro"
    assert liberado.contagem("/x") == 0
    if h2.erro_categoria:
        assert h2.erro_categoria in CATEGORIAS


@pytest.mark.parametrize("valor", ["file", "gopher", "ftp", "javascript", "data", "HTTP", "http://127.0.0.1:1/"])
def test_esquema_montado_por_placeholder(valor, cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-01: esquema vindo de placeholder: pendência (sem execução) ou erro; nunca requisição ao destino."""
    g = cadeia(cfg_http(f"{liberado.base}/alvo?v={quote(valor, safe='')}"), cfg_http("{{ anterior.corpo.v }}://127.0.0.1:1/x"))
    _, e, _ = executar(cliente_coordenador, g)
    assert e is None or no(e, "h2").status == "erro"
    assert liberado.contagem("/x") == 0


@pytest.mark.parametrize("valor", ["1", "0", "22", "65535", "65536", "99999999999", "-1", "80@127.0.0.1", "80/../x"])
def test_porta_montada_por_placeholder(valor, cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-02: porta alta/inválida/maliciosa vinda de placeholder nunca causa 500 e só chega ao servidor se permitido."""
    g = cadeia(cfg_http(f"{liberado.base}/alvo?v={quote(valor, safe='')}"), cfg_http("http://127.0.0.1:{{ anterior.corpo.v }}/x"))
    _, e, _ = executar(cliente_coordenador, g)
    assert e is None or no(e, "h2").status == "erro"
    assert liberado.contagem("/x") == 0


@pytest.mark.parametrize("destino", [
    "http://169.254.169.254/latest/meta-data/", "http://[::ffff:127.0.0.1]:{p}/secret", "http://0x7f.1:{p}/secret",
    "http://0177.0.0.1:{p}/secret", "http://2130706433:{p}/secret", "//169.254.169.254/x", "/\\169.254.169.254/x",
    "http://[fd00:ec2::254]/latest", "http://100.64.0.1/", "http://localhost.:{p}/secret", "http://LOCALHOST:{p}/secret",
    "http://127.1:{p}/secret", "http://[::]:{p}/secret", "http://0:{p}/secret",
])
def test_redirect_para_alvos_internos_em_todas_as_formas(destino, cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-05: redirect do servidor liberado para alvos internos (IPv4 alternativo, IPv6, protocolo-relativo, barra invertida)."""
    alvo = quote(destino.format(p=liberado.porta), safe="")
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/redir-para?para={alvo}")))
    h1 = no(e, "h1")
    assert h1.status == "erro" and h1.erro_categoria in ("bloqueado_ssrf", "conexao"), (destino, h1.erro_categoria)
    assert h1.erro_categoria == "bloqueado_ssrf" or "169.254" not in destino
    assert liberado.contagem("/secret") == 0


def test_redirect_em_cadeia_permitido_depois_proibido(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-05: dois saltos permitidos e o terceiro proibido → bloqueado; o destino não é contactado."""
    final = quote(f"http://localhost:{liberado.porta}/secret", safe="")
    meio = quote(f"/redir-para?para={final}", safe="")
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/redir-para?para={meio}")))
    assert no(e, "h1").erro_categoria == "bloqueado_ssrf" and liberado.contagem("/secret") == 0


def test_redirect_infinito_para_si_mesmo(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-05: laço de redirect → redirect_excessivo (não trava)."""
    t0 = time.time()
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/redir-self")))
    assert no(e, "h1").erro_categoria == "redirect_excessivo" and time.time() - t0 < 10


def test_dns_que_muda_entre_chamadas_nao_burla_a_validacao(cliente_coordenador, servidor, dns, executar, cadeia, cfg_http, no):
    """SEG-04: nome cujo DNS troca (1ª proibida, 2ª outra) continua bloqueado — nenhuma conexão."""
    chamadas = dns({"troca.exemplo.test": [["127.0.0.1"], ["10.0.0.9"], ["127.0.0.1"]]}, sequencial=True)
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"http://troca.exemplo.test:{servidor.porta}/ok")))
    assert no(e, "h1").erro_categoria == "bloqueado_ssrf" and servidor.hits == [] and chamadas["troca.exemplo.test"] >= 1


def test_liberado_com_dns_que_muda_conecta_so_no_ip_validado(cliente_coordenador, servidor, settings, dns, executar, cadeia, cfg_http, no):
    """SEG-04/SEG-16.2: liberado por nome, mas a 2ª resolução aponta para IP interno diferente → conexão fica no IP validado."""
    settings.MOTOR_SSRF_LIBERAR = [f"troca.exemplo.test:{servidor.porta}"]
    dns({"troca.exemplo.test": [["127.0.0.1"], ["169.254.169.254"]]}, sequencial=True)
    t0 = time.time()
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"http://troca.exemplo.test:{servidor.porta}/ok")))
    assert e.status == "sucesso" and time.time() - t0 < 8


@pytest.mark.parametrize("url_tpl", [
    "http://127.0.0.1 .exemplo.test:{p}/ok", "http://127.0.0.1\t:{p}/ok", "http://127.0.0.1%09:{p}/ok", "http://127.0.0.1%0d%0a:{p}/ok",
    "http://１２７.０.０.１:{p}/ok", "http://127。0。0。1:{p}/ok", "http://ｌｏｃａｌｈｏｓｔ:{p}/ok", "http://ⓛⓞⓒⓐⓛⓗⓞⓢⓣ:{p}/ok",
    "http://xn--localhost-.:{p}/ok", "http://ехample.test:{p}/ok", "http://127.0.0.1​:{p}/ok", "http://‮127.0.0.1:{p}/ok",
    "http://[fe80::1%25en0]:{p}/ok", "http://[fe80::1%en0]:{p}/ok", "http://[::1%25lo0]:{p}/ok", "http://[::1%lo0]:{p}/ok",
    "http://127.0.0.1\\@exemplo.test:{p}/ok", "http://127.0.0.1:{p}\\@exemplo.test/ok", " http://127.0.0.1:{p}/ok", "http://127.0.0.1:{p}/ok ",
])
def test_urls_malformadas_e_unicode_nunca_chegam_ao_servidor_local(url_tpl, cliente_coordenador, servidor, executar, cadeia, cfg_http, no):
    """SEG-02/SEG-03/SEG-06: espaço, tab, CR/LF, IDN, dígitos/pontos Unicode, homóglifos e zona IPv6: pendência ou erro; nunca conexão ao servidor local."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(url_tpl.format(p=servidor.porta))))
    assert e is None or no(e, "h1").status == "erro"
    assert servidor.hits == []


# ---------- placeholders hostis em execução ----------


@pytest.mark.parametrize("caminho", [
    "anterior" + ".corpo" * 300, "anterior.corpo.lista.99999999999999999999", "anterior.corpo.lista.-1", "anterior.corpo.a.b",
    "anterior.corpo.__proto__", "anterior.corpo.__class__", "anterior.corpo.a" + ".a" * 5000, "anterior.corpo." + "x" * 100000,
    "anterior.corpo.‮", "anterior.corpo.é", "anterior.corpo.a b",
])
def test_placeholders_hostis_nunca_derrubam_a_execucao(caminho, cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-03: profundidade, índice gigante, chaves especiais/ponto/unicode e caminhos de 100 KB → erro de placeholder ou valor; nunca 500."""
    g = cadeia(cfg_http(f"{liberado.base}/chave-ponto"), cfg_http(f"{liberado.base}/eco", query=[{"nome": "x", "valor": "{{ " + caminho + " }}"}]))
    r, e, _ = executar(cliente_coordenador, g)
    assert r.status_code == 302 or e is None
    if e is not None:
        h2 = no(e, "h2")
        assert h2.status in ("sucesso", "erro", "nao_executado")
        if h2.status == "erro":
            assert h2.erro_categoria in CATEGORIAS


def test_valor_de_900kb_em_placeholder_no_corpo_e_na_url(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """PLH-04/SEG-07: valor de ~900 KB interpolado no corpo funciona ou falha com categoria; na URL é recusado; nunca 500."""
    g = cadeia(cfg_http(f"{liberado.base}/enorme"), cfg_http(f"{liberado.base}/eco", "POST", corpo='{"a": "{{ anterior.corpo.v }}"}'))
    r, e, _ = executar(cliente_coordenador, g)
    assert r.status_code == 302 and no(e, "h2").status in ("sucesso", "erro")
    g = cadeia(cfg_http(f"{liberado.base}/enorme"), cfg_http(f"{liberado.base}/eco/" + "{{ anterior.corpo.v }}"))
    r, e, _ = executar(cliente_coordenador, g)
    assert r.status_code == 302 and no(e, "h2").status == "erro"


def test_resposta_com_byte_nul_nao_da_500(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-07/EXE-06: corpo de resposta com byte NUL (binário) é gravado/escapado ou vira erro categorizado; nunca 500."""
    r, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/nul")))
    assert r.status_code == 302 and e.status in ("sucesso", "erro")
    assert cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).status_code == 200


def test_resposta_json_profundissima_nao_derruba_o_motor(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-07: corpo JSON com 100 mil níveis de aninhamento é gravado como texto/valor ou vira erro categorizado; nunca 500."""
    r, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/profundo")))
    assert r.status_code == 302 and e.status in ("sucesso", "erro")
    assert cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).status_code == 200


# ---------- vazamento de segredo ----------

SEGREDO = "SEGREDO-ADV-9f3a"


@pytest.mark.parametrize("caminho", ["/status/500", "/status/404", "/redir/9", "/lento?s=3", "/grande-404"])
def test_segredo_nao_aparece_em_erros_telas_nem_snapshot(caminho, cliente_coordenador, cliente_adm, liberado, settings, executar, cadeia, cfg_http, no, nos_de):
    """SEG-09/SEG-10: com falhas variadas, o segredo de header/query não aparece em erro_mensagem, erro_resumo, entrada/saída, snapshot nem telas."""
    settings.MOTOR_TIMEOUT_LEITURA = 1
    g = cadeia(cfg_http(f"{liberado.base}{caminho}", headers=[{"nome": "Authorization", "valor": f"Bearer {SEGREDO}"}, {"nome": "X-Api-Key", "valor": SEGREDO}], query=[{"nome": "token", "valor": SEGREDO}, {"nome": "password", "valor": SEGREDO}]))
    _, e, _ = executar(cliente_coordenador, g)
    blobs = [e.erro_resumo, json.dumps(e.grafo_snapshot)]
    for n in nos_de(e):
        blobs += [n.erro_mensagem or "", json.dumps(n.entrada), json.dumps(n.saida)]
    assert SEGREDO not in "\n".join(blobs)
    for c in (cliente_coordenador, cliente_adm):
        for url in (reverse("execucoes:detalhe", kwargs={"pk": e.pk}), reverse("execucoes:lista")):
            assert SEGREDO not in _h(c.get(url))


@pytest.mark.parametrize("modo", ["conexao_recusada", "ssrf", "dns", "tls"])
def test_segredo_na_query_nao_vaza_na_mensagem_de_erro_de_rede(modo, cliente_coordenador, servidor, settings, dns, executar, cadeia, cfg_http, no):
    """SEG-10: erros de rede/SSRF/DNS/TLS não repetem a URL com o token na mensagem."""
    import socket

    q = [{"nome": "token", "valor": SEGREDO}]
    if modo == "conexao_recusada":
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
        s.close()
        settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{porta}"]
        url = f"http://127.0.0.1:{porta}/x"
    elif modo == "ssrf":
        url = f"http://127.0.0.1:{servidor.porta}/x"
    elif modo == "dns":
        dns({"nada.exemplo.test": None})
        url = "http://nada.exemplo.test/x"
    else:
        settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{servidor.porta}"]
        url = f"https://127.0.0.1:{servidor.porta}/x"
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(url, query=q)))
    h1 = no(e, "h1")
    assert h1.status == "erro" and SEGREDO not in (h1.erro_mensagem + e.erro_resumo + json.dumps(h1.entrada))
    assert SEGREDO not in _h(cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})))


def test_header_sensivel_da_resposta_nao_vaza_em_nenhuma_tela(cliente_coordenador, cliente_adm, liberado, executar, cadeia, cfg_http):
    """SEG-09: Set-Cookie/X-Api-Key/X-Token-Interno da resposta ficam mascarados em detalhe e lista."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/cabecalhos")))
    for c in (cliente_coordenador, cliente_adm):
        for url in (reverse("execucoes:detalhe", kwargs={"pk": e.pk}), reverse("execucoes:lista")):
            h = _h(c.get(url))
            assert "SEGREDO-COOKIE-RESP" not in h and "SEGREDO-APIKEY-RESP" not in h and "SEGREDO-TOKEN-RESP" not in h


def test_nome_de_header_sensivel_com_caixa_e_variacoes(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-09: variações de caixa/hífen/sublinhado em nomes sensíveis também são mascaradas."""
    nomes = ["aUtHoRiZaTiOn", "x_api_key", "X-API-KEY", "x-Token", "SECRET", "x-client-secret", "PASSWORD", "x-senha-admin", "Api-Key"]
    hs = [{"nome": n, "valor": SEGREDO} for n in nomes]
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/eco", headers=hs)))
    assert SEGREDO not in json.dumps(no(e, "h1").entrada)


@pytest.mark.parametrize("caminho", ["/ok", "/status/500", "/redir/2"])
@pytest.mark.parametrize("nivel", ["INFO", "DEBUG"])
def test_segredo_de_query_nao_vai_para_os_logs(caminho, nivel, cliente_coordenador, liberado, caplog, executar, cadeia, cfg_http):
    """SEG-11/SEG-09: nenhum segredo em log — o cliente HTTP não pode registrar a URL com ?token=… (httpx loga a URL em INFO)."""
    g = cadeia(cfg_http(f"{liberado.base}{caminho}", query=[{"nome": "token", "valor": SEGREDO}, {"nome": "api-key", "valor": SEGREDO}], headers=[{"nome": "Authorization", "valor": f"Bearer {SEGREDO}"}]))
    with caplog.at_level(nivel):
        executar(cliente_coordenador, g)
    assert SEGREDO not in caplog.text


# ---------- limites ----------


def test_resposta_infinita_e_cortada_no_limite(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-07: resposta chunked sem fim é cortada em 1 MiB (truncado=true) e a execução termina rápido."""
    t0 = time.time()
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/infinito")))
    s = no(e, "h1").saida
    assert e.status == "sucesso" and s["truncado"] is True and len(s["corpo"]) <= 1024 * 1024
    assert time.time() - t0 < 15


def test_slowloris_estoura_o_limite_por_no(cliente_coordenador, liberado, settings, executar, cadeia, cfg_http, no):
    """SEG-07: servidor que goteja 1 byte a cada 0,3 s (sem estourar a leitura) é cortado pelo limite TOTAL do nó."""
    settings.MOTOR_TIMEOUT_LEITURA = 1
    settings.MOTOR_TIMEOUT_NO = 2
    t0 = time.time()
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/gotejar")))
    assert no(e, "h1").erro_categoria == "timeout" and time.time() - t0 < 8


def test_gzip_bomba_300mb_e_truncada_sem_estourar_memoria(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-07: gzip de ~300 MB descompactados é cortado em 1 MiB (truncado) e leva poucos segundos."""
    t0 = time.time()
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/gzip-bomba")))
    s = no(e, "h1").saida
    assert s["truncado"] is True and len(s["corpo"]) <= 1024 * 1024 and time.time() - t0 < 15


@pytest.mark.parametrize("caminho", ["/muitos-headers", "/header-enorme"])
def test_muitos_headers_e_header_gigante_na_resposta(caminho, cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """SEG-07: 300 headers ou um header de 70 KB na resposta → sucesso ou erro categorizado; nunca 500 e a tela abre."""
    r, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}{caminho}")))
    assert r.status_code == 302 and e.status in ("sucesso", "erro")
    if e.status == "erro":
        assert no(e, "h1").erro_categoria in CATEGORIAS
    assert cliente_coordenador.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).status_code == 200


def test_cadeia_de_48_nos_lentos_respeita_o_limite_total(cliente_coordenador, liberado, settings, executar, cadeia, cfg_http, no, nos_de):
    """EXE-13: 48 nós de 0,5 s com limite total de 3 s → para no estouro (timeout), restante nao_executado, tempo total limitado."""
    settings.MOTOR_TIMEOUT_EXECUCAO = 3
    g = cadeia(*[cfg_http(f"{liberado.base}/lento?s=0.5") for _ in range(48)])
    t0 = time.time()
    _, e, _ = executar(cliente_coordenador, g)
    assert time.time() - t0 < 12
    assert e.status == "erro"
    estados = [n.status for n in nos_de(e)]
    assert "nao_executado" in estados and any(n.erro_categoria == "timeout" for n in nos_de(e))
    assert liberado.contagem("/lento") < 20


def test_muitos_headers_e_query_na_requisicao(cliente_coordenador, liberado, executar, cadeia, cfg_http, no):
    """GRF-04: 30 headers e 30 query de 4096 bytes: executam ou falham com categoria; nunca 500."""
    hs = [{"nome": f"X-H{i}", "valor": "v" * 4096} for i in range(30)]
    qs = [{"nome": f"q{i}", "valor": "v" * 4096} for i in range(30)]
    r, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/eco", headers=hs, query=qs)))
    assert r.status_code == 302 and e.status in ("sucesso", "erro")


# ---------- XSS no detalhe (chromium e webkit) ----------


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_xss_no_detalhe_com_resposta_hostil_nao_executa(pagina_coordenador, liberado, cliente_coordenador, executar, cadeia, cfg_http):
    """SEG-13: corpo, chaves, listas e headers hostis da resposta HTTP aparecem como texto no detalhe; nada executa."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/xss-completo")))
    pagina = pagina_coordenador
    pagina.goto(pagina.live_url + reverse("execucoes:detalhe", kwargs={"pk": e.pk}))
    pagina.wait_for_timeout(600)
    pagina.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    for botao in pagina.get_by_role("button", name="Copiar").all():
        botao.click()
    pagina.wait_for_timeout(300)
    assert pagina.dialogos == []
    assert pagina.evaluate("window.__pwn") is None
    assert pagina.locator("[onerror], [onload]").count() == 0
    assert not [e for e in pagina.erros_js if "Clipboard" not in e], pagina.erros_js


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_xss_de_resposta_html_no_detalhe_e_na_lista(pagina_coordenador, liberado, cliente_coordenador, executar, cadeia, cfg_http):
    """SEG-13: resposta text/html com <script> vira texto no detalhe; a lista também não executa nada."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/xss")))
    pagina = pagina_coordenador
    for caminho in (reverse("execucoes:detalhe", kwargs={"pk": e.pk}), reverse("execucoes:lista")):
        pagina.goto(pagina.live_url + caminho)
        pagina.wait_for_timeout(500)
        pagina.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
        assert pagina.dialogos == [] and pagina.evaluate("window.__pwn") is None
        assert pagina.locator("img[onerror]").count() == 0


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_botao_executar_bloqueia_duplo_envio(pagina_coordenador, liberado, cliente_coordenador, fabrica_fluxo, cadeia, cfg_http, modelos):
    """EXE-13: após clicar em Executar na lista, o botão fica desabilitado/carregando e um segundo clique não cria 2ª execução."""
    f = fabrica_fluxo(grafo=cadeia(cfg_http(f"{liberado.base}/lento?s=2")), status="ativo", nome="Fluxo Lento Duplo")
    pagina = pagina_coordenador
    pagina.goto(pagina.live_url + reverse("fluxos:lista"))
    pagina.wait_for_load_state()
    botao = pagina.locator(f'form[action="{reverse("fluxos:executar", kwargs={"pk": f.pk})}"] button, form[action="{reverse("fluxos:executar", kwargs={"pk": f.pk})}"] [type=submit]').first
    botao.click()
    pagina.wait_for_timeout(250)
    try:
        bloqueado = botao.is_disabled() or botao.get_attribute("aria-busy") == "true" or botao.get_attribute("data-carregando") is not None
    except Exception:  # navegação já em curso
        bloqueado = True
    try:
        botao.click(timeout=300, force=True)
    except Exception:
        pass
    pagina.wait_for_url("**/execucoes/**", timeout=20000)
    assert bloqueado
    assert modelos.Execucao.objects.filter(fluxo=f).count() == 1
