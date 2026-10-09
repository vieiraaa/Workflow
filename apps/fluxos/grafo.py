"""Validação do grafo canônico v2 (docs/spec/grafo.yaml GRF-*, motor-v2.yaml MV2-02, MV2-12 L3/L4).

`validar(grafo)` não toca no banco e devolve `(erros_de_formato, pendencias)`:
- erros de formato (lista de {"campo", "mensagem"}): forma/tipo JSON errado; recusam o salvamento.
  Quando há algum, as pendências não são calculadas;
- pendências (lista de {"no", "campo", "mensagem"}): valor inválido com o tipo certo ou grafo
  incompleto; não impedem salvar rascunho, mas impedem ativar e executar. `no` é o id do nó
  (ou None para pendência global).
"""

import json
import math
import re
from urllib.parse import urlsplit

from . import catalogo
from .migracao import para_v2

VERSAO = 2
MAX_NOS = 200
MAX_ARESTAS = 400
MAX_NOTAS = 100
MAX_TEXTO_NOTA = 5000
MAX_TITULO = 80
MAX_URL = 2048
MAX_PARES = 30
MAX_VALOR_PAR = 4096
MAX_CORPO_BYTES = 100 * 1024
MAX_ITENS_FIXOS = 1000
METODOS = ("GET", "POST", "PUT", "PATCH", "DELETE")
METODOS_COM_CORPO = ("POST", "PUT", "PATCH")
MAX_PROFUNDIDADE = 16
CHAVES_RAIZ = {"versao", "nos", "arestas", "notas", "dados_fixos"}
CHAVES_NO = {
    "id",
    "tipo",
    "titulo",
    "posicao",
    "config",
    "desativado",
    "executar_uma_vez",
    "em_erro",
}
CHAVES_ARESTA = {"de", "saida", "para", "entrada"}
CHAVES_POSICAO = {"x", "y"}
CHAVES_NOTA = {"id", "texto", "posicao", "tamanho", "cor"}
CHAVES_TAMANHO = {"l", "a"}
CHAVES_PAR = {"nome", "valor"}
RE_ID = re.compile(r"[a-zA-Z0-9_-]{1,40}")
RE_ESPACO = re.compile(r"\s")


def _numero(valor):
    return isinstance(valor, int | float) and not isinstance(valor, bool)


def _erro(campo, mensagem):
    return {"campo": campo, "mensagem": mensagem}


def _pendencia(no, campo, mensagem):
    return {"no": no, "campo": campo, "mensagem": mensagem}


# ---------------------------------------------------------------- sanidade do JSON (GRF-09)
def _texto_valido(texto):
    if "\x00" in texto:
        return False
    try:
        texto.encode("utf-8")
    except UnicodeEncodeError:  # surrogate solto
        return False
    return True


def _sanidade(grafo):
    """Varredura iterativa (sem recursão): profundidade, números finitos e textos UTF-8 sem NUL."""
    erros = []
    pilha = [(grafo, 1)]
    achou_numero = achou_texto = False
    while pilha:
        valor, profundidade = pilha.pop()
        if profundidade > MAX_PROFUNDIDADE:
            return [
                _erro(
                    None,
                    f"O grafo tem aninhamento demais (máximo de {MAX_PROFUNDIDADE} níveis).",
                )
            ]
        if isinstance(valor, float) and not math.isfinite(valor):
            achou_numero = True
        elif isinstance(valor, str) and not _texto_valido(valor):
            achou_texto = True
        elif isinstance(valor, dict):
            for chave, filho in valor.items():
                if not _texto_valido(chave):
                    achou_texto = True
                pilha.append((filho, profundidade + 1))
        elif isinstance(valor, list):
            pilha.extend((filho, profundidade + 1) for filho in valor)
    if achou_numero:
        erros.append(_erro(None, "O grafo contém um número inválido (NaN ou infinito)."))
    if achou_texto:
        erros.append(
            _erro(None, "O grafo contém texto inválido (caractere nulo ou que não é UTF-8).")
        )
    return erros


def _chaves_desconhecidas(objeto, permitidas, onde):
    extras = sorted(str(k) for k in set(objeto) - permitidas)
    return [_erro(onde, f"Chave desconhecida: '{extra}'.") for extra in extras]


# ---------------------------------------------------------------- formato (GRF-02, MV2-02)
def _tipo_ok(valor, tipo):
    if tipo == "texto":
        return isinstance(valor, str)
    if tipo == "texto?":
        return valor is None or isinstance(valor, str)
    if tipo == "bool":
        return isinstance(valor, bool)
    if tipo == "int":
        return isinstance(valor, int) and not isinstance(valor, bool)
    if tipo == "numero":
        return _numero(valor)
    if tipo == "lista":
        return isinstance(valor, list)
    if tipo == "obj":
        return isinstance(valor, dict)
    if tipo == "obj?":
        return valor is None or isinstance(valor, dict)
    return False


def _formato_pares(config, campo, onde):
    erros = []
    pares = config.get(campo)
    if pares is None:
        return erros
    if not isinstance(pares, list):
        return [_erro(f"{onde}.{campo}", f"'{campo}' deve ser uma lista de pares nome/valor.")]
    for item in pares:
        if isinstance(item, dict) and (
            extras := _chaves_desconhecidas(item, CHAVES_PAR, f"{onde}.{campo}")
        ):
            erros += extras
            break
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


def _formato_config(tipo, config, onde):
    esquema = catalogo.ESQUEMA_CONFIG[tipo]
    erros = _chaves_desconhecidas(config, set(esquema), f"{onde}.config")
    for campo, esperado in esquema.items():
        if campo not in config:
            continue
        valor = config[campo]
        if not _tipo_ok(valor, esperado):
            erros.append(_erro(f"{onde}.config.{campo}", f"'{campo}' tem um tipo inválido."))
            continue
        permitidos = catalogo.ENUMS_CONFIG.get((tipo, campo))
        if permitidos and valor not in permitidos:
            erros.append(_erro(f"{onde}.config.{campo}", f"Valor inválido em '{campo}'."))
    if tipo == "http" and not erros:
        for campo in ("headers", "query"):
            erros += _formato_pares(config, campo, f"{onde}.config")
        corpo = config.get("corpo")
        if corpo is not None:
            erros += _chaves_desconhecidas(corpo, catalogo.CHAVES_CORPO, f"{onde}.config.corpo")
            if corpo.get("tipo", "nenhum") not in catalogo.TIPOS_DE_CORPO:
                erros.append(_erro(f"{onde}.config.corpo.tipo", "Tipo de corpo inválido."))
            conteudo = corpo.get("conteudo", "")
            if corpo.get("tipo") == "formulario":
                erros += _formato_pares(corpo, "conteudo", f"{onde}.config.corpo")
            elif not isinstance(conteudo, str):
                erros.append(
                    _erro(f"{onde}.config.corpo.conteudo", "O conteúdo do corpo deve ser um texto.")
                )
    return erros


def _formato_posicao(posicao, onde):
    if not (isinstance(posicao, dict) and _numero(posicao.get("x")) and _numero(posicao.get("y"))):
        return [_erro(onde, "A posição precisa de x e y numéricos.")]
    return _chaves_desconhecidas(posicao, CHAVES_POSICAO, onde)


def _formato_no(no, indice):
    onde = f"nos[{indice}]"
    if not isinstance(no, dict):
        return [_erro(onde, "Cada nó deve ser um objeto.")]
    erros = _chaves_desconhecidas(no, CHAVES_NO, onde)
    id_ = no.get("id")
    if not isinstance(id_, str) or not RE_ID.fullmatch(id_):
        erros.append(
            _erro(f"{onde}.id", "O id do nó deve ter de 1 a 40 letras, números, '-' ou '_'.")
        )
    tipo = no.get("tipo")
    if tipo not in catalogo.TIPOS_DE_NO:
        erros.append(_erro(f"{onde}.tipo", "Tipo de nó desconhecido."))
    if not isinstance(no.get("titulo"), str):
        erros.append(_erro(f"{onde}.titulo", "O título do nó deve ser um texto."))
    posicao_erros = _formato_posicao(no.get("posicao"), f"{onde}.posicao")
    erros += posicao_erros
    for campo in ("desativado", "executar_uma_vez"):
        if campo in no and not isinstance(no[campo], bool):
            erros.append(_erro(f"{onde}.{campo}", f"'{campo}' deve ser verdadeiro ou falso."))
    if no.get("em_erro", "parar") not in catalogo.EM_ERRO:
        erros.append(_erro(f"{onde}.em_erro", "Valor inválido em 'em_erro'."))
    config = no.get("config")
    if not isinstance(config, dict):
        erros.append(_erro(f"{onde}.config", "A configuração do nó deve ser um objeto."))
    elif tipo in catalogo.ESQUEMA_CONFIG:
        erros += _formato_config(tipo, config, onde)
    return erros


def _formato_aresta(aresta, indice):
    onde = f"arestas[{indice}]"
    if not (
        isinstance(aresta, dict)
        and isinstance(aresta.get("de"), str)
        and isinstance(aresta.get("para"), str)
    ):
        return [_erro(onde, "Cada aresta precisa de 'de' e 'para' em texto.")]
    erros = _chaves_desconhecidas(aresta, CHAVES_ARESTA, onde)
    for campo in ("saida", "entrada"):
        valor = aresta.get(campo, 0)
        if not (isinstance(valor, int) and not isinstance(valor, bool)) or valor < 0:
            erros.append(_erro(f"{onde}.{campo}", f"'{campo}' deve ser um inteiro a partir de 0."))
    return erros


def _formato_nota(nota, indice):
    onde = f"notas[{indice}]"
    if not isinstance(nota, dict):
        return [_erro(onde, "Cada nota deve ser um objeto.")]
    erros = _chaves_desconhecidas(nota, CHAVES_NOTA, onde)
    if not isinstance(nota.get("id"), str) or not RE_ID.fullmatch(nota.get("id", "")):
        erros.append(
            _erro(f"{onde}.id", "O id da nota deve ter de 1 a 40 letras, números, '-' ou '_'.")
        )
    texto = nota.get("texto", "")
    if not isinstance(texto, str):
        erros.append(_erro(f"{onde}.texto", "O texto da nota deve ser um texto."))
    elif len(texto) > MAX_TEXTO_NOTA:
        erros.append(
            _erro(f"{onde}.texto", f"A nota pode ter no máximo {MAX_TEXTO_NOTA} caracteres.")
        )
    erros += _formato_posicao(nota.get("posicao"), f"{onde}.posicao")
    tamanho = nota.get("tamanho")
    if tamanho is not None:
        if not (
            isinstance(tamanho, dict) and _numero(tamanho.get("l")) and _numero(tamanho.get("a"))
        ):
            erros.append(_erro(f"{onde}.tamanho", "O tamanho precisa de l e a numéricos."))
        else:
            erros += _chaves_desconhecidas(tamanho, CHAVES_TAMANHO, f"{onde}.tamanho")
    if nota.get("cor", "amarela") not in catalogo.CORES_NOTA:
        erros.append(_erro(f"{onde}.cor", "Cor de nota inválida."))
    return erros


def _formato_dados_fixos(dados_fixos):
    erros = []
    for chave, itens in dados_fixos.items():
        onde = f"dados_fixos.{chave}"
        if not isinstance(itens, list):
            erros.append(_erro(onde, "Os dados fixos de um nó devem ser uma lista de itens."))
        elif len(itens) > MAX_ITENS_FIXOS:
            erros.append(_erro(onde, f"Use no máximo {MAX_ITENS_FIXOS} itens fixos por nó."))
        elif not all(
            isinstance(i, dict) and set(i) == {"json"} and isinstance(i["json"], dict)
            for i in itens
        ):
            erros.append(_erro(onde, 'Cada item fixo deve ser {"json": {...}}.'))
    return erros


def _formato(grafo):
    if not isinstance(grafo, dict):
        return [_erro(None, "O grafo deve ser um objeto JSON.")]
    if erros := _sanidade(grafo):
        return erros
    erros = _chaves_desconhecidas(grafo, CHAVES_RAIZ, None)
    if grafo.get("versao") != VERSAO or isinstance(grafo.get("versao"), bool):
        erros.append(_erro("versao", "Versão do grafo não suportada."))
    nos, arestas = grafo.get("nos"), grafo.get("arestas")
    notas, dados_fixos = grafo.get("notas", []), grafo.get("dados_fixos", {})
    if not isinstance(nos, list):
        erros.append(_erro("nos", "'nos' deve ser uma lista."))
    if not isinstance(arestas, list):
        erros.append(_erro("arestas", "'arestas' deve ser uma lista."))
    if not isinstance(notas, list):
        erros.append(_erro("notas", "'notas' deve ser uma lista."))
    if not isinstance(dados_fixos, dict):
        erros.append(_erro("dados_fixos", "'dados_fixos' deve ser um objeto."))
    if erros:
        return erros
    for campo, lista, limite in (
        ("nos", nos, MAX_NOS),
        ("arestas", arestas, MAX_ARESTAS),
        ("notas", notas, MAX_NOTAS),
    ):
        if len(lista) > limite:
            return [_erro(campo, f"Use no máximo {limite} em '{campo}'.")]
    ids = set()
    for indice, no in enumerate(nos):
        erros += _formato_no(no, indice)
        id_ = no.get("id") if isinstance(no, dict) else None
        if isinstance(id_, str):
            if id_ in ids:
                erros.append(_erro(f"nos[{indice}].id", "Id de nó repetido."))
            ids.add(id_)
    for indice, aresta in enumerate(arestas):
        erros += _formato_aresta(aresta, indice)
        if (
            isinstance(aresta, dict)
            and isinstance(aresta.get("de"), str)
            and isinstance(aresta.get("para"), str)
            and (aresta["de"] not in ids or aresta["para"] not in ids)
        ):
            erros.append(_erro(f"arestas[{indice}]", "A aresta aponta para um nó que não existe."))
    ids_notas = set()
    for indice, nota in enumerate(notas):
        erros += _formato_nota(nota, indice)
        id_ = nota.get("id") if isinstance(nota, dict) else None
        if isinstance(id_, str):
            if id_ in ids_notas:
                erros.append(_erro(f"notas[{indice}].id", "Id de nota repetido."))
            ids_notas.add(id_)
    erros += _formato_dados_fixos(dados_fixos)
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


def _corpo(config):
    corpo = config.get("corpo")
    return corpo if isinstance(corpo, dict) else {"tipo": "nenhum", "conteudo": ""}


def _pendencias_corpo(no_id, metodo, corpo):
    tipo, conteudo = corpo.get("tipo", "nenhum"), corpo.get("conteudo", "")
    if tipo == "formulario":
        if not conteudo:
            return []
        if metodo not in METODOS_COM_CORPO:
            return [_pendencia(no_id, "corpo", "Este método não aceita corpo; deixe-o vazio.")]
        return _pendencias_pares(no_id, {"conteudo": conteudo}, "conteudo", "campos do formulário")
    if tipo == "nenhum" or not conteudo.strip():
        return []
    if metodo not in METODOS_COM_CORPO:
        return [_pendencia(no_id, "corpo", "Este método não aceita corpo; deixe-o vazio.")]
    if len(conteudo.encode("utf-8")) > MAX_CORPO_BYTES:
        return [_pendencia(no_id, "corpo", "O corpo pode ter no máximo 100 KB.")]
    if tipo == "json" and not conteudo.lstrip().startswith("="):
        try:
            json.loads(conteudo)
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
    pendencias += _pendencias_corpo(no_id, metodo, _corpo(config))
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


def _alcancaveis(inicios, saidas):
    visto, pilha = set(inicios), list(inicios)
    while pilha:
        for vizinho in saidas.get(pilha.pop(), ()):
            if vizinho not in visto:
                visto.add(vizinho)
                pilha.append(vizinho)
    return visto


def arestas_de_retorno(nos, arestas):
    """Índices das arestas de retorno de laço (NOV-04): aresta cujo destino é um Repetir em lotes
    R e cuja origem é alcançável a partir da saída 0 ("loop") de R. Só aceita estrutura válida."""
    por_id = {n["id"]: n for n in nos}
    retornos = set()
    for repetir in (n["id"] for n in nos if n["tipo"] == "repetir_em_lotes"):
        saidas = {}
        for aresta in arestas:
            if aresta["de"] in por_id and aresta["para"] in por_id:
                saidas.setdefault(aresta["de"], []).append(aresta["para"])
        iniciais = [
            a["para"]
            for a in arestas
            if a["de"] == repetir and a.get("saida", 0) == 0 and a["para"] in por_id
        ]
        dentro = _alcancaveis(iniciais, saidas)
        for indice, aresta in enumerate(arestas):
            if aresta["para"] == repetir and aresta["de"] in dentro:
                retornos.add(indice)
    return retornos


def _pendencias_arestas(nos_por_id, arestas):
    pendencias = []
    for aresta in arestas:
        origem, destino = nos_por_id.get(aresta["de"]), nos_por_id.get(aresta["para"])
        if origem is None or destino is None:
            pendencias.append(
                _pendencia(None, None, "Uma conexão aponta para um nó que não existe.")
            )
            continue
        if origem["tipo"] == "saida":
            pendencias.append(
                _pendencia(origem["id"], None, "A Saída não pode ter ligações de saída.")
            )
        elif aresta.get("saida", 0) >= catalogo.n_saidas(origem):
            pendencias.append(
                _pendencia(origem["id"], None, "Ligação para uma saída que este nó não tem.")
            )
        if destino["tipo"] == "gatilho":
            pendencias.append(_pendencia(destino["id"], None, "O gatilho não pode ter entrada."))
        elif aresta.get("entrada", 0) >= catalogo.n_entradas(destino):
            pendencias.append(
                _pendencia(destino["id"], None, "Uma conexão chega a uma alça que este nó não tem.")
            )
    return pendencias


def _pendencias_estrutura(grafo):
    nos, arestas = grafo["nos"], grafo["arestas"]
    pendencias = []
    por_id = {n["id"]: n for n in nos}
    pendencias += _pendencias_arestas(por_id, arestas)
    validas = [a for a in arestas if a["de"] in por_id and a["para"] in por_id]
    gatilhos = [n["id"] for n in nos if n["tipo"] == "gatilho"]
    if len(gatilhos) != 1:
        pendencias.append(_pendencia(None, None, "O fluxo precisa de exatamente um gatilho."))
    titulos = {}
    for no in nos:
        titulos.setdefault(no["titulo"].strip(), []).append(no["id"])
    for titulo, ids in titulos.items():
        if titulo and len(ids) > 1:
            pendencias += [
                _pendencia(id_, "titulo", f'Já existe um nó com o título "{titulo}".')
                for id_ in ids[1:]
            ]
    for chave in grafo.get("dados_fixos", {}):
        if chave not in por_id:
            pendencias.append(
                _pendencia(None, "dados_fixos", "Dados fixos de um nó que não existe.")
            )
    retornos = arestas_de_retorno(nos, validas)
    por_repetir = {}
    for indice in retornos:
        por_repetir.setdefault(validas[indice]["para"], []).append(indice)
    for repetir, indices in por_repetir.items():
        if len(indices) > 1:
            pendencias.append(
                _pendencia(repetir, None, "Repetir em lotes aceita uma única conexão de retorno.")
            )
    saidas = {i: [] for i in por_id}
    for indice, aresta in enumerate(validas):
        if indice not in retornos:
            saidas[aresta["de"]].append(aresta["para"])
    if gatilhos:
        todas = {i: [] for i in por_id}
        for aresta in validas:
            todas[aresta["de"]].append(aresta["para"])
        alcancados = _alcancaveis(gatilhos, todas)
        pendencias += [
            _pendencia(id_, None, "Este nó não está ligado ao gatilho.")
            for id_ in por_id
            if id_ not in alcancados
        ]
    no_do_ciclo = _tem_ciclo(list(por_id), saidas)
    if no_do_ciclo is not None:
        pendencias.append(_pendencia(no_do_ciclo, None, "O fluxo tem um ciclo."))
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
    return pendencias + _pendencias_estrutura(grafo)


def normalizar(grafo):
    """Grafo v2 completo (converte v1 e preenche padrões); só chame com `validar(...)` sem erros."""
    grafo = para_v2(grafo)
    novo = json.loads(json.dumps(grafo))
    novo.setdefault("notas", [])
    novo.setdefault("dados_fixos", {})
    for no in novo["nos"]:
        no.setdefault("desativado", False)
        no.setdefault("executar_uma_vez", False)
        no.setdefault("em_erro", "parar")
    for aresta in novo["arestas"]:
        aresta.setdefault("saida", 0)
        aresta.setdefault("entrada", 0)
    for nota in novo["notas"]:
        nota.setdefault("texto", "")
        nota.setdefault("cor", "amarela")
    return novo


def validar(grafo):
    """Valida o grafo (v1 é convertido antes). Devolve (erros_de_formato, pendencias)."""
    if isinstance(grafo, dict) and (erros := _sanidade(grafo)):
        return erros, []  # antes de copiar/migrar: aninhamento extremo não pode estourar a pilha
    grafo = para_v2(grafo)
    erros = _formato(grafo)
    if erros:
        return erros, []
    return [], _pendencias(normalizar(grafo))
