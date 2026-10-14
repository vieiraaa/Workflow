"""Adversarial T-073 · nó Chamar n8n (N8N-02/03/04/05, SEG-01..10, CRD-02). Tudo contra servidor local; nunca internet."""
import json
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("n8n")]

SEGREDO = "SEGREDO-ADV-N8N-FICTICIO-4242"


def _terminou(e, n=None):
    assert e is not None and e.status in ("sucesso", "erro"), getattr(e, "status", None)
    if n is not None:
        assert n.status in ("sucesso", "erro"), "o motor falhou sem gravar o nó (falha inesperada)"


def _tudo(e):
    from django.apps import apps
    partes = [e.erro_resumo or "", json.dumps(e.grafo_snapshot, default=str)]
    for x in apps.get_model("execucoes", "ExecucaoNo").objects.filter(execucao=e):
        partes += [x.erro_mensagem or "", json.dumps([x.entrada, x.saida, x.requisicoes, getattr(x, "logs", None)], default=str)]
    return "\n".join(partes)


# ---------------- URL por expressão resolvendo para destino proibido ----------------

ALVOS = ["http://169.254.169.254/latest/meta-data/", "http://127.0.0.1:1/x", "http://localhost/x", "http://localhost./x",
         "http://[::1]/x", "http://[::ffff:127.0.0.1]/x", "http://0x7f.1/x", "http://0177.0.0.1/x", "http://2130706433/x",
         "http://127.1/x", "http://0.0.0.0/x", "http://10.0.0.1/x", "http://192.168.0.1/x", "http://172.16.0.1/x",
         "http://[fd00::1]/x", "http://user:pw@127.0.0.1/x", "http://exemplo.test@127.0.0.1/x", "http://127.0.0.1%2523@exemplo.test/",
         "http://metadata.google.internal/x"]


@pytest.mark.parametrize("alvo", ALVOS)
def test_url_de_expressao_para_destino_interno_e_bloqueada(n8n_no, liberado, nao_liberado, sem_internet, cfg, alvo):
    """N8N-05/SEG-01..06: qualquer forma de endereço interno vinda de expressão = erro do nó, nada chega a servidor algum."""
    e, n = n8n_no(cfg("{{ $json.alvo }}"), [{"alvo": alvo}])
    assert e.status == "erro" and n.erro_categoria in ("bloqueado_ssrf", "placeholder", "dns", "conexao")
    assert liberado.requisicoes == [] and nao_liberado.requisicoes == []


@pytest.mark.parametrize("alvo", ["file:///etc/passwd", "gopher://127.0.0.1/x", "ftp://exemplo.test/x", "javascript:alert(1)",
                                  "data:text/plain,x", "//127.0.0.1/x", "\\\\127.0.0.1\\x"])
def test_url_de_expressao_com_esquema_nao_http_falha(n8n_no, liberado, cfg, alvo):
    """N8N-02/SEG-01: esquema não-http resolvido em runtime → erro do nó, nada enviado."""
    e, n = n8n_no(cfg("{{ $json.alvo }}"), [{"alvo": alvo}])
    assert e.status == "erro" and liberado.requisicoes == []


@pytest.mark.parametrize("v", ["x@169.254.169.254", "../../etc", "x#@127.0.0.1:9", "x?y=1&z=2", "a\\@127.0.0.1", "x%2f..%2f",
                              "..%252f", "a b", "ç/ã"])
def test_valor_hostil_inserido_no_caminho_nao_muda_o_host(n8n_no, liberado, cfg, v):
    """PLH-04/SEG-06: valor com / ? # @ \\ inserido no caminho da URL é codificado; o host e o caminho-base continuam os mesmos."""
    liberado.rotas["/webhook/ok"] = lambda req: (200, {"ok": 1}, None)
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/ok/{{{{ $json.v }}}}"), [{"v": v}])
    _terminou(e)
    for r in liberado.requisicoes:
        assert r["path"].startswith("/webhook/ok/") and "?" not in r["path"] and "#" not in r["path"]
        assert r["headers"]["host"] == f"127.0.0.1:{liberado.porta}"
        assert r["path"].count("/") == 3, r["path"]


def test_valor_na_parte_do_host_nao_vira_outro_host(n8n_no, liberado, nao_liberado, cfg):
    """SEG-06: expressão no lugar da porta/host não consegue desviar para outro servidor local não liberado."""
    e, n = n8n_no(cfg("http://127.0.0.1:{{ $json.p }}/webhook/x"), [{"p": f"{nao_liberado.porta}"}])
    assert e.status == "erro" and n.erro_categoria == "bloqueado_ssrf" and nao_liberado.requisicoes == []


# ---------------- redirects ----------------

@pytest.mark.parametrize("codigo", [301, 302, 303, 307, 308])
@pytest.mark.parametrize("destino", ["http://169.254.169.254/latest/meta-data/", "http://localhost/x", "http://[::1]/x",
                                     "NAOLIB", "file:///etc/passwd", "gopher://127.0.0.1/x"])
def test_redirect_para_destino_proibido_e_barrado(n8n_no, liberado, nao_liberado, cfg, codigo, destino):
    """N8N-05/SEG-05: 30x do 'n8n' para interno/metadados/esquema estranho → erro, e o destino NUNCA recebe requisição."""
    alvo = f"{nao_liberado.base}/segredo" if destino == "NAOLIB" else destino
    liberado.rotas["/webhook/r"] = lambda req: (codigo, b"", {"Location": alvo})
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/r"), [{"a": 1}])
    assert e.status == "erro" and nao_liberado.requisicoes == []
    assert len(liberado.hits("/webhook/r")) == 1
    assert n.erro_categoria in ("bloqueado_ssrf", "redirect_excessivo", "conexao", "placeholder")


def test_redirect_nao_reenvia_corpo_nem_credencial_a_outro_destino(n8n_no, liberado, nao_liberado, cfg, criar_cred):
    """SEG-05/CRD-02: nem o corpo nem o Authorization seguem para o destino do redirect."""
    criar_cred(nome="Cofre n8n", tipo="bearer", valor=SEGREDO)
    liberado.rotas["/webhook/r2"] = lambda req: (307, b"", {"Location": f"{nao_liberado.base}/coleta"})
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/r2", credencial="Cofre n8n"), [{"confidencial": "corpo-secreto"}])
    assert e.status == "erro" and nao_liberado.requisicoes == []


def test_laco_de_redirects_vira_redirect_excessivo(n8n_no, liberado, cfg):
    """SEG-05: laço de redirects (mesmo host liberado) → no máx. 5 seguidos; o 6º = redirect_excessivo."""
    liberado.rotas["/webhook/loop"] = lambda req: (302, b"", {"Location": f"{liberado.base}/webhook/loop"})
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/loop"), [{"a": 1}])
    assert e.status == "erro" and n.erro_categoria == "redirect_excessivo" and len(liberado.hits("/webhook/loop")) <= 6


# ---------------- resposta gigante / aninhada ----------------

def test_resposta_json_gigante_termina_sem_estourar_memoria_ou_gravacao(n8n_no, liberado, cfg):
    """SEG-07/MV2-12: JSON de ~6 MB termina (sucesso ou erro por limite), nunca 'executando', gravação limitada."""
    corpo = json.dumps([{"k": "v" * 100, "i": i} for i in range(50_000)]).encode()
    liberado.rotas["/webhook/gg"] = lambda req: (200, corpo, None)
    inicio = time.monotonic()
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/gg"))
    _terminou(e, n)
    assert time.monotonic() - inicio < 20
    assert len(n.saida) <= 50 and len(_tudo(e)) < 10 * 1024 * 1024


def test_resposta_texto_gigante_e_resposta_grande_e_sem_vazar_corpo(n8n_no, liberado, cfg):
    """N8N-07(5): texto > 1 MB → erro resposta_grande; o texto gigante não vai inteiro para o histórico."""
    liberado.rotas["/webhook/tg"] = lambda req: (200, b"Q" * (3 * 1024 * 1024), {"Content-Type": "text/plain"})
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/tg"))
    assert e.status == "erro" and n.erro_categoria == "resposta_grande" and len(_tudo(e)) < 1024 * 1024


@pytest.mark.parametrize("profundidade", [1_000, 20_000, 200_000])
def test_resposta_json_muito_aninhada_nao_derruba_o_motor(n8n_no, liberado, cfg, profundidade):
    """SEG-07: JSON com milhares de níveis ([[[[…]]]]) não causa 500/RecursionError/execução pendurada."""
    corpo = ("[" * profundidade + "]" * profundidade).encode()
    liberado.rotas["/webhook/an"] = lambda req: (200, corpo, None)
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/an"))
    _terminou(e, n)
    if e.status == "erro":
        assert n.erro_categoria and "Traceback" not in (n.erro_mensagem or "") and "recursion" not in (n.erro_mensagem or "").lower()


def test_resposta_objeto_muito_aninhado_nao_derruba_o_motor(n8n_no, liberado, cfg):
    """SEG-07: objeto {"a":{"a":…}} com 50.000 níveis termina limpo e a execução seguinte ainda funciona."""
    n_ = 50_000
    corpo = ('{"a":' * n_ + "1" + "}" * n_).encode()
    liberado.rotas["/webhook/ao"] = lambda req: (200, corpo, None)
    liberado.rotas["/webhook/depois"] = lambda req: (200, {"ok": 1}, None)
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/ao"))
    _terminou(e)
    e2, _ = n8n_no(cfg(f"{liberado.base}/webhook/depois"))
    assert e2.status == "sucesso"


def test_lista_enorme_de_itens_limitada(n8n_no, liberado, cfg):
    """MV2-12: 100.000 itens pequenos → termina; gravação ≤ 50 itens."""
    corpo = json.dumps(list(range(100_000))).encode()
    liberado.rotas["/webhook/li"] = lambda req: (200, corpo, None)
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/li"))
    _terminou(e, n)
    assert len(n.saida) <= 50


def test_muitos_itens_de_entrada_nao_geram_rajada_ilimitada(n8n_no, liberado, cfg):
    """N8N-03: 300 itens de entrada → termina; execução em estado final (item = uma chamada por item, sem laço infinito)."""
    liberado.rotas["/webhook/m"] = lambda req: (200, {"ok": 1}, None)
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/m"), [{"i": i} for i in range(300)])
    _terminou(e)
    assert len(liberado.hits("/webhook/m")) <= 300


# ---------------- header injection ----------------

def test_crlf_no_corpo_json_nao_vira_header(n8n_no, liberado, cfg):
    """SEG-16(3): CR/LF em valores do item vai escapado no corpo JSON; o servidor vê UMA requisição, sem header injetado."""
    liberado.rotas["/webhook/ci"] = lambda req: (200, {"ok": 1}, None)
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/ci"), [{"v": "a\r\nX-Injetado: 1\r\n\r\nPOST /x HTTP/1.1"}])
    _terminou(e)
    assert len(liberado.requisicoes) == 1 and "x-injetado" not in liberado.requisicoes[0]["headers"]
    assert json.loads(liberado.requisicoes[0]["corpo"])["v"].startswith("a\r\nX-Injetado")


@pytest.mark.parametrize("v", ["a\r\nX-Injetado: 1", "a\nX-Injetado: 1", "a%0d%0aX-Injetado:%201", "a\r\n\r\nGET /admin HTTP/1.1"])
def test_crlf_em_url_de_expressao_nao_injeta_header_nem_segunda_requisicao(n8n_no, liberado, cfg, v):
    """SEG-16(3): CR/LF na URL resolvida → erro ou codificação; nunca header injetado nem requisição extra."""
    liberado.rotas["/webhook/cu"] = lambda req: (200, {"ok": 1}, None)
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/cu?x={{{{ $json.v }}}}"), [{"v": v}])
    _terminou(e)
    assert len(liberado.requisicoes) <= 1
    assert all("x-injetado" not in r["headers"] and r["rota"] == "/webhook/cu" for r in liberado.requisicoes)


@pytest.mark.parametrize("nome,valor", [("X-A\r\nInjetado: 1", "v"), ("X-A", "v\r\nInjetado: 1")])
def test_crlf_em_credencial_header_nao_injeta(n8n_no, liberado, cfg, criar_cred, nome, valor):
    """CRD-02/SEG-16: credencial 'header' com CR/LF no nome ou valor: recusada na criação ou erro na execução; nunca header injetado."""
    liberado.rotas["/webhook/cc"] = lambda req: (200, {"ok": 1}, None)
    criar_cred(nome="Hostil", tipo="header", valor=valor, header_nome=nome)
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/cc", credencial="Hostil"))
    _terminou(e)
    assert all("injetado" not in r["headers"] for r in liberado.requisicoes)
    assert all("injetado" not in " ".join(r["headers"].values()).lower() for r in liberado.requisicoes)


def test_crlf_em_credencial_bearer_nao_injeta(n8n_no, liberado, cfg, criar_cred):
    """CRD-02: bearer com \\r\\n no valor não cria header novo."""
    liberado.rotas["/webhook/cb"] = lambda req: (200, {"ok": 1}, None)
    criar_cred(nome="Hostil", tipo="bearer", valor="abc\r\nX-Injetado: 1")
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/cb", credencial="Hostil"))
    _terminou(e)
    assert all("x-injetado" not in r["headers"] for r in liberado.requisicoes)


def test_corpo_personalizado_hostil_continua_json_valido(n8n_no, liberado, cfg):
    """N8N-03: corpo personalizado com aspas/barras/controle/unicode vira JSON válido (round-trip exato)."""
    liberado.rotas["/webhook/cp"] = lambda req: (200, {"ok": 1}, None)
    hostil = 'x"}, "admin": true, "y": "\\ \U0001f600'
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/cp", enviar="personalizado", corpo="={{ $json.dados }}"),
                  [{"dados": {"v": hostil}}])
    _terminou(e)
    if liberado.requisicoes:
        assert json.loads(liberado.requisicoes[0]["corpo"]) == {"v": hostil}


# ---------------- credencial refletida pelo n8n falso ----------------

@pytest.mark.parametrize("modo", ["corpo_json", "texto", "erro500", "erro404", "erro401", "header_resposta", "aninhado"])
def test_credencial_refletida_nunca_e_gravada(n8n_no, liberado, cfg, criar_cred, cliente_adm, caplog, modo):
    """CRD-02/N8N-05: o 'n8n' reflete o Bearer (corpo, texto, erro, headers, aninhado) e o valor não aparece em NADA gravado, tela ou log."""
    caplog.set_level("DEBUG")
    criar_cred(nome="Cofre n8n", tipo="bearer", valor=SEGREDO)

    def rota(req):
        auth = req["headers"].get("authorization", "")
        if modo == "corpo_json":
            return 200, {"eco": auth, "puro": SEGREDO}, None
        if modo == "texto":
            return 200, f"token={SEGREDO}".encode(), {"Content-Type": "text/plain"}
        if modo == "erro500":
            return 500, {"erro": f"falha com {SEGREDO}"}, None
        if modo == "erro404":
            return 404, f"nada para {SEGREDO}".encode(), {"Content-Type": "text/plain"}
        if modo == "erro401":
            return 401, {"visto": auth}, None
        if modo == "header_resposta":
            return 200, {"ok": 1}, {"X-Eco": SEGREDO, "Set-Cookie": f"s={SEGREDO}"}
        return 200, {"a": {"b": [{"c": SEGREDO}]}}, None

    liberado.rotas["/webhook/rf"] = rota
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/rf", credencial="Cofre n8n"), [{"id": 1}])
    _terminou(e, n)
    assert SEGREDO not in _tudo(e)
    detalhe = cliente_adm.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).content.decode()
    assert SEGREDO not in detalhe and SEGREDO not in caplog.text


def test_credencial_basic_senha_refletida_nunca_e_gravada(n8n_no, liberado, cfg, criar_cred):
    """CRD-02: senha de credencial básica refletida (valor puro e Authorization) não é gravada."""
    criar_cred(nome="Basica", tipo="basic", usuario="maria", valor=SEGREDO)
    liberado.rotas["/webhook/bs"] = lambda req: (200, {"senha": SEGREDO, "auth": req["headers"]["authorization"]}, None)
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/bs", credencial="Basica"))
    _terminou(e)
    assert SEGREDO not in _tudo(e)


def test_credencial_refletida_com_aguardar_false_e_em_get(n8n_no, liberado, cfg, criar_cred):
    """CRD-02: GET e aguardar=false também não gravam o valor (requisições e saída)."""
    criar_cred(nome="Cofre n8n", tipo="bearer", valor=SEGREDO)
    liberado.rotas["/webhook/ag"] = lambda req: (200, {"eco": req["headers"].get("authorization")}, {"X-Eco": SEGREDO})
    for kw in ({"metodo": "GET"}, {"aguardar_resposta": False}):
        e, _ = n8n_no(cfg(f"{liberado.base}/webhook/ag", credencial="Cofre n8n", **kw), [{"id": 1}])
        _terminou(e)
        assert SEGREDO not in _tudo(e)


def test_credencial_no_token_da_url_nao_vaza(n8n_no, liberado, cfg):
    """SEG-09: ?token= / ?api-key= na URL do webhook é mascarado nas requisições gravadas."""
    liberado.rotas["/webhook/tk"] = lambda req: (500, {"m": "x"}, None)
    e, n = n8n_no(cfg(f"{liberado.base}/webhook/tk?token={SEGREDO}&api-key={SEGREDO}"))
    _terminou(e, n)
    assert SEGREDO not in json.dumps(n.requisicoes) and SEGREDO not in (n.erro_mensagem or "")


# ---------------- aguardar=false não lê além de 64 KB ----------------

def _servidor_lento(total, bloco=16 * 1024):
    """Servidor TCP cru que declara Content-Length=total e envia em blocos; conta quantos bytes o kernel aceitou antes de travar/fechar."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    estado = {"enviado": 0, "porta": srv.getsockname()[1], "fim": threading.Event()}

    def laco():
        srv.settimeout(10)
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        conn.settimeout(4)
        try:
            conn.recv(65536)
            conn.sendall(f"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: {total}\r\nConnection: close\r\n\r\n".encode())
            while estado["enviado"] < total:
                conn.sendall(b"L" * bloco)
                estado["enviado"] += bloco
        except OSError:
            pass
        finally:
            estado["fim"].set()
            conn.close()
            srv.close()

    threading.Thread(target=laco, daemon=True).start()
    return estado


def test_aguardar_false_nao_le_o_corpo_alem_de_64kb(n8n_no, settings, cfg):
    """N8N-04: aguardar_resposta=false lê no máximo ~64 KB do corpo (servidor que tenta enviar 40 MB é cortado cedo)."""
    estado = _servidor_lento(40 * 1024 * 1024)
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{estado['porta']}"]
    inicio = time.monotonic()
    e, n = n8n_no(cfg(f"http://127.0.0.1:{estado['porta']}/webhook/slow", aguardar_resposta=False, tempo_limite_s=10), [{"id": 1}])
    assert e.status == "sucesso" and [i["json"] for i in n.saida] == [{"id": 1, "n8n_status": 200}]
    estado["fim"].wait(5)
    assert time.monotonic() - inicio < 9
    assert estado["enviado"] < 4 * 1024 * 1024, f"o motor consumiu {estado['enviado']} bytes"


def test_aguardar_true_com_texto_gigante_corta_cedo(n8n_no, settings, cfg):
    """SEG-07: aguardar=true com corpo de 40 MB → resposta_grande depois de ler ~1 MB (não consome o corpo todo)."""
    estado = _servidor_lento(40 * 1024 * 1024)
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{estado['porta']}"]
    e, n = n8n_no(cfg(f"http://127.0.0.1:{estado['porta']}/webhook/slow", tempo_limite_s=10), [{"id": 1}])
    assert e.status == "erro" and n.erro_categoria == "resposta_grande"
    estado["fim"].wait(5)
    assert estado["enviado"] < 8 * 1024 * 1024


# ---------------- GET com valores hostis na query ----------------

HOSTIS = {
    "e_comercial": "x&admin=1", "igual": "a=b=c", "hash": "x#frag", "interrogacao": "x?y=1", "crlf": "a\r\nX-Injetado: 1",
    "pct": "%0d%0aX-Injetado:%201", "barra": "../../etc/passwd", "unicode": "ação ☃ 😀", "espaco": "a b+c",
    "aspas": "'\"<script>alert(1)</script>", "arroba": "x@169.254.169.254",
}


def test_get_com_valores_hostis_na_query_vai_codificado(n8n_no, liberado, cfg):
    """N8N-03: GET achata escalares em query string CODIFICADA: nada de parâmetro extra, header injetado, host ou caminho alterados."""
    liberado.rotas["/webhook/q"] = lambda req: (200, {"ok": 1}, None)
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/q", metodo="GET"), [dict(HOSTIS)])
    _terminou(e)
    if e.status == "erro":  # recusar valor com controle (CR/LF/NUL) é aceitável; nunca enviar algo adulterado
        assert all("x-injetado" not in r["headers"] for r in liberado.requisicoes)
        return
    assert len(liberado.requisicoes) == 1
    r = liberado.requisicoes[0]
    assert r["rota"] == "/webhook/q" and r["corpo"] == "" and "x-injetado" not in r["headers"]
    assert r["headers"]["host"] == f"127.0.0.1:{liberado.porta}"
    q = parse_qs(urlsplit(r["path"]).query, keep_blank_values=True)
    assert "admin" not in q and "frag" not in q and "y" not in q
    for chave, valor in HOSTIS.items():
        assert q[chave] == [valor], chave


def test_get_com_chaves_hostis_nao_cria_parametros_extras(n8n_no, liberado, cfg):
    """N8N-03: CHAVES do item com & = # [] viram um único parâmetro cada (codificadas), sem injetar outros."""
    liberado.rotas["/webhook/qk"] = lambda req: (200, {"ok": 1}, None)
    item = {"a&admin": "1", "b=c": "2", "x#y": "3", "k[]": "4", "../p": "5", "ç": "6"}
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/qk", metodo="GET"), [item])
    _terminou(e)
    if e.status == "sucesso":
        q = parse_qs(urlsplit(liberado.requisicoes[0]["path"]).query, keep_blank_values=True)
        assert q == {k: [v] for k, v in item.items()} and "admin" not in q


def test_get_valor_enorme_na_query_termina_sem_500(n8n_no, liberado, cfg):
    """N8N-03/SEG-07: valor de 200 KB na query (GET) → erro limpo ou envio; nunca travar/quebrar o servidor local."""
    liberado.rotas["/webhook/qe"] = lambda req: (200, {"ok": 1}, None)
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/qe", metodo="GET"), [{"v": "A" * 200_000}])
    _terminou(e)


def test_get_com_listas_e_objetos_hostis_nao_vazam_para_query(n8n_no, liberado, cfg):
    """N8N-03: valores não escalares (lista/objeto) ficam fora da query — inclusive os que contêm payload hostil."""
    liberado.rotas["/webhook/qn"] = lambda req: (200, {"ok": 1}, None)
    e, _ = n8n_no(cfg(f"{liberado.base}/webhook/qn", metodo="GET"),
                  [{"ok": "1", "lista": ["&admin=1"], "obj": {"admin": "1"}, "vazio": []}])
    _terminou(e)
    q = parse_qs(urlsplit(liberado.requisicoes[0]["path"]).query)
    assert q == {"ok": ["1"]}


# ---------------- estado/formato inválido ----------------

@pytest.mark.parametrize("campo,valor", [("tempo_limite_s", "abc"), ("tempo_limite_s", None), ("tempo_limite_s", 10**9),
                                         ("enviar", "../etc"), ("metodo", "DELETE"), ("aguardar_resposta", "talvez"),
                                         ("url", 123), ("url", ["http://a"]), ("corpo", {"x": 1})])
def test_config_invalida_nunca_vira_500_nem_chamada_extra(cliente_adm, fabrica_fluxo, salvar_grafo, h, cfg, liberado, modelos, campo, valor):
    """N8N-01/02: config com tipos/valores hostis → 4xx/pendência ao salvar, ou erro limpo na execução; nunca 500."""
    f = fabrica_fluxo(grafo=h.cadeia2(), status="rascunho")
    c = cfg(f"{liberado.base}/webhook/x")
    c[campo] = valor
    r = salvar_grafo(cliente_adm, f, h.cadeia2(h.no2("n", "chamar_n8n", c, x=1)))
    assert r.status_code < 500
    if r.status_code == 200:
        f.refresh_from_db()
        resp = cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
        assert resp.status_code < 500
        for ex in modelos.Execucao.objects.all():
            assert ex.status in ("sucesso", "erro")
