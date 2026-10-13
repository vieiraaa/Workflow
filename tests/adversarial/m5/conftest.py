"""Fixtures do ADVERSARIAL M5 (cópia independente das do aceite; só pela spec: docs/spec/motor-v2.yaml, seguranca.yaml).

Servidor HTTP LOCAL em thread (nunca internet), liberado só via settings.MOTOR_SSRF_LIBERAR (SEG-08).
"""

import copy
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest
from django.apps import apps
from django.urls import reverse


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _enviar(self, status, corpo=b"", headers=None):
        self.send_response(status)
        for nome, valor in (headers or {}).items():
            self.send_header(nome, valor)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(corpo)

    def _tratar(self):
        srv = self.server.estado
        tamanho = int(self.headers.get("Content-Length") or 0)
        corpo = self.rfile.read(tamanho) if tamanho else b""
        partes = urlsplit(self.path)
        req = {"metodo": self.command, "path": self.path, "rota": partes.path, "query": parse_qs(partes.query),
               "headers": {k.lower(): v for k, v in self.headers.items()}, "corpo": corpo.decode("utf-8", "replace")}
        srv.requisicoes.append(req)
        jh = {"Content-Type": "application/json"}
        rota = partes.path
        if rota in srv.rotas:  # rotas dinâmicas registradas pelo teste: callable(req) -> (status, obj|bytes, headers)
            status, obj, hs = srv.rotas[rota](req)
            dados = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
            self._enviar(status, dados, {**jh, **(hs or {})})
        elif rota == "/ok":
            self._enviar(200, json.dumps({"ok": True, "n": 1}).encode(), jh)
        elif rota.startswith("/status/"):
            codigo = int(rota.rsplit("/", 1)[1])
            self._enviar(codigo, json.dumps({"erro": "detalhe", "codigo": codigo}).encode(), jh)
        elif rota.startswith("/eco"):
            self._enviar(200, json.dumps(req).encode(), jh)
        elif rota == "/lista":
            self._enviar(200, json.dumps([{"id": 1}, {"id": 2}, {"id": 3}]).encode(), jh)
        else:
            self._enviar(404, b"nao encontrado", {"Content-Type": "text/plain"})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _tratar


class ServidorLocal:
    def __init__(self):
        self.requisicoes = []
        self.rotas = {}
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._httpd.daemon_threads = True
        self._httpd.block_on_close = False
        self._httpd.estado = self
        self.porta = self._httpd.server_address[1]
        threading.Thread(target=self._httpd.serve_forever, daemon=True).start()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.porta}"

    def hits(self, prefixo=""):
        return [r for r in self.requisicoes if r["rota"].startswith(prefixo)]

    def parar(self):
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def servidor():
    s = ServidorLocal()
    yield s
    s.parar()


@pytest.fixture
def liberado(servidor, settings):
    """SEG-08: libera só este servidor de teste."""
    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{servidor.porta}"]
    return servidor


# ---------- construtores de grafo v2 (MV2-02) ----------

def itens(*jsons):
    return [{"json": j} for j in jsons]


def no2(id_, tipo, config=None, x=0, y=0, titulo=None, **extra):
    n = {"id": id_, "tipo": tipo, "titulo": titulo or id_, "posicao": {"x": x, "y": y}, "config": config or {},
         "desativado": False, "executar_uma_vez": False, "em_erro": "parar"}
    n.update(extra)
    return n


def aresta(de, para, saida=0, entrada=0):
    return {"de": de, "saida": saida, "para": para, "entrada": entrada}


def grafo2(nos, arestas, dados_fixos=None, notas=None):
    """arestas: dicts ou tuplas (de, para[, saida[, entrada]])."""
    ars = [a if isinstance(a, dict) else aresta(*a) for a in arestas]
    return {"versao": 2, "nos": nos, "arestas": ars, "notas": notas or [], "dados_fixos": dados_fixos or {}}


def cfg_http2(url, metodo="GET", query=None, headers=None, corpo=None, **extra):
    c = {"metodo": metodo, "url": url, "query": query or [], "headers": headers or [],
         "corpo": corpo or {"tipo": "nenhum", "conteudo": ""}, "credencial": None, "resposta": "automatica",
         "paginacao": None, "resposta_completa": False}
    c.update(extra)
    return c


def cfg_editar(campos, incluir_outros=False):
    """campos: [(nome, valor, tipo)]"""
    return {"modo": "manual", "campos": [{"nome": n, "valor": v, "tipo": t} for n, v, t in campos],
            "incluir_outros": incluir_outros}


def cadeia2(*meio, dados_fixos=None, com_saida=False):
    """gatilho 'g' → nós do meio (dicts de nó, na ordem) [→ saída 's']."""
    nos = [no2("g", "gatilho", titulo="Início")] + list(meio)
    if com_saida:
        nos.append(no2("s", "saida", x=2000, titulo="Resultado"))
    ids = [n["id"] for n in nos]
    return grafo2(nos, list(zip(ids, ids[1:], strict=False)), dados_fixos)


@pytest.fixture
def h():
    """Atalhos de construção (itens, no2, aresta, grafo2, cfg_http2, cfg_editar, cadeia2)."""
    class H:
        pass

    for f in (itens, no2, aresta, grafo2, cfg_http2, cfg_editar, cadeia2):
        setattr(H, f.__name__, staticmethod(f))
    return H


@pytest.fixture
def modelos():
    class M:
        Execucao = apps.get_model("execucoes", "Execucao")
        ExecucaoNo = apps.get_model("execucoes", "ExecucaoNo")
        Fluxo = apps.get_model("fluxos", "Fluxo")

    return M


@pytest.fixture
def executar(fabrica_fluxo, modelos):
    """Fluxo com o grafo + POST fluxos:executar. Devolve (resposta, execucao|None, fluxo)."""

    def _exec(cliente, grafo, status="ativo", follow=False, fluxo=None):
        f = fluxo or fabrica_fluxo(grafo=copy.deepcopy(grafo), status=status)
        antes = set(modelos.Execucao.objects.values_list("pk", flat=True))
        r = cliente.post(reverse("fluxos:executar", kwargs={"pk": f.pk}), follow=follow)
        novas = modelos.Execucao.objects.exclude(pk__in=antes).order_by("pk")
        return r, novas.last(), f

    return _exec


@pytest.fixture
def nos_de(modelos):
    return lambda e: list(modelos.ExecucaoNo.objects.filter(execucao=e).order_by("ordem"))


@pytest.fixture
def no(modelos):
    return lambda e, id_: modelos.ExecucaoNo.objects.get(execucao=e, no_id=id_)


@pytest.fixture
def jsons():
    """jsons(execucaoNo) → [item['json'] …] da saída gravada."""
    return lambda n: [i["json"] for i in n.saida]


@pytest.fixture
def grafo_do_editor(fabrica_fluxo):
    """Abre fluxos:editor e devolve o grafo do json_script id="grafo-inicial"."""

    def _ler(cliente, fluxo):
        r = cliente.get(reverse("fluxos:editor", kwargs={"pk": fluxo.pk}))
        assert r.status_code == 200
        m = re.search(r'<script id="grafo-inicial"[^>]*>(.*?)</script>', r.content.decode(), re.S)
        assert m, "json_script grafo-inicial ausente"
        return json.loads(m.group(1))

    return _ler


@pytest.fixture
def avaliar(executar, cadeia2_dados, no, jsons, cliente_adm):
    """avaliar(valor, tipo='texto', entrada=None) → valor do campo `r` produzido por Editar campos (MV2-10/11)."""

    def _av(valor, tipo="texto", entrada=None, titulo_dados="Dados"):
        _, e, _ = executar(cliente_adm, cadeia2_dados(valor, tipo, entrada, titulo_dados))
        assert e is not None and e.status == "sucesso", getattr(e, "erro_resumo", None)
        return jsons(no(e, "calc"))[0]["r"]

    return _av


@pytest.fixture
def cadeia2_dados():
    ENTRADA = {"n": 5, "nome": "Ana", "lista": [10, 20, 30], "obj": {"k": "v"}, "txt": "Olá"}

    def _mk(valor, tipo="texto", entrada=None, titulo_dados="Dados"):
        pins = {"d": itens(*(entrada if entrada is not None else [ENTRADA]))}
        return cadeia2(no2("d", "sem_operacao", x=200, titulo=titulo_dados),
                       no2("calc", "editar_campos", cfg_editar([("r", valor, tipo)]), x=400, titulo="Calc"),
                       dados_fixos=pins)

    return _mk


@pytest.fixture
def executar_expr(executar, cadeia2_dados, no, cliente_adm):
    """executar_expr(valor, tipo) → (execucao, ExecucaoNo 'calc'); não exige sucesso (para erros)."""

    def _ex(valor, tipo="texto", entrada=None):
        _, e, _ = executar(cliente_adm, cadeia2_dados(valor, tipo, entrada))
        return e, no(e, "calc")

    return _ex


@pytest.fixture
def rodar_no(executar, cliente_adm, no, jsons):
    """rodar_no(tipo, config, entrada, saidas=1, **extra_no) → (execucao, [lista de jsons de cada saída]).

    gatilho → Dados (dados fixos) → <nó testado> → um 'sem operação' por saída (S0, S1…), cada um na alça i.
    Nó sem itens (status sem_itens) devolve [] para a saída.
    """

    def _rodar(tipo, config, entrada, saidas=1, **extra):
        nos = [no2("g", "gatilho", titulo="Início"), no2("d", "sem_operacao", x=1, titulo="Dados"),
               no2("t", tipo, config, x=2, titulo="Testado", **extra)]
        ars = [("g", "d"), ("d", "t")]
        for i in range(saidas):
            nos.append(no2(f"s{i}", "sem_operacao", x=3, y=i * 100, titulo=f"S{i}"))
            ars.append(aresta("t", f"s{i}", i, 0))
        _, e, _ = executar(cliente_adm, grafo2(nos, ars, {"d": itens(*entrada)}))
        assert e is not None
        return e, [jsons(no(e, f"s{i}")) for i in range(saidas)]

    return _rodar


@pytest.fixture
def nao_liberado():
    """Segundo servidor local que NÃO entra em MOTOR_SSRF_LIBERAR (o motor tem de bloqueá-lo, SEG-02)."""
    s = ServidorLocal()
    yield s
    s.parar()


@pytest.fixture
def http_no(executar, cliente_adm, liberado, h, no, jsons):
    """http_no(config_http, entrada=[{}], **extra_no) → (execucao, ExecucaoNo 'h'). Cadeia g → Dados(pin) → http 'h'."""

    def _h(config, entrada=None, **extra):
        g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"), h.no2("h", "http", config, x=2, titulo="HTTP", **extra),
                      dados_fixos={"d": h.itens(*(entrada if entrada is not None else [{}]))})
        _, e, _ = executar(cliente_adm, g)
        return e, no(e, "h")

    return _h


# ---------------- parte C: credenciais, setores, importação ----------------

@pytest.fixture(autouse=True)
def chave_credenciais(settings):
    """SEG-18: chave de teste gerada na fixture (settings.CREDENCIAIS_CHAVE, MV2-18 C2)."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:  # dependência ainda não instalada: só os testes de credencial dependem dela
        return None
    settings.CREDENCIAIS_CHAVE = Fernet.generate_key().decode()
    return settings.CREDENCIAIS_CHAVE


@pytest.fixture
def mk_setor(db):
    Setor = apps.get_model("contas", "Setor")
    return lambda nome: Setor.objects.create(nome=nome)


@pytest.fixture
def setor_a(mk_setor):
    return mk_setor("Setor A Fictício")


@pytest.fixture
def setor_b(mk_setor):
    return mk_setor("Setor B Fictício")


@pytest.fixture
def logar(fabrica_usuario, client):
    """logar(papel, setor=None) → (Client logado, usuário). Papéis: Adm|Coordenador|Base."""
    from django.test import Client

    def _l(papel, setor=None):
        u = fabrica_usuario(papel=papel)
        if setor is not None:
            u.setor = setor
            u.save()
        c = Client()
        c.force_login(u)
        return c, u

    return _l


@pytest.fixture
def fluxo_no_setor(fabrica_fluxo, modelos):
    def _f(setor, **kw):
        f = fabrica_fluxo(**kw)
        modelos.Fluxo.objects.filter(pk=f.pk).update(setor=setor)
        f.refresh_from_db()
        return f

    return _f


@pytest.fixture
def Credencial(db):
    return apps.get_model("credenciais", "Credencial")


@pytest.fixture
def criar_cred(cliente_adm):
    """criar_cred(nome, tipo='bearer', valor='…', setor=None, **campos) → resposta do POST credenciais:nova (Adm)."""

    def _c(nome="Digisac", tipo="bearer", valor="SEGREDO-CRED-VALOR-123", setor="", **campos):
        dados = {"nome": nome, "tipo": tipo, "valor": valor, "setor": setor, **campos}
        return cliente_adm.post(reverse("credenciais:nova"), dados)

    return _c


# ---------------- importar / exportar (MV2-13, MV2-18 C6/C9) ----------------

N8N = "n8n-nodes-base."


def _n8n_no(nome, tipo, params=None, pos=(0, 0), versao=1, **extra):
    return {"id": f"id-{nome}", "name": nome, "type": N8N + tipo, "typeVersion": versao, "position": list(pos),
            "parameters": params or {}, **extra}


def _liga(origem, *destinos_por_saida):
    return {origem: {"main": [[{"node": d, "type": "main", "index": 0} for d in saida] for saida in destinos_por_saida]}}


def _n8n(nos, conexoes=None, nome="Fluxo n8n fictício", **raiz):
    c = {}
    for x in conexoes or []:
        c.update(x)
    return {"name": nome, "nodes": nos, "connections": c, "pinData": {}, "active": False, "settings": {}, **raiz}


@pytest.fixture
def imp(cliente_adm, modelos):
    """Ferramentas de importação: n8n_no, liga, n8n, importar(cliente, obj_ou_bytes, **post_extra), exportar(cliente, fluxo)."""
    import json as _json

    from django.core.files.uploadedfile import SimpleUploadedFile

    class I:
        n8n_no = staticmethod(_n8n_no)
        liga = staticmethod(_liga)
        n8n = staticmethod(_n8n)

        @staticmethod
        def arquivo(conteudo, nome="fluxo.json"):
            dados = conteudo if isinstance(conteudo, bytes) else _json.dumps(conteudo).encode()
            return SimpleUploadedFile(nome, dados, content_type="application/json")

        @classmethod
        def importar(cls, cliente, conteudo, json_=True, **post_extra):
            kw = {"HTTP_ACCEPT": "application/json"} if json_ else {}
            return cliente.post(reverse("fluxos:importar"), {"arquivo": cls.arquivo(conteudo), **post_extra}, **kw)

        @staticmethod
        def exportar(cliente, fluxo):
            return cliente.get(reverse("fluxos:exportar", kwargs={"pk": fluxo.pk}))

        @staticmethod
        def novos(antes):
            return modelos.Fluxo.objects.exclude(pk__in=antes)

        @staticmethod
        def pks():
            return set(modelos.Fluxo.objects.values_list("pk", flat=True))

    return I
