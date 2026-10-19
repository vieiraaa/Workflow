"""Clientes do Dify e do DataJud (CAD-07, CAD-07a, CAD-10, CAD-14, CAD-18).

Tudo passa por `apps.motor.http.requisitar` (SSRF, pin de IP, redirect manual, limites): nenhum
caminho de rede novo. Só estes dois chamadores usam prazo maior, limite de 2 MB e o repositório de
certificados do sistema (truststore); a verificação TLS NUNCA é desligada. A chave vem do cofre
(Credencial) e nunca entra em mensagem, log ou texto gravado.
"""

import json
import re
import ssl
import threading
import time
import uuid
from urllib.parse import urlsplit

from django.conf import settings

from apps.motor import credenciais, mascarar
from apps.motor import http as http_motor
from apps.motor.erros import FalhaNo

MSG_PEM = "Certificado inválido: cole o PEM completo (BEGIN/END CERTIFICATE)."
MSG_TLS_DIFY = (
    "Não foi possível validar o certificado do Dify. Peça à TI um certificado válido "
    "ou cadastre a CA em Configuração."
)
MSG_DIFY_RECUSOU = "O Dify recusou a chave: confira a credencial em Configuração."
MSG_DATAJUD_RECUSOU = "Chave do DataJud recusada: atualize a credencial em Configuração."
RE_PEM = re.compile(
    r"-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----", re.MULTILINE
)
QUERY_PDF_ANEXADO = (
    "O processo está no PDF ANEXADO (pode ser escaneado ou protegido contra cópia). "
    "Leia o arquivo inteiro, página por página, e extraia os dados seguindo exatamente as "
    "instruções e o formato JSON."
)


class ErroCliente(Exception):
    """Falha de um chamador externo: `categoria` + `mensagem` próprias (sem texto de driver)."""

    def __init__(self, categoria, mensagem):
        super().__init__(mensagem)
        self.categoria = categoria
        self.mensagem = mensagem


def mascarar_texto(texto, segredos):
    """Troca por •••• os valores de credencial (crus, JSON-escapados ou percent-encoded)."""
    if not texto or not segredos:
        return texto or ""
    pacote = {"corpo": texto, "headers": [], "query": []}
    return mascarar.ocultar_valores(pacote, segredos)["corpo"]


# ---------------------------------------------------------------- TLS (CAD-07a)
def validar_pem(pem):
    """Levanta ValueError(MSG_PEM) se o PEM não carrega como certificado de CA."""
    pem = (pem or "").strip()
    if not pem:
        return
    if not RE_PEM.search(pem):
        raise ValueError(MSG_PEM)
    try:
        ssl.create_default_context().load_verify_locations(cadata=pem)
    except ssl.SSLError, ValueError:
        raise ValueError(MSG_PEM) from None


def contextos_tls(url, ca_pem=""):
    """Contextos TLS a tentar, em ordem: cadeia padrão (None), repositório do sistema operacional
    (truststore) e, só se houver `ca_pem`, a cadeia padrão + essa CA (SÓ para o host de `url`)."""
    contextos = [None]
    try:
        import truststore

        contextos.append(truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    except ImportError, OSError, ssl.SSLError:
        pass
    if (ca_pem or "").strip() and urlsplit(url).hostname:
        try:
            contexto = ssl.create_default_context()
            contexto.load_verify_locations(cadata=ca_pem.strip())
            contextos.append(contexto)
        except ssl.SSLError, ValueError:
            pass
    return contextos


def _requisitar(url, *, metodo, headers, corpo, prazo_s, ca_pem="", **extra):
    """Uma chamada pelo cliente do motor, tentando os contextos TLS só em falha de certificado."""
    ultimo = None
    for contexto in contextos_tls(url, ca_pem):
        try:
            return http_motor.requisitar(
                metodo=metodo,
                url=url,
                headers=headers,
                corpo=corpo,
                prazo_s=prazo_s,
                prazo_max_s=prazo_s,
                corpo_max=settings.JURIDICO_RESPOSTA_MAX_BYTES,
                contexto_tls=contexto,
                **extra,
            )
        except http_motor.ErroHttp as erro:
            if erro.categoria != "tls":
                raise
            ultimo = erro
    raise ultimo


# ---------------------------------------------------------------- credenciais
def _cabecalho(nome, tipo, rotulo):
    if not (nome or "").strip():
        raise ErroCliente(
            "credencial", f"Credencial do {rotulo} não configurada: escolha-a em Configuração."
        )
    try:
        tipo_cred, dados = credenciais.carregar(nome, None, (tipo,))
    except FalhaNo as falha:
        raise ErroCliente("credencial", falha.mensagem) from None
    cabecalho, valor, segredos = credenciais.cabecalho_http(tipo_cred, dados)
    return {"nome": cabecalho, "valor": valor}, {
        s for s in segredos if isinstance(s, str) and len(s) >= 4
    }


def _juntar(base, caminho):
    return base.rstrip("/") + "/" + caminho.lstrip("/")


def _json(resposta):
    corpo = resposta.get("corpo")
    if isinstance(corpo, dict | list):
        return corpo
    try:
        return json.loads(resposta.get("texto", ""))
    except ValueError, RecursionError:
        return None


def _falha_de_rede(erro, sujeito):
    if erro.categoria == "tls":
        return ErroCliente(
            "tls",
            MSG_TLS_DIFY
            if sujeito == "Dify"
            else "Não foi possível validar o certificado do DataJud.",
        )
    motivo = http_motor.MENSAGENS.get(erro.categoria, "falha de conexão").rstrip(".")
    motivo = motivo[0].lower() + motivo[1:]
    return ErroCliente(erro.categoria, f"{motivo}")


# ---------------------------------------------------------------- Dify
class Dify:
    def __init__(self, config):
        self.base = config.dify_url
        self.usuario = config.dify_usuario
        self.ca_pem = config.dify_ca_pem
        self.cabecalho, self.segredos = _cabecalho(config.dify_credencial, "bearer", "Dify")
        self.prazo = float(settings.JURIDICO_DIFY_TIMEOUT_S)

    def _chamar(self, caminho, corpo, content_type):
        headers = [
            {"nome": "Content-Type", "valor": content_type},
            {"nome": self.cabecalho["nome"], "valor": self.cabecalho["valor"]},
        ]
        try:
            resposta = _requisitar(
                _juntar(self.base, caminho),
                metodo="POST",
                headers=headers,
                corpo=corpo,
                prazo_s=self.prazo,
                ca_pem=self.ca_pem,
            )
        except http_motor.ErroHttp as erro:
            raise _falha_de_rede(erro, "Dify") from None
        if resposta["status"] in (401, 403):
            raise ErroCliente("recusada", MSG_DIFY_RECUSOU)
        if not 200 <= resposta["status"] < 300:
            raise ErroCliente("http", f"O Dify respondeu {resposta['status']}")
        if resposta.get("truncado"):
            raise ErroCliente("resposta_grande", "A resposta do Dify passou do limite de 2 MB")
        return resposta

    def conversar(self, query, arquivo_id=None):
        """Devolve (texto da resposta `answer`, resposta bruta mascarada)."""
        corpo = {
            "inputs": {},
            "query": query,
            "response_mode": "blocking",
            "user": self.usuario,
        }
        if arquivo_id:
            corpo["files"] = [
                {"type": "document", "transfer_method": "local_file", "upload_file_id": arquivo_id}
            ]
        resposta = self._chamar(
            "chat-messages", json.dumps(corpo, ensure_ascii=False), "application/json"
        )
        bruto = mascarar_texto(resposta.get("texto", ""), self.segredos)
        dados = _json(resposta)
        answer = dados.get("answer") if isinstance(dados, dict) else None
        if not isinstance(answer, str):
            raise ErroCliente("formato", "A IA não devolveu os dados no formato esperado.")
        return answer, bruto

    def enviar_arquivo(self, conteudo, nome):
        """files/upload (multipart: file, user) → id do arquivo no Dify."""
        limite = "----cadastro" + uuid.uuid4().hex
        nome_seguro = re.sub(r'[\r\n"\\]', "_", nome or "arquivo.pdf")
        partes = [
            (
                f'--{limite}\r\nContent-Disposition: form-data; name="user"\r\n\r\n'
                f"{self.usuario}\r\n"
            ).encode(),
            (
                f'--{limite}\r\nContent-Disposition: form-data; name="file"; '
                f'filename="{nome_seguro}"\r\nContent-Type: application/pdf\r\n\r\n'
            ).encode(),
            conteudo,
            f"\r\n--{limite}--\r\n".encode(),
        ]
        resposta = self._chamar(
            "files/upload", b"".join(partes), f"multipart/form-data; boundary={limite}"
        )
        dados = _json(resposta)
        identificador = dados.get("id") if isinstance(dados, dict) else None
        if not isinstance(identificador, str) or not identificador:
            raise ErroCliente("formato", "O Dify não devolveu o identificador do arquivo.")
        return identificador


# ---------------------------------------------------------------- DataJud
_trava = threading.Lock()
_ultima_consulta = [0.0]


def _respeitar_intervalo():
    """No máximo 1 consulta a cada JURIDICO_DATAJUD_INTERVALO_S (CAD-10), entre threads."""
    intervalo = float(settings.JURIDICO_DATAJUD_INTERVALO_S)
    with _trava:
        espera = _ultima_consulta[0] + intervalo - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        _ultima_consulta[0] = time.monotonic()


class DataJud:
    def __init__(self, config):
        self.base = config.datajud_url
        self.cabecalho, self.segredos = _cabecalho(config.datajud_credencial, "header", "DataJud")
        self.prazo = float(settings.JURIDICO_DATAJUD_TIMEOUT_S)

    def consultar(self, alias, digitos):
        """Primeiro hit do índice (dict `_source`) ou None se não achou."""
        corpo = json.dumps({"query": {"match": {"numeroProcesso": digitos}}, "size": 1})
        headers = [
            {"nome": "Content-Type", "valor": "application/json"},
            {"nome": self.cabecalho["nome"], "valor": self.cabecalho["valor"]},
        ]
        _respeitar_intervalo()
        try:
            resposta = _requisitar(
                _juntar(self.base, f"api_publica_{alias}/_search"),
                metodo="POST",
                headers=headers,
                corpo=corpo,
                prazo_s=self.prazo,
            )
        except http_motor.ErroHttp as erro:
            raise _falha_de_rede(erro, "DataJud") from None
        if resposta["status"] in (401, 403):
            raise ErroCliente("recusada", MSG_DATAJUD_RECUSOU)
        if not 200 <= resposta["status"] < 300:
            raise ErroCliente("http", f"O DataJud respondeu {resposta['status']}")
        dados = _json(resposta)
        try:
            hits = dados["hits"]["hits"]
        except KeyError, TypeError:
            raise ErroCliente("formato", "O DataJud devolveu uma resposta inesperada.") from None
        if not isinstance(hits, list):
            raise ErroCliente("formato", "O DataJud devolveu uma resposta inesperada.")
        fonte = hits[0].get("_source") if hits and isinstance(hits[0], dict) else None
        return fonte if isinstance(fonte, dict) else None
