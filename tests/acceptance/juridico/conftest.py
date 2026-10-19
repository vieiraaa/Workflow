"""Fixtures do aceite M8 (Cadastro de processos, T-077). Só pela spec: docs/spec/juridico-cadastro.yaml (CAD-01..23),
permissoes.yaml (cadastro.*) e telas.yaml (TEL-27..35).

CONTRATO USADO (CAD-23): app `juridico` (Carteira, ConfigCadastro.obter(), Processo, Envio, ItemEnvio); worker
`call_command("processar_cadastros", "--uma-vez")`; settings JURIDICO_*; rotas/campos do bloco `contrato`.
Dify e DataJud FALSOS em UM servidor HTTP local (prefixos /dify e /datajud), liberado só via MOTOR_SSRF_LIBERAR (SEG-08).
PDFs fictícios montados em bytes no próprio teste. Nada de internet nem DATABASE_URL.
"""
import html as _html
import itertools
import json
import re
import time
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from tests.acceptance.m5.conftest import *  # noqa: F401,F403  (servidor, liberado, criar_cred, setor_a/b, logar, chave_credenciais…)

_seq = itertools.count(1)
NUMERO_RE = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")

SEGREDO_DIFY = "CHAVE-DIFY-FICTICIA-AB12CD34EF56"
SEGREDO_DATAJUD = "CHAVE-DATAJUD-FICTICIA-ZZ99YY88"


# ---------------- números CNJ ----------------

def cnj(seq=1234, ano=2022, j=8, tr=26, orgao=100, dv_errado=False):
    """→ (formatado, só dígitos). DV = 98 − (NNNNNNNAAAAJTROOOO00 mod 97); dv_errado=True troca o DV."""
    base = f"{seq:07d}{ano:04d}{j}{tr:02d}{orgao:04d}"
    dv = 98 - (int(base + "00") % 97)
    if dv_errado:
        dv = dv + 1 if dv < 98 else 2
    d = f"{base[:7]}{dv:02d}{base[7:]}"
    return f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}", d


def so_digitos(txt):
    return re.sub(r"\D", "", txt)


# ---------------- PDFs fictícios ----------------

def _esc(b):
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def pdf_bytes(texto=None, numero=None, marca=""):
    """PDF mínimo de 1 página. texto=None → sem texto (como escaneado). `numero` vai num comentário `% NUM:` (o Dify falso o
    usa para saber o que responder, mesmo quando o texto não existe). `marca` muda o sha256 sem mudar o texto."""
    linhas = [] if texto is None else texto.split("\n")
    fluxo = b"BT /F1 10 Tf 12 TL 20 800 Td " + b" T* ".join(b"(" + _esc(x.encode("cp1252")) + b") Tj" for x in linhas) + b" ET" if linhas else b""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(fluxo)).encode() + b" >>\nstream\n" + fluxo + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    out += f"% NUM:{numero or ''} MARCA:{marca}\n".encode()
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def texto_processo(numero, variante="a", tamanho=400):
    """Texto de um 'processo' fictício com pelo menos `tamanho` caracteres (≥ 200 → caminho de texto, CAD-07)."""
    base = (f"PODER JUDICIARIO Processo numero {numero} variante {variante}. Autor ATIVOS contra Joao da Silva Ficticio. "
            f"Acao de cobranca. Valor da causa R$ 1.234,56. ")
    while len(base) < tamanho:
        base += f"Texto fictício de preenchimento {variante}. "
    return base


def pdf_processo(numero, variante="a", **kw):
    return pdf_bytes(texto_processo(numero, variante), numero=numero, marca=variante), f"processo-{variante}.pdf"


def pdf_escaneado(numero, marca="esc"):
    return pdf_bytes(None, numero=numero, marca=marca), f"escaneado-{marca}.pdf"


def upload(conteudo, nome="arquivo.pdf"):
    return SimpleUploadedFile(nome, conteudo, content_type="application/pdf")


# ---------------- Dify FALSO ----------------

def campos_dify(numero, **mudancas):
    d = {"numero_cnj": numero, "numero_contrato_operacao": "OP-998877", "empresa": "ATIVOS S.A. SECURITIZADORA DE CRÉDITOS FINANCEIROS",
         "condicao": "Autor", "advogado_empresa": "Dra. Helena Fictícia", "adverso_nome": "João da Silva Fictício",
         "adverso_cpf_cnpj": "123.456.789-09", "advogado_adverso_nome": "Dr. Pedro Fictício", "advogado_adverso_oab": "OAB/SP 123456",
         "tipo_acao": "Ação de Cobrança", "rito": "Comum", "natureza": "Cível", "meio_tramitacao": "Eletrônico", "instancia": "1º Grau",
         "distribuido_em": "15/03/2022", "tribunal": "TJSP", "juizo": "1ª Vara Cível", "comarca": "São Paulo", "estado": "SP",
         "desdobramento": "", "fase_atual": "POSTULATÓRIA", "data_citacao": "20/04/2022", "valor_causa": "R$ 1.234,56",
         "pedidos_completos": "Condenação ao pagamento do valor devido.",
         "ultimas_movimentacoes": [{"data": "10/05/2023", "evento": "Juntada de petição"}], "observacoes": ""}
    d.update(mudancas)
    return d


class DifyFalso:
    """chat-messages {answer} (com cercas/JSON inválido/401/lento), files/upload {id}. Registra tudo o que recebe."""

    def __init__(self, srv, prefixo="/dify"):
        self.srv, self.prefixo = srv, prefixo
        self.respostas = {}   # numero formatado → dict de campos | callable(numero) → dict | str (answer cru)
        self.modo = None      # None|"cercas"|"prefixo"|"invalido"|"401"|"403"|"500"|"lento"|"upload_500"
        self.atraso = 0
        self.eco_chave = False  # reflete o header Authorization no `answer` (para provar mascaramento)
        self.extra = {}       # campos extras no JSON (ex.: marcador que só existe na resposta_ia)
        self._ups, self._n = {}, itertools.count(1)
        srv.rotas[f"{prefixo}/chat-messages"] = self._chat
        srv.rotas[f"{prefixo}/files/upload"] = self._upload

    @property
    def chats(self):
        return [json.loads(r["corpo"]) for r in self.srv.hits(f"{self.prefixo}/chat-messages")]

    @property
    def chats_req(self):
        return self.srv.hits(f"{self.prefixo}/chat-messages")

    @property
    def uploads(self):
        return self.srv.hits(f"{self.prefixo}/files/upload")

    def _upload(self, req):
        if self.modo == "upload_500":
            return 500, {"message": "falha no upload"}, None
        uid = f"up-{next(self._n)}"
        self._ups[uid] = req["corpo"]
        return 200, {"id": uid}, None

    def _numero(self, corpo):
        m = NUMERO_RE.search(corpo.get("query") or "")
        if m:
            return m.group(0)
        for f in corpo.get("files") or []:
            m = re.search(r"NUM:(\S*)", self._ups.get(f.get("upload_file_id"), ""))
            if m and m.group(1):
                return m.group(1)
        return None

    def _chat(self, req):
        corpo = json.loads(req["corpo"])
        if self.modo in ("401", "403"):
            return int(self.modo), {"code": "unauthorized", "message": "chave recusada"}, None
        if self.modo == "500":
            return 500, {"message": "erro interno do dify"}, None
        if self.modo == "lento" or self.atraso:
            time.sleep(self.atraso or 3)
        if corpo.get("query") == "ping":
            return 200, {"answer": "pong"}, None
        numero = self._numero(corpo)
        r = self.respostas.get(numero)
        if callable(r):
            r = r(numero)
        if isinstance(r, str):
            return 200, {"answer": r}, None
        d = dict(r if r is not None else campos_dify(numero or ""))
        d.update(self.extra)
        txt = json.dumps(d, ensure_ascii=False)
        if self.eco_chave:
            txt = txt[:-1] + f', "eco": "{req["headers"].get("authorization", "")}"}}'
        if self.modo == "cercas":
            txt = f"```json\n{txt}\n```"
        elif self.modo == "prefixo":
            txt = f"Segue o resultado solicitado:\n```json\n{txt}\n```\nQualquer dúvida, avise."
        elif self.modo == "invalido":
            txt = "Desculpe, não consegui montar o JSON."
        return 200, {"answer": txt}, None


# ---------------- DataJud FALSO ----------------

ALIASES = ["tjsp", "tjrj", "tjmg", "tjpr", "tjrs", "trf1", "trf3", "trf4", "trt2", "trt15", "tre-sp"]


def fonte_datajud(digitos, tribunal="TJSP", ajuizamento="2022-03-15T00:00:00.000Z",
                  orgao="1ª Vara Cível do Foro Central de São Paulo", assuntos=("Indenização por Dano Moral",), movimentos=()):
    return {"numeroProcesso": digitos, "tribunal": tribunal, "dataAjuizamento": ajuizamento, "classe": {"codigo": 7, "nome": "Procedimento Comum"},
            "orgaoJulgador": {"nome": orgao}, "assuntos": [{"codigo": 1, "nome": a} for a in assuntos],
            "movimentos": [{"codigo": 1, "nome": nome, "dataHora": dh} for dh, nome in movimentos]}


class DatajudFalso:
    def __init__(self, srv, prefixo="/datajud"):
        self.srv, self.prefixo = srv, prefixo
        self.fontes = {}     # dígitos → _source (None/ausente = não achou)
        self.status = 200
        self.atraso = 0
        self.instantes = []
        for a in ALIASES:
            srv.rotas[f"{prefixo}/api_publica_{a}/_search"] = self._busca

    @property
    def buscas(self):
        return [r for r in self.srv.requisicoes if r["rota"].startswith(self.prefixo) and r["rota"].endswith("/_search")]

    def _busca(self, req):
        self.instantes.append(time.monotonic())
        if self.atraso:
            time.sleep(self.atraso)
        if self.status != 200:
            return self.status, {"error": "recusado"}, None
        corpo = json.loads(req["corpo"])
        dig = corpo["query"]["match"]["numeroProcesso"]
        src = self.fontes.get(dig)
        hits = [{"_source": src}] if src else []
        return 200, {"hits": {"total": {"value": len(hits)}, "hits": hits}}, None


# ---------------- cenário completo ----------------

def _usuario(fabrica_usuario, client_cls, papel, setor, nome, email):
    u = fabrica_usuario(papel=papel, nome=nome, email=email)
    if setor is not None:
        u.setor = setor
        u.save()
    c = client_cls()
    c.force_login(u)
    return c, u


@pytest.fixture
def cad(db, servidor, settings, tmp_path, criar_cred, setor_a, setor_b, fabrica_usuario, cliente_adm, usuario_adm):
    """Cenário padrão: Dify+DataJud falsos liberados, credenciais no cofre, ConfigCadastro apontando para eles, setor A com acesso,
    carteiras, MEDIA_ROOT em tmp_path e usuários: adm, ana (Base/A), bruno (Coordenador/A), carla (Base/B, sem acesso)."""
    from django.test import Client

    settings.MOTOR_SSRF_LIBERAR = [f"127.0.0.1:{servidor.porta}"]
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.JURIDICO_DATAJUD_INTERVALO_S = 0
    settings.JURIDICO_DIFY_TIMEOUT_S = 5
    settings.JURIDICO_DATAJUD_TIMEOUT_S = 5
    dify, dj = DifyFalso(servidor), DatajudFalso(servidor)
    criar_cred(nome="Dify chave", tipo="bearer", valor=SEGREDO_DIFY)
    criar_cred(nome="DataJud chave", tipo="header", valor=f"APIKey {SEGREDO_DATAJUD}", header_nome="Authorization")
    Config = apps.get_model("juridico", "ConfigCadastro")
    cfg = Config.obter()
    cfg.dify_url = f"{servidor.base}/dify"
    cfg.dify_credencial = "Dify chave"
    cfg.datajud_url = f"{servidor.base}/datajud"
    cfg.datajud_credencial = "DataJud chave"
    cfg.save()
    cfg.setores_com_acesso.set([setor_a])
    Carteira = apps.get_model("juridico", "Carteira")
    cart = {}
    for nome, empresa in [("Ativos", "ATIVOS S.A. SECURITIZADORA DE CRÉDITOS FINANCEIROS"), ("Ailos", "COOPERATIVA DE CRÉDITO (SISTEMA AILOS)"),
                          ("Volvo", "Volvo do Brasil Veículos Ltda")]:
        cart[nome], _ = Carteira.objects.get_or_create(nome=nome, defaults={"empresa": empresa, "ativa": True})
        Carteira.objects.filter(pk=cart[nome].pk).update(empresa=empresa, ativa=True)
        cart[nome].refresh_from_db()
    ana_c, ana = _usuario(fabrica_usuario, Client, "Base", setor_a, "Ana Souza", "ana.souza@exemplo.test")
    bruno_c, bruno = _usuario(fabrica_usuario, Client, "Coordenador", setor_a, "Bruno Lima", "bruno.lima@exemplo.test")
    carla_c, carla = _usuario(fabrica_usuario, Client, "Base", setor_b, "Carla Dias", "carla.dias@exemplo.test")
    return SimpleNamespace(srv=servidor, dify=dify, datajud=dj, config=cfg, carteiras=cart, setor_a=setor_a, setor_b=setor_b,
                           adm=cliente_adm, adm_u=usuario_adm, ana=ana_c, ana_u=ana, bruno=bruno_c, bruno_u=bruno,
                           carla=carla_c, carla_u=carla, anonimo=Client(), tmp=tmp_path,
                           Processo=apps.get_model("juridico", "Processo"), Envio=apps.get_model("juridico", "Envio"),
                           ItemEnvio=apps.get_model("juridico", "ItemEnvio"), Carteira=Carteira, Config=Config)


# ---------------- ações ----------------

@pytest.fixture
def rodar():
    """Worker em uma passada (CAD-07/CAD-23)."""
    return lambda: call_command("processar_cadastros", "--uma-vez")


@pytest.fixture
def enviar(cad):
    """enviar(cliente, [(bytes, nome)…] | (bytes, nome)…, carteira=None, **extra) → resposta do POST juridico:enviar_pdfs."""

    def _e(cliente, *arquivos, carteira=None, **extra):
        if len(arquivos) == 1 and isinstance(arquivos[0], list):
            arquivos = arquivos[0]
        dados = {"arquivos": [upload(b, n) for b, n in arquivos], "carteira": carteira.pk if carteira else "", **extra}
        return cliente.post(reverse("juridico:enviar_pdfs"), dados)

    return _e


@pytest.fixture
def enviar_cnj(cad):
    def _e(cliente, numeros, carteira=None, **extra):
        return cliente.post(reverse("juridico:enviar_cnj"), {"numeros": numeros, "carteira": carteira.pk if carteira else "", **extra})

    return _e


@pytest.fixture
def ingerir(cad, enviar, rodar):
    """ingerir(cliente, numero, variante='a', carteira=None, campos=None, escaneado=False) → (ItemEnvio, Processo|None).
    Envia 1 PDF (com o número no texto), roda o worker e devolve o item processado."""

    def _i(cliente, numero, variante="a", carteira=None, campos=None, escaneado=False):
        if campos is not None:
            cad.dify.respostas[numero] = campos_dify(numero, **campos)
        arq = pdf_escaneado(numero, variante) if escaneado else pdf_processo(numero, variante)
        enviar(cliente, arq, carteira=carteira)
        rodar()
        item = cad.ItemEnvio.objects.order_by("pk").last()
        item.refresh_from_db()
        return item, item.processo

    return _i


# ---------------- leitura de telas ----------------

def html(r):
    return r.content.decode()


def texto(r):
    """HTML sem tags, entidades decodificadas, espaços normalizados."""
    bruto = re.sub(r"<(script|style)\b.*?</\1>", " ", html(r), flags=re.S)
    bruto = re.sub(r"<input\b[^>]*\bvalue=\"([^\"]*)\"[^>]*>", r" \1 ", bruto)  # valores de campos de formulário também são conteúdo
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", bruto)))


def momento(dt):
    """DD/MM/AAAA HH:MM no fuso do projeto (CAD-06)."""
    return timezone.localtime(dt).strftime("%d/%m/%Y %H:%M")


def data_br(d):
    return d.strftime("%d/%m/%Y")


def pks(lista):
    """pks de uma lista de objetos ou dicts (o contexto `processos`/`itens` da spec pode ser qualquer dos dois)."""
    return [x["pk"] if isinstance(x, dict) else x.pk for x in lista]


def html_cru(r):
    """HTML com entidades decodificadas (para achar textos que vão em atributos data-*)."""
    return _html.unescape(html(r))


@pytest.fixture
def ver():
    return SimpleNamespace(html=html, texto=texto, momento=momento, data_br=data_br, pks=pks, html_cru=html_cru)


def criar_processo(cad, numero=None, usuario=None, via="pdf", status="CONFERIR", valido=True, **campos):
    """Prepara estado pelo ORM (permitido pela CAD-23): Processo completo e válido por padrão."""
    n = next(_seq)
    fmt, dig = numero or cnj(5000 + n)
    dados = dict(numero=fmt, numero_digitos=dig, numero_valido=valido, status=status, pendencias=[], carteira=cad.carteiras["Ativos"],
                 empresa="ATIVOS S.A.", adverso_nome=f"Adverso Fictício {n}", adverso_cpf_cnpj="123.456.789-09", tribunal="TJSP",
                 comarca="São Paulo", juizo="1ª Vara Cível", estado="SP", valor_causa="1234.56", distribuido_em="2022-03-15",
                 criado_por=usuario or cad.ana_u, criado_via=via, origem_campos={})
    dados.update(campos)
    return cad.Processo.objects.create(**dados)
