"""Validação do grafo canônico (docs/spec/grafo.yaml: GRF-02, GRF-03, GRF-04, GRF-08).

`validar(grafo)` não toca no banco e devolve `(erros_de_formato, pendencias)`:
- erros de formato (lista de {"campo", "mensagem"}): forma/tipo JSON errado; recusam o salvamento.
  Quando há algum, as pendências não são calculadas;
- pendências (lista de {"no", "campo", "mensagem"}): valor inválido com o tipo certo ou grafo
  incompleto; não impedem salvar rascunho, mas impedem ativar e executar. `no` é o id do nó
  (ou None para pendência global).
"""

import json
import re
from urllib.parse import urlsplit

VERSAO = 1
MAX_NOS = 50
MAX_TITULO = 80
MAX_URL = 2048
MAX_PARES = 30
MAX_VALOR_PAR = 4096
MAX_CORPO_BYTES = 100 * 1024
TIPOS_DE_NO = ("gatilho", "http", "saida")
METODOS = ("GET", "POST", "PUT", "PATCH", "DELETE")
METODOS_COM_CORPO = ("POST", "PUT", "PATCH")
RE_ID = re.compile(r"[a-zA-Z0-9_-]{1,40}")
RE_ESPACO = re.compile(r"\s")


def _numero(valor):
    return isinstance(valor, int | float) and not isinstance(valor, bool)


def _erro(campo, mensagem):
    return {"campo": campo, "mensagem": mensagem}


def _pendencia(no, campo, mensagem):
    return {"no": no, "campo": campo, "mensagem": mensagem}


# ---------------------------------------------------------------- formato (GRF-02)
def _formato_pares(config, campo, onde):
    erros = []
    pares = config.get(campo)
    if pares is None:
        return erros
    if not isinstance(pares, list):
        return [_erro(f"{onde}.{campo}", f"'{campo}' deve ser uma lista de pares nome/valor.")]
    for item in pares:
        if not (
            isinstance(item, dict)
            and isinstance(item.get("nome"), str)
            and isinstance(item.get("valor"), str)
        ):
            erros.append(
                _erro(
                    f"{onde}.{campo}", f"Cada item de '{campo}' precisa de nome e valor em texto."
                )
            )
            break
    return erros


def _formato_no(no, indice):
    onde = f"nos[{indice}]"
    if not isinstance(no, dict):
        return [_erro(onde, "Cada nó deve ser um objeto.")]
    erros = []
    id_ = no.get("id")
    if not isinstance(id_, str) or not RE_ID.fullmatch(id_):
        erros.append(
            _erro(f"{onde}.id", "O id do nó deve ter de 1 a 40 letras, números, '-' ou '_'.")
        )
    if no.get("tipo") not in TIPOS_DE_NO:
        erros.append(_erro(f"{onde}.tipo", "Tipo de nó desconhecido."))
    if not isinstance(no.get("titulo"), str):
        erros.append(_erro(f"{onde}.titulo", "O título do nó deve ser um texto."))
    posicao = no.get("posicao")
    if not (isinstance(posicao, dict) and _numero(posicao.get("x")) and _numero(posicao.get("y"))):
        erros.append(_erro(f"{onde}.posicao", "A posição do nó precisa de x e y numéricos."))
    config = no.get("config")
    if not isinstance(config, dict):
        erros.append(_erro(f"{onde}.config", "A configuração do nó deve ser um objeto."))
    elif no.get("tipo") == "http":
        for campo in ("metodo", "url", "corpo"):
            if campo in config and not isinstance(config[campo], str):
                erros.append(_erro(f"{onde}.config.{campo}", f"'{campo}' deve ser um texto."))
        for campo in ("headers", "query"):
            erros += _formato_pares(config, campo, f"{onde}.config")
    return erros


def _formato(grafo):
    if not isinstance(grafo, dict):
        return [_erro(None, "O grafo deve ser um objeto JSON.")]
    erros = []
    if grafo.get("versao") != VERSAO or isinstance(grafo.get("versao"), bool):
        erros.append(_erro("versao", "Versão do grafo não suportada."))
    nos, arestas = grafo.get("nos"), grafo.get("arestas")
    if not isinstance(nos, list):
        erros.append(_erro("nos", "'nos' deve ser uma lista."))
    if not isinstance(arestas, list):
        erros.append(_erro("arestas", "'arestas' deve ser uma lista."))
    if erros:
        return erros
    if len(nos) > MAX_NOS:
        return [_erro("nos", f"Use no máximo {MAX_NOS} nós.")]
    ids = set()
    for indice, no in enumerate(nos):
        erros += _formato_no(no, indice)
        id_ = no.get("id") if isinstance(no, dict) else None
        if isinstance(id_, str):
            if id_ in ids:
                erros.append(_erro(f"nos[{indice}].id", "Id de nó repetido."))
            ids.add(id_)
    for indice, aresta in enumerate(arestas):
        onde = f"arestas[{indice}]"
        if not (
            isinstance(aresta, dict)
            and isinstance(aresta.get("de"), str)
            and isinstance(aresta.get("para"), str)
        ):
            erros.append(_erro(onde, "Cada aresta precisa de 'de' e 'para' em texto."))
        elif aresta["de"] not in ids or aresta["para"] not in ids:
            erros.append(_erro(onde, "A aresta aponta para um nó que não existe."))
    return erros


# ---------------------------------------------------------------- pendências (GRF-03, GRF-04)
def _pendencias_pares(no_id, config, campo, rotulo):
    pendencias = []
    pares = config.get(campo) or []
    if len(pares) > MAX_PARES:
        pendencias.append(_pendencia(no_id, campo, f"Use no máximo {MAX_PARES} itens em {rotulo}."))
    for par in pares:
        nome, valor = par["nome"], par["valor"]
        if not nome or RE_ESPACO.search(nome):
            pendencias.append(
                _pendencia(no_id, campo, f"Nome inválido em {rotulo}: informe um nome sem espaços.")
            )
        elif len(valor) > MAX_VALOR_PAR or "\r" in valor or "\n" in valor:
            pendencias.append(
                _pendencia(
                    no_id,
                    campo,
                    f"Valor de {rotulo} ({nome}) inválido: "
                    f"máx. {MAX_VALOR_PAR} caracteres, sem quebra de linha.",
                )
            )
    return pendencias


def _pendencias_url(no_id, url):
    if not url.strip():
        return [_pendencia(no_id, "url", "Informe a URL.")]
    if len(url) > MAX_URL:
        return [_pendencia(no_id, "url", f"A URL pode ter no máximo {MAX_URL} caracteres.")]
    try:
        partes = urlsplit(url)
        host = partes.netloc.rpartition("@")[2]
    except ValueError:
        return [_pendencia(no_id, "url", "URL inválida.")]
    if partes.scheme.lower() not in ("http", "https"):
        return [_pendencia(no_id, "url", "A URL deve começar com http:// ou https://.")]
    if not host:
        return [_pendencia(no_id, "url", "A URL precisa de um endereço (host).")]
    return []


def _pendencias_corpo(no_id, metodo, corpo):
    if not corpo.strip():
        return []
    if metodo not in METODOS_COM_CORPO:
        return [_pendencia(no_id, "corpo", "Este método não aceita corpo; deixe-o vazio.")]
    if len(corpo.encode("utf-8")) > MAX_CORPO_BYTES:
        return [_pendencia(no_id, "corpo", "O corpo pode ter no máximo 100 KB.")]
    try:
        json.loads(corpo)
    except ValueError:
        return [_pendencia(no_id, "corpo", "O corpo precisa ser um JSON válido.")]
    return []


def _pendencias_http(no):
    config, no_id = no["config"], no["id"]
    metodo = config.get("metodo", "")
    pendencias = []
    if metodo not in METODOS:
        pendencias.append(
            _pendencia(no_id, "metodo", "Escolha um método: GET, POST, PUT, PATCH ou DELETE.")
        )
    pendencias += _pendencias_url(no_id, config.get("url", ""))
    pendencias += _pendencias_pares(no_id, config, "headers", "cabeçalhos")
    pendencias += _pendencias_pares(no_id, config, "query", "parâmetros de consulta")
    pendencias += _pendencias_corpo(no_id, metodo, config.get("corpo", ""))
    return pendencias


def _tem_ciclo(ids, saidas):
    """Devolve o id de um nó que participa de um ciclo, ou None (DFS iterativa com cores)."""
    cor = dict.fromkeys(ids, 0)  # 0 branco, 1 cinza, 2 preto
    for inicio in ids:
        if cor[inicio]:
            continue
        pilha = [(inicio, iter(saidas[inicio]))]
        cor[inicio] = 1
        while pilha:
            no, vizinhos = pilha[-1]
            for vizinho in vizinhos:
                if cor[vizinho] == 1:
                    return vizinho
                if cor[vizinho] == 0:
                    cor[vizinho] = 1
                    pilha.append((vizinho, iter(saidas[vizinho])))
                    break
            else:
                cor[no] = 2
                pilha.pop()
    return None


def _pendencias_estrutura(nos, arestas):
    pendencias = []
    ids = [n["id"] for n in nos]
    saidas = {i: [] for i in ids}
    entradas = {i: 0 for i in ids}
    for aresta in arestas:
        saidas[aresta["de"]].append(aresta["para"])
        entradas[aresta["para"]] += 1
    gatilhos = [n["id"] for n in nos if n["tipo"] == "gatilho"]
    if len(gatilhos) != 1:
        pendencias.append(_pendencia(None, None, "O fluxo precisa ter exatamente um gatilho."))
    if not any(n["tipo"] == "saida" for n in nos):
        pendencias.append(_pendencia(None, None, "O fluxo precisa de pelo menos uma saída."))
    for no in nos:
        id_, tipo = no["id"], no["tipo"]
        if tipo == "gatilho" and entradas[id_]:
            pendencias.append(
                _pendencia(id_, None, "O gatilho não pode receber conexões de entrada.")
            )
        if tipo == "saida" and saidas[id_]:
            pendencias.append(_pendencia(id_, None, "A saída não pode ter conexões de saída."))
        if len(saidas[id_]) > 1:
            pendencias.append(
                _pendencia(
                    id_, None, "Este nó tem mais de uma conexão de saída (não há paralelismo)."
                )
            )
        if entradas[id_] > 1:
            pendencias.append(
                _pendencia(
                    id_, None, "Este nó tem mais de uma conexão de entrada (não há paralelismo)."
                )
            )
    if gatilhos:
        alcancados, pilha = set(gatilhos), list(gatilhos)
        while pilha:
            for vizinho in saidas[pilha.pop()]:
                if vizinho not in alcancados:
                    alcancados.add(vizinho)
                    pilha.append(vizinho)
        for id_ in ids:
            if id_ not in alcancados:
                pendencias.append(_pendencia(id_, None, "Nó solto: não está ligado ao gatilho."))
    no_do_ciclo = _tem_ciclo(ids, saidas)
    if no_do_ciclo is not None:
        pendencias.append(
            _pendencia(no_do_ciclo, None, "O fluxo tem um ciclo; remova a conexão que volta.")
        )
    return pendencias


def _pendencias(grafo):
    pendencias = []
    for no in grafo["nos"]:
        titulo = no["titulo"]
        if not titulo.strip():
            pendencias.append(_pendencia(no["id"], "titulo", "Informe um título para o nó."))
        elif len(titulo) > MAX_TITULO:
            pendencias.append(
                _pendencia(
                    no["id"], "titulo", f"O título pode ter no máximo {MAX_TITULO} caracteres."
                )
            )
        if no["tipo"] == "http":
            pendencias += _pendencias_http(no)
    return pendencias + _pendencias_estrutura(grafo["nos"], grafo["arestas"])


def validar(grafo):
    """Valida o grafo canônico. Devolve (erros_de_formato, pendencias)."""
    erros = _formato(grafo)
    if erros:
        return erros, []
    return [], _pendencias(grafo)
