"""Cliente HTTP do motor, com proteção SSRF (SEG-01..08, SEG-10, SEG-11).

Fluxo de cada requisição (e de cada redirect):
 1. valida a URL (esquema http/https, sem credenciais, sem `\\`, `#@` nem caracteres de controle);
 2. normaliza o host (IPv4 em decimal/octal/hex/abreviado, IPv6, `localhost`);
 3. resolve o DNS UMA vez e valida TODOS os IPs (loopback, privados, link-local, CGNAT,
    multicast, reservados e IPv4 embutido em IPv6: mapeado, compatível, NAT64, 6to4 e Teredo);
 4. conecta ao IP validado (pin anti DNS rebinding), enviando o Host e o SNI originais;
 5. redirects manuais (máx. 5), cada destino revalidado do zero.
A resposta é lida em streaming até 1 MB já descompactado (`truncado`). Erros viram categorias
da SEG-10 com mensagem própria: a exceção do driver nunca chega ao usuário.

`settings.MOTOR_SSRF_LIBERAR` (lista de "host:porta", vazia em todos os ambientes) só é
alterada por testes: um host:porta exato dessa lista dispensa a validação de IP.
"""

import ipaddress
import json
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as PrazoDeDns
from urllib.parse import quote, urlencode, urljoin, urlsplit

import httpx
from django.conf import settings

from .mascarar import sensivel

PRAZO_DNS = 5.0
REDIRECTS = {301, 302, 303, 307, 308}
IGNORADOS_DO_USUARIO = {"host", "content-length", "transfer-encoding", "connection", "upgrade"}
NOMES_LOCAIS = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}

MENSAGENS = {
    "bloqueado_ssrf": "Destino bloqueado por segurança: endereço não permitido.",
    "timeout": "A requisição excedeu o tempo limite.",
    "dns": "Não foi possível resolver o endereço (DNS).",
    "conexao": "Não foi possível conectar ao servidor.",
    "tls": "Falha na conexão segura (TLS).",
    "redirect_excessivo": "Redirecionamentos demais (máximo de 5).",
    "http_4xx": "O servidor respondeu com erro do cliente (4xx).",
    "http_5xx": "O servidor respondeu com erro do servidor (5xx).",
}

_CARACTERES_PROIBIDOS = re.compile(r"[\x00-\x20\x7f\\]")
_SO_IPV4_LEGADO = re.compile(r"[0-9a-fA-FxX.]+")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_SEIS_PARA_QUATRO = ipaddress.ip_network("2002::/16")
_TEREDO = ipaddress.ip_network("2001::/32")


class ErroHttp(Exception):
    """Erro do cliente com `categoria` (SEG-10) e `mensagem` própria (sem texto de driver)."""

    def __init__(self, categoria, mensagem=None):
        self.categoria = categoria
        self.mensagem = mensagem or MENSAGENS[categoria]
        super().__init__(self.mensagem)


def _limite(nome):
    """Limite do motor vindo das settings (MOTOR_*, SEG-16 item 7)."""
    return getattr(settings, f"MOTOR_{nome}")


def categoria_de_status(status):
    """`http_4xx`/`http_5xx` para respostas de erro; None para as demais."""
    if 400 <= status < 500:
        return "http_4xx"
    if 500 <= status < 600:
        return "http_5xx"
    return None


def _bloqueado(motivo=None):
    return ErroHttp("bloqueado_ssrf", motivo)


# ---------------------------------------------------------------- IPs e hosts
def _ipv4_embutidos(ip):
    """IPv4 escondidos num IPv6: mapeado, compatível, NAT64, 6to4 e Teredo (servidor e cliente)."""
    if ip.version != 6:
        return []
    valor, achados = int(ip), []
    if ip.ipv4_mapped is not None:
        achados.append(ip.ipv4_mapped)
    elif valor >> 32 == 0:  # ::a.b.c.d (compatível)
        achados.append(ipaddress.IPv4Address(valor & 0xFFFFFFFF))
    if ip in _NAT64:
        achados.append(ipaddress.IPv4Address(valor & 0xFFFFFFFF))
    if ip in _SEIS_PARA_QUATRO:
        achados.append(ipaddress.IPv4Address((valor >> 80) & 0xFFFFFFFF))
    if ip in _TEREDO:
        achados.append(ipaddress.IPv4Address((valor >> 64) & 0xFFFFFFFF))  # servidor
        achados.append(ipaddress.IPv4Address((valor & 0xFFFFFFFF) ^ 0xFFFFFFFF))  # cliente
    return achados


def ip_proibido(ip):
    """True se o IP (ou um IPv4 embutido nele) não deve receber conexões do motor."""
    ip = ipaddress.ip_address(ip) if isinstance(ip, str) else ip
    if ip.is_loopback or ip.is_unspecified or ip.is_link_local or ip.is_multicast:
        return True
    if ip.version == 6 and ip.is_site_local:
        return True
    embutidos = _ipv4_embutidos(ip)
    if embutidos:  # mapeado, compatível, NAT64, 6to4, Teredo: vale o IPv4 que carregam
        return any(ip_proibido(embutido) for embutido in embutidos)
    if ip.is_reserved or not ip.is_global:
        return True
    return ip.version == 4 and ip in _CGNAT


def _ip_literal(host):
    """IP que o host representa (IPv6, IPv4 e formas legadas decimal/octal/hex/curta) ou None."""
    if ":" in host:
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            raise _bloqueado("URL inválida.") from None
    if _SO_IPV4_LEGADO.fullmatch(host):
        try:
            return ipaddress.IPv4Address(socket.inet_aton(host))
        except OSError:
            if all(parte.isdigit() or parte == "" for parte in host.split(".")):
                raise _bloqueado("URL inválida.") from None
    return None


# ---------------------------------------------------------------- destino
class _Destino:
    def __init__(self, url):
        if _CARACTERES_PROIBIDOS.search(url):
            raise _bloqueado("URL inválida.")
        try:
            partes = urlsplit(url)
            porta = partes.port
        except ValueError:
            raise _bloqueado("URL inválida.") from None
        if partes.scheme.lower() not in ("http", "https"):
            raise _bloqueado("Só são permitidas URLs http e https.")
        if "@" in partes.netloc or "@" in partes.fragment:
            raise _bloqueado("URLs com credenciais não são permitidas.")
        host = (partes.hostname or "").rstrip(".").lower()
        if not host:
            raise _bloqueado("A URL precisa de um endereço (host).")
        self.esquema = partes.scheme.lower()
        self.host = host
        self.porta = porta or (443 if self.esquema == "https" else 80)
        self.porta_explicita = porta
        caminho = partes.path or "/"
        self.alvo = caminho + (f"?{partes.query}" if partes.query else "")

    @property
    def liberado(self):
        return f"{self.host}:{self.porta}" in set(settings.MOTOR_SSRF_LIBERAR)

    @property
    def cabecalho_host(self):
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{host}:{self.porta_explicita}" if self.porta_explicita else host

    @property
    def origem(self):
        return (self.esquema, self.host, self.porta)


def _resolver_dns(host, porta):
    with ThreadPoolExecutor(max_workers=1) as pool:
        futuro = pool.submit(socket.getaddrinfo, host, porta, 0, socket.SOCK_STREAM)
        try:
            return futuro.result(timeout=PRAZO_DNS)
        except PrazoDeDns:
            raise ErroHttp("dns") from None
        except OSError:  # socket.gaierror e afins
            raise ErroHttp("dns") from None


def _enderecos_validados(destino):
    """IPs do destino, todos validados (exceto host:porta liberado em teste). Resolve uma vez."""
    literal = _ip_literal(destino.host)
    if literal is not None:
        ips = [literal]
    else:
        if destino.host in NOMES_LOCAIS or destino.host.endswith(".localhost"):
            if not destino.liberado:
                raise _bloqueado()
        try:
            destino.host.encode("idna")
        except UnicodeError:
            raise _bloqueado("URL inválida.") from None
        resolvidos = _resolver_dns(destino.host, destino.porta)
        ips = []
        for _familia, _tipo, _proto, _nome, endereco in resolvidos:
            ip = ipaddress.ip_address(endereco[0].split("%")[0])
            if ip not in ips:
                ips.append(ip)
        if not ips:
            raise ErroHttp("dns")
    if not destino.liberado and any(ip_proibido(ip) for ip in ips):
        raise _bloqueado()
    return ips


# ---------------------------------------------------------------- resposta
def _decodificar_corpo(bruto, content_type):
    charset = "utf-8"
    achado = re.search(r"charset=([\w.-]+)", content_type or "", re.IGNORECASE)
    if achado:
        charset = achado.group(1)
    try:
        texto = bruto.decode(charset, errors="replace")
    except LookupError:
        texto = bruto.decode("utf-8", errors="replace")
    parece_json = "json" in (content_type or "").lower() or texto.lstrip()[:1] in ("{", "[")
    if parece_json:
        try:
            return json.loads(texto, parse_constant=_recusar_constante)
        except ValueError, RecursionError:
            pass
    return texto


def _recusar_constante(nome):
    raise ValueError(nome)


def _headers_da_resposta(resposta):
    juntos = {}
    for nome, valor in resposta.headers.multi_items():
        nome = nome.lower()
        juntos[nome] = f"{juntos[nome]}, {valor}" if nome in juntos else valor
    return juntos


def _ler_limitado(resposta, limite_tempo):
    """Lê o corpo (já descompactado) até 1 MB. Devolve (bytes, truncado)."""
    limite_corpo = _limite("LIMITE_RESPOSTA")
    pedacos, total = [], 0
    for pedaco in resposta.iter_bytes():
        if time.monotonic() > limite_tempo:
            raise ErroHttp("timeout")
        pedacos.append(pedaco)
        total += len(pedaco)
        if total > limite_corpo:
            return b"".join(pedacos)[:limite_corpo], True
    return b"".join(pedacos), False


def _erro_de_transporte(erro):
    if isinstance(erro, httpx.TimeoutException):
        return ErroHttp("timeout")
    causa = (
        f"{type(erro.__cause__).__name__} {erro}".lower() if erro.__cause__ else str(erro).lower()
    )
    if "ssl" in causa or "certificate" in causa or "tls" in causa:
        return ErroHttp("tls")
    return ErroHttp("conexao")


# ---------------------------------------------------------------- requisição
def _montar_url(url, query):
    if not query:
        return url
    extra = urlencode([(p["nome"], p["valor"]) for p in query], quote_via=quote)
    partes = urlsplit(url)
    base = url.split("#", 1)[0]
    juncao = "&" if partes.query else "?"
    return f"{base}{juncao}{extra}"


def _cabecalhos(headers, destino, corpo):
    final = {"user-agent": "ConstrutorWorkflows/1.0", "accept": "*/*"}
    tem_content_type = False
    for par in headers:
        nome = par["nome"].strip().lower()
        if nome in IGNORADOS_DO_USUARIO:
            continue
        tem_content_type = tem_content_type or nome == "content-type"
        final[nome] = par["valor"]
    if corpo and not tem_content_type:
        final["content-type"] = "application/json"
    final["host"] = destino.cabecalho_host
    return final


def _headers_em_bytes(cabecalhos):
    """Nomes em ASCII e valores em UTF-8 (o httpx assumiria ASCII para texto)."""
    try:
        return [(nome.encode("ascii"), valor.encode("utf-8")) for nome, valor in cabecalhos.items()]
    except UnicodeEncodeError:
        raise ErroHttp("conexao", "Cabeçalho inválido: use só letras ASCII no nome.") from None


def _ip_na_url(ip):
    return f"[{ip}]" if ip.version == 6 else str(ip)


def _enviar_uma_vez(cliente, metodo, destino, ips, cabecalhos, corpo, limite_tempo):
    """Conecta a um dos IPs validados (pin). Devolve a resposta em streaming."""
    ultimo = None
    for ip in ips:
        url = f"{destino.esquema}://{_ip_na_url(ip)}:{destino.porta}{destino.alvo}"
        try:
            requisicao = cliente.build_request(
                metodo,
                url,
                headers=_headers_em_bytes(cabecalhos),
                content=corpo.encode("utf-8") if corpo else None,
                extensions={"sni_hostname": destino.host},
            )
        except httpx.InvalidURL:
            raise _bloqueado("URL inválida.") from None
        try:
            return cliente.send(requisicao, stream=True)
        except httpx.InvalidURL:  # Location de redirect que o httpx nem consegue interpretar
            raise _bloqueado("Destino de redirecionamento inválido.") from None
        except httpx.ConnectError as erro:
            ultimo = _erro_de_transporte(erro)
        except httpx.HTTPError as erro:
            raise _erro_de_transporte(erro) from None
        if time.monotonic() > limite_tempo:
            raise ErroHttp("timeout")
    raise ultimo or ErroHttp("conexao")


def requisitar(*, metodo, url, headers=(), query=(), corpo="", prazo_s=None):
    """Faz a requisição com proteção SSRF. Devolve {status, headers, corpo, truncado}.

    Respostas 4xx/5xx NÃO levantam erro aqui (o executor grava a saída e mapeia a categoria com
    `categoria_de_status`). Levanta `ErroHttp` para bloqueio, DNS, conexão, TLS, timeout e
    redirect excessivo.
    """
    prazo_no = _limite("TIMEOUT_NO")
    prazo_s = prazo_no if prazo_s is None else min(prazo_s, prazo_no)
    limite_tempo = time.monotonic() + max(0.1, prazo_s)
    max_redirects = _limite("MAX_REDIRECTS")
    atual = _montar_url(url, query)
    metodo = metodo.upper()
    cabecalhos_do_usuario = [dict(par) for par in headers]
    conexao, leitura = _limite("TIMEOUT_CONEXAO"), _limite("TIMEOUT_LEITURA")
    conexao, leitura = min(conexao, prazo_s), min(leitura, prazo_s)  # nenhum passo passa do prazo
    timeout = httpx.Timeout(connect=conexao, read=leitura, write=leitura, pool=conexao)
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=timeout) as cliente:
        origem_inicial = None
        for salto in range(max_redirects + 1):
            destino = _Destino(atual)
            origem_inicial = origem_inicial or destino.origem
            if destino.origem != origem_inicial:  # não vaza credenciais para outra origem
                cabecalhos_do_usuario = [
                    p for p in cabecalhos_do_usuario if not sensivel(p["nome"])
                ]
            ips = _enderecos_validados(destino)
            resposta = _enviar_uma_vez(
                cliente,
                metodo,
                destino,
                ips,
                _cabecalhos(cabecalhos_do_usuario, destino, corpo),
                corpo,
                limite_tempo,
            )
            try:
                local = resposta.headers.get("location")
                if resposta.status_code in REDIRECTS and local:
                    if salto == max_redirects:
                        raise ErroHttp("redirect_excessivo")
                    atual = urljoin(atual.split("#", 1)[0], local)
                    if resposta.status_code in (301, 302, 303) and metodo not in ("GET", "HEAD"):
                        metodo, corpo = "GET", ""
                    continue
                try:
                    bruto, truncado = _ler_limitado(resposta, limite_tempo)
                except httpx.HTTPError as erro:
                    raise _erro_de_transporte(erro) from None
                return {
                    "status": resposta.status_code,
                    "headers": _headers_da_resposta(resposta),
                    "corpo": _decodificar_corpo(bruto, resposta.headers.get("content-type")),
                    "truncado": truncado,
                }
            finally:
                resposta.close()
    raise ErroHttp("redirect_excessivo")  # inalcançável; mantém o contrato
