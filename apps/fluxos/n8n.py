"""Importação do formato n8n (IMP-03, MV2-20/21, SEG-19): `{nodes, connections}` → grafo v2.

Função pura (sem banco). O JSON é dado não confiável: só campos conhecidos são lidos, ids são
novos, e o que o mapa não conhece vai para `ajustes` (nunca vira erro).
"""

import json
import secrets

from . import importacao as imp

PREFIXO = "n8n-nodes-base."
MAX_TITULO = 80
MAX_NOTA = 5000

TIPOS = {
    "manualTrigger": "gatilho",
    "httpRequest": "http",
    "code": "codigo",
    "set": "editar_campos",
    "filter": "filtrar",
    "if": "se",
    "switch": "escolher",
    "merge": "juntar",
    "sort": "ordenar",
    "limit": "limitar",
    "removeDuplicates": "remover_duplicados",
    "splitOut": "separar_lista",
    "aggregate": "agregar",
    "summarize": "resumir",
    "dateTime": "data_hora",
    "splitInBatches": "repetir_em_lotes",
    "stopAndError": "parar_com_erro",
    "noOp": "sem_operacao",
}
OPERADORES = {
    "equals": "igual", "notEquals": "diferente", "gt": "maior", "gte": "maior_igual", "lt": "menor",
    "lte": "menor_igual", "contains": "contem", "notContains": "nao_contem",
    "startsWith": "comeca_com", "endsWith": "termina_com", "empty": "vazio",
    "notEmpty": "nao_vazio", "regex": "regex", "exists": "existe", "notExists": "nao_existe",
}  # fmt: skip
TIPOS_COND = {
    "string": "texto", "number": "numero", "dateTime": "data", "boolean": "booleano",
    "array": "lista", "object": "objeto",
}  # fmt: skip
TIPOS_CAMPO = dict(TIPOS_COND)
TIPOS_CAMPO.pop("dateTime")
OPS_RESUMIR = {
    "count": "contar", "countUnique": "contar_unicos", "sum": "somar", "average": "media",
    "min": "min", "max": "max", "concatenate": "concatenar",
}  # fmt: skip
OPS_DATA = {
    "getCurrentDate": "agora", "addToDate": "somar", "subtractFromDate": "subtrair",
    "formatDate": "formatar", "getTimeBetweenDates": "diferenca", "roundDate": "inicio_de",
}  # fmt: skip
UNIDADES = {
    "days": "dias",
    "hours": "horas",
    "minutes": "minutos",
    "weeks": "semanas",
    "months": "meses",
}
UNIDADES_INICIO = {"day": "dia", "week": "semana", "month": "mes", "hour": "hora"}
CORES = {1: "amarela", 2: "cinza", 3: "cinza", 4: "verde", 5: "azul", 6: "azul", 7: "cinza"}
JUNCAO = {
    "keepMatches": "dentro", "keepEverything": "externa", "enrichInput1": "esquerda",
    "enrichInput2": "direita",
}  # fmt: skip
COMUNS = {"options"}  # chaves de parameters aceitas em silêncio em qualquer tipo


def _id(prefixo):
    return f"{prefixo}_{secrets.token_hex(6)}"


def _txt(valor, padrao=""):
    if isinstance(valor, str):
        return valor
    if valor is None or isinstance(valor, dict | list):
        return padrao
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor)


def _int(valor, padrao, minimo=None, maximo=None):
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        try:
            valor = int(str(valor).strip())
        except ValueError:
            valor = padrao
    valor = int(valor)
    if minimo is not None:
        valor = max(minimo, valor)
    if maximo is not None:
        valor = min(maximo, valor)
    return valor


def _dict(valor):
    return valor if isinstance(valor, dict) else {}


def _lista(valor):
    return [x for x in valor if isinstance(x, dict)] if isinstance(valor, list) else []


def _lista_csv(valor):
    if isinstance(valor, list):
        valor = ",".join(str(v) for v in valor)
    return [p.strip() for p in _txt(valor).split(",") if p.strip()]


# ---------------------------------------------------------------- mapeadores por tipo
# Cada um recebe (params, ajustes) e devolve (config, chaves_conhecidas). `ajustes` é uma lista de
# mensagens para o relatório.
def _pares(params, flag, chave):
    if params.get(flag) is not True:
        return []
    return [
        {"nome": _txt(p.get("name")), "valor": _txt(p.get("value"))}
        for p in _lista(_dict(params.get(chave)).get("parameters"))
    ]


def _paginacao(opcoes, query, headers, ajustes):
    bruto = _dict(_dict(opcoes.get("pagination")).get("pagination"))
    if not bruto:
        return None
    modo = bruto.get("paginationMode", "updateAParameterInEachRequest")
    parametros = _lista(_dict(bruto.get("parameters")).get("parameters"))
    if len(parametros) > 1:
        ajustes.append("Paginação com vários parâmetros: só o primeiro foi importado.")
    primeiro = parametros[0] if parametros else {}
    nome, valor = _txt(primeiro.get("name")), _txt(primeiro.get("value"))
    if modo == "responseContainsNextURL":
        pag = {"modo": "proxima_url", "url": _txt(bruto.get("nextURL"))}
    else:
        tipo = primeiro.get("type")
        if tipo == "body":
            onde = "corpo"
        elif tipo == "headers" or (tipo is None and nome in {h["nome"] for h in headers}):
            onde = "header"
        else:
            onde = "query"
        pag = {"modo": "atualizar_parametro", "onde": onde, "nome": nome, "valor": valor}
    quando = bruto.get("paginationCompleteWhen", "responseIsEmpty")
    if quando == "other":
        pag.update(parar_quando="expressao", expressao=_txt(bruto.get("completeExpression")))
    elif quando == "receiveSpecificStatusCodes":
        codigos = [int(c) for c in _lista_csv(bruto.get("statusCodesWhenComplete")) if c.isdigit()]
        pag.update(parar_quando="status", codigos=codigos)
    else:
        pag["parar_quando"] = "resposta_vazia"
    if bruto.get("limitPagesFetched") is True:
        pag["limite_paginas"] = _int(bruto.get("maxRequests"), 10, 1, 100)
    else:
        pag["limite_paginas"] = 100
    if "requestInterval" in bruto:
        pag["intervalo_ms"] = _int(bruto.get("requestInterval"), 0, 0, 5000)
    return pag


def _corpo(params, ajustes):
    if params.get("sendBody") is not True:
        return {"tipo": "nenhum", "conteudo": ""}
    tipo = params.get("contentType", "json")
    if tipo == "json" and params.get("specifyBody", "keypair") == "json":
        return {"tipo": "json", "conteudo": _txt(params.get("jsonBody"))}
    pares = _lista(_dict(params.get("bodyParameters")).get("parameters"))
    pares = [{"nome": _txt(p.get("name")), "valor": _txt(p.get("value"))} for p in pares]
    if tipo == "json":
        return {"tipo": "json", "conteudo": json.dumps({p["nome"]: p["valor"] for p in pares})}
    if tipo in ("form-urlencoded", "multipart-form-data"):
        if tipo == "multipart-form-data":
            ajustes.append("Corpo multipart foi importado como formulário comum.")
        return {"tipo": "formulario", "conteudo": pares}
    if tipo == "raw":
        return {"tipo": "texto", "conteudo": _txt(params.get("body"))}
    ajustes.append(f"Tipo de corpo '{_txt(tipo)}' sem equivalente: corpo vazio.")
    return {"tipo": "nenhum", "conteudo": ""}


def _http(params, ajustes):
    query = _pares(params, "sendQuery", "queryParameters")
    headers = _pares(params, "sendHeaders", "headerParameters")
    opcoes = _dict(params.get("options"))
    resposta = _dict(_dict(opcoes.get("response")).get("response"))
    formato = resposta.get("responseFormat", "autodetect")
    if formato not in ("json", "text", "autodetect"):
        ajustes.append(f"Formato de resposta '{_txt(formato)}' sem equivalente: automático.")
    for chave in set(opcoes) - {"response", "pagination"}:
        ajustes.append(f"Opção '{chave}' do HTTP sem equivalente.")
    if params.get("authentication", "none") != "none":
        ajustes.append("Autenticação não importada: configure uma credencial no nó.")
    metodo = _txt(params.get("method"), "GET").upper()
    config = {
        "metodo": metodo if metodo in ("GET", "POST", "PUT", "PATCH", "DELETE") else "GET",
        "url": _txt(params.get("url")),
        "query": query,
        "headers": headers,
        "corpo": _corpo(params, ajustes),
        "credencial": None,
        "resposta": {"json": "json", "text": "texto"}.get(formato, "automatica"),
        "resposta_completa": resposta.get("fullResponse") is True,
        "paginacao": _paginacao(opcoes, query, headers, ajustes),
    }
    conhecidas = {
        "method", "url", "sendQuery", "queryParameters", "sendHeaders", "headerParameters",
        "sendBody", "specifyBody", "jsonBody", "bodyParameters", "contentType", "body",
        "authentication", "genericAuthType", "nodeCredentialType",
    }  # fmt: skip
    return config, conhecidas


def _codigo(params, ajustes):
    if params.get("language") in ("python", "pythonNative"):
        ajustes.append("Código em Python não é suportado: só JavaScript.")
    modo = (
        "uma_vez_por_item" if params.get("mode") == "runOnceForEachItem" else "uma_vez_para_todos"
    )
    return {"modo": modo, "codigo": _txt(params.get("jsCode"))}, {"mode", "jsCode", "language"}


def _direita(valor, tipo):
    if tipo == "numero" and isinstance(valor, str):
        try:
            numero = float(valor)
        except ValueError:
            return valor
        return int(numero) if numero.is_integer() else numero
    if tipo == "texto" and not isinstance(valor, str):
        return _txt(valor)
    return valor


def _condicoes(bloco, ajustes):
    """`{conditions: [...], combinator}` → (condicoes, combinar)."""
    bloco = _dict(bloco)
    saida = []
    for c in _lista(bloco.get("conditions")):
        operador = _dict(c.get("operator"))
        operacao = OPERADORES.get(operador.get("operation"))
        if operacao is None:
            ajustes.append(f"Operador '{_txt(operador.get('operation'))}' sem equivalente: igual.")
            operacao = "igual"
        tipo = TIPOS_COND.get(operador.get("type"), "texto")
        item = {"esquerda": _txt(c.get("leftValue")), "operador": operacao, "tipo": tipo}
        if "rightValue" in c:
            item["direita"] = _direita(c["rightValue"], tipo)
        saida.append(item)
    return saida, ("ou" if bloco.get("combinator") == "or" else "e")


def _set(params, ajustes):
    if params.get("mode") == "raw":
        config = {"modo": "json", "json": _txt(params.get("jsonOutput"))}
    else:
        campos = []
        for c in _lista(_dict(params.get("assignments")).get("assignments")):
            tipo = TIPOS_CAMPO.get(c.get("type"), "texto")
            valor = c.get("value")
            campos.append(
                {
                    "nome": _txt(c.get("name")),
                    "valor": valor if isinstance(valor, str | int | float | bool) else _txt(valor),
                    "tipo": tipo,
                }
            )
        config = {"modo": "manual", "campos": campos}
    config["incluir_outros"] = params.get("includeOtherFields") is True
    return config, {"mode", "jsonOutput", "assignments", "includeOtherFields"}


def _filtro(params, ajustes):
    condicoes, combinar = _condicoes(params.get("conditions"), ajustes)
    return {"condicoes": condicoes, "combinar": combinar}, {"conditions"}


def _escolher(params, ajustes):
    regras = []
    for i, regra in enumerate(_lista(_dict(params.get("rules")).get("values"))):
        condicoes, combinar = _condicoes(regra.get("conditions"), ajustes)
        rotulo = _txt(regra.get("outputKey")) or f"Saída {i}"
        regras.append({"condicoes": condicoes, "combinar": combinar, "rotulo": rotulo})
    extra = _dict(params.get("options")).get("fallbackOutput") == "extra"
    return {"regras": regras, "saida_outros": extra}, {"rules"}


def _juntar(params, ajustes):
    modo = params.get("mode", "append")
    config = {"modo": "anexar", "entradas": 2}
    if modo == "chooseBranch":
        config["modo"] = "escolher_entrada"
    elif modo == "combine":
        por = params.get("combineBy", "combineByFields")
        if por == "combineByPosition":
            config["modo"] = "combinar_por_posicao"
        elif por == "combineByFields":
            pares = [
                (_txt(p.get("field1")), _txt(p.get("field2")))
                for p in _lista(_dict(params.get("fields")).get("values"))
            ]
            if not pares:
                pares = [(c, c) for c in _lista_csv(params.get("fieldsToMatchString"))]
            if len(pares) > 1:
                ajustes.append("Juntar por vários campos: só o primeiro par foi importado.")
            campo1, campo2 = pares[0] if pares else ("", "")
            config.update(
                modo="combinar_por_campo",
                campo1=campo1,
                campo2=campo2,
                tipo=JUNCAO.get(params.get("joinMode", "keepMatches"), "dentro"),
            )
        else:
            ajustes.append(f"Modo de combinação '{_txt(por)}' sem equivalente.")
            config["modo"] = "combinar_por_posicao"
    elif modo != "append":
        ajustes.append(f"Modo '{_txt(modo)}' do Juntar sem equivalente: anexar.")
    return config, {"mode", "combineBy", "fields", "fieldsToMatchString", "joinMode"}


def _ordenar(params, ajustes):
    campos = []
    for c in _lista(_dict(params.get("sortFieldsUi")).get("sortField")):
        ordem = "desc" if c.get("order") == "descending" else "asc"
        campos.append({"campo": _txt(c.get("fieldName")), "ordem": ordem})
    return {"campos": campos}, {"sortFieldsUi", "type"}


def _limitar(params, ajustes):
    de = "fim" if params.get("keep") == "lastItems" else "inicio"
    return {"quantidade": _int(params.get("maxItems"), 1, 1), "de": de}, {"maxItems", "keep"}


def _duplicados(params, ajustes):
    modo = params.get("compare", "allFields")
    if modo not in ("allFields", "selectedFields"):
        ajustes.append(f"Comparação '{_txt(modo)}' sem equivalente: todos os campos.")
    if modo == "selectedFields":
        config = {"comparar": "campos", "campos": _lista_csv(params.get("fieldsToCompare"))}
    else:
        config = {"comparar": "todos", "campos": []}
    return config, {"compare", "fieldsToCompare"}


def _separar(params, ajustes):
    incluir = params.get("include", "noOtherFields")
    if incluir == "selectedOtherFields":
        ajustes.append("Incluir só alguns campos do pai sem equivalente: nenhum campo do pai.")
    config = {
        "campo": _txt(params.get("fieldToSplitOut")),
        "incluir": "campos_pai" if incluir == "allOtherFields" else "nada",
    }
    return config, {"fieldToSplitOut", "include", "fieldsToInclude"}


def _agregar(params, ajustes):
    if params.get("aggregate") == "aggregateAllItemData":
        config = {
            "modo": "todos",
            "campos": [],
            "saida": _txt(params.get("destinationFieldName"), "data"),
        }
    else:
        lista = _lista(_dict(params.get("fieldsToAggregate")).get("fieldToAggregate"))
        config = {
            "modo": "campos",
            "campos": [_txt(c.get("fieldToAggregate")) for c in lista],
            "saida": "",
        }
    return config, {"aggregate", "fieldsToAggregate", "destinationFieldName"}


def _resumir(params, ajustes):
    operacoes = []
    for v in _lista(_dict(params.get("fieldsToSummarize")).get("values")):
        op = OPS_RESUMIR.get(v.get("aggregation"))
        if op is None:
            ajustes.append(f"Agregação '{_txt(v.get('aggregation'))}' sem equivalente: contar.")
            op = "contar"
        operacoes.append({"op": op, "campo": _txt(v.get("field"))})
    config = {"agrupar_por": _lista_csv(params.get("fieldsToSplitBy")), "operacoes": operacoes}
    return config, {"fieldsToSplitBy", "fieldsToSummarize"}


def _data(params, ajustes):
    acao = params.get("action") or params.get("operation")
    operacao = OPS_DATA.get(acao)
    if operacao is None:
        ajustes.append(f"Operação de data '{_txt(acao)}' sem equivalente: data atual.")
        operacao = "agora"
    config = {"operacao": operacao}
    saida = _txt(params.get("outputFieldName"))
    if saida:
        config["saida"] = saida
    if operacao in ("somar", "subtrair"):
        config.update(
            campo=_txt(params.get("date")),
            quantidade=_int(params.get("duration"), 0),
            unidade=UNIDADES.get(params.get("timeUnit"), "dias"),
        )
    elif operacao == "formatar":
        formato = _txt(params.get("format"))
        if formato == "custom":
            formato = _txt(params.get("customFormat"))
        config.update(campo=_txt(params.get("date")), formato=formato)
    elif operacao == "diferenca":
        config.update(campo=_txt(params.get("startDate")), campo2=_txt(params.get("endDate")))
    elif operacao == "inicio_de":
        config.update(
            campo=_txt(params.get("date")),
            unidade=UNIDADES_INICIO.get(params.get("toNearest"), "dia"),
        )
    conhecidas = {
        "action", "operation", "outputFieldName", "date", "duration", "timeUnit", "format",
        "customFormat", "startDate", "endDate", "mode", "toNearest", "unit",
    }  # fmt: skip
    return config, conhecidas


def _lotes(params, ajustes):
    return {"tamanho_lote": _int(params.get("batchSize"), 10, 1)}, {"batchSize"}


def _parar(params, ajustes):
    return {"mensagem": _txt(params.get("errorMessage"))}, {"errorMessage", "errorType"}


def _vazio(params, ajustes):
    return {}, set()


MAPEADORES = {
    "gatilho": _vazio,
    "http": _http,
    "codigo": _codigo,
    "editar_campos": _set,
    "filtrar": _filtro,
    "se": _filtro,
    "escolher": _escolher,
    "juntar": _juntar,
    "ordenar": _ordenar,
    "limitar": _limitar,
    "remover_duplicados": _duplicados,
    "separar_lista": _separar,
    "agregar": _agregar,
    "resumir": _resumir,
    "data_hora": _data,
    "repetir_em_lotes": _lotes,
    "parar_com_erro": _parar,
    "sem_operacao": _vazio,
}


# ---------------------------------------------------------------- nós, notas, arestas
def _posicao(bruta):
    if (
        isinstance(bruta, list)
        and len(bruta) == 2
        and all(isinstance(v, int | float) and not isinstance(v, bool) for v in bruta)
    ):
        return {"x": bruta[0], "y": bruta[1]}
    return {"x": 0, "y": 0}


def _titulo_unico(nome, usados):
    base = (nome.strip() or "Sem título")[:MAX_TITULO]
    titulo, n = base, 2
    while titulo in usados:
        sufixo = f" {n}"
        titulo = base[: MAX_TITULO - len(sufixo)] + sufixo
        n += 1
    usados.add(titulo)
    return titulo


def _nota(texto, posicao, tamanho=None, cor="amarela"):
    nota = {"id": _id("nota"), "texto": texto[:MAX_NOTA], "posicao": posicao, "cor": cor}
    if tamanho:
        nota["tamanho"] = tamanho
    return nota


def _sticky(no, notas):
    params = _dict(no.get("parameters"))
    larg, alt = params.get("width"), params.get("height")
    tamanho = None
    if all(isinstance(v, int | float) and not isinstance(v, bool) for v in (larg, alt)):
        tamanho = {"l": larg, "a": alt}
    cor = params.get("color")
    cor = (
        CORES.get(cor, "amarela")
        if isinstance(cor, int) and not isinstance(cor, bool)
        else "amarela"
    )
    notas.append(_nota(_txt(params.get("content")), _posicao(no.get("position")), tamanho, cor))


def _validar_nos(dados):
    nos = dados.get("nodes")
    if not isinstance(nos, list) or not nos:
        raise imp.ErroImportacao("o arquivo do n8n não tem nós")
    for no in nos:
        if not (
            isinstance(no, dict)
            and isinstance(no.get("name"), str)
            and isinstance(no.get("type"), str)
        ):
            raise imp.ErroImportacao("um dos nós do arquivo do n8n é inválido")
    if not isinstance(dados.get("connections", {}), dict):
        raise imp.ErroImportacao("as conexões do arquivo do n8n são inválidas")
    return nos


def _converter_no(no, titulo, relatorio, notas):
    tipo_n8n = no["type"]
    curto = tipo_n8n[len(PREFIXO) :] if tipo_n8n.startswith(PREFIXO) else None
    tipo = TIPOS.get(curto)
    posicao = _posicao(no.get("position"))
    params = _dict(no.get("parameters"))
    if tipo is None:
        tipo, config = "sem_operacao", {}
        relatorio["sem_equivalente"].append({"no": titulo, "tipo_n8n": tipo_n8n[:200]})
        notas.append(
            _nota(f"Não suportado: {tipo_n8n[:200]}", {"x": posicao["x"], "y": posicao["y"] + 90})
        )
    else:
        ajustes = []
        config, conhecidas = MAPEADORES[tipo](params, ajustes)
        for chave in sorted(set(params) - conhecidas - COMUNS):
            ajustes.append(f"Parâmetro '{chave[:60]}' sem equivalente.")
        if isinstance(no.get("credentials"), dict) and no["credentials"]:
            ajustes.append(
                "Credenciais do n8n não importadas: crie uma credencial e escolha no nó."
            )
        for mensagem in ajustes:
            relatorio["ajustes"].append({"no": titulo, "mensagem": mensagem})
        relatorio["importados"].append(titulo)
    em_erro = {"continueRegularOutput": "continuar", "continueErrorOutput": "saida_de_erro"}.get(
        no.get("onError"), "parar"
    )
    if tipo in ("gatilho", "saida"):
        em_erro = "parar"
    novo = {
        "id": _id("n"),
        "tipo": tipo,
        "titulo": titulo,
        "posicao": posicao,
        "config": config,
        "desativado": no.get("disabled") is True,
        "executar_uma_vez": no.get("executeOnce") is True,
        "em_erro": em_erro,
    }
    texto = no.get("notes")
    if isinstance(texto, str) and texto.strip():
        notas.append(_nota(f"{titulo}: {texto}", {"x": posicao["x"], "y": posicao["y"] - 90}))
    return novo


def _arestas(conexoes, ids, tipos, relatorio):
    arestas, vistas = [], set()
    for origem, saidas in conexoes.items():
        if origem not in ids or not isinstance(saidas, dict):
            if origem not in ids:
                relatorio["ajustes"].append(
                    {"no": origem[:80], "mensagem": "Conexão de um nó que não existe."}
                )
            continue
        for canal, listas in saidas.items():
            if canal != "main":
                relatorio["ajustes"].append(
                    {"no": origem[:80], "mensagem": f"Conexão '{canal[:40]}' sem equivalente."}
                )
                continue
            if not isinstance(listas, list):
                continue
            for saida, destinos in enumerate(listas):
                if tipos[origem] == "repetir_em_lotes" and saida in (0, 1):
                    saida = 1 - saida  # n8n: 0 done / 1 loop ↔ nosso: 0 loop / 1 pronto
                for destino in _lista(destinos):
                    nome, entrada = destino.get("node"), destino.get("index", 0)
                    if nome not in ids or isinstance(entrada, bool) or not isinstance(entrada, int):
                        relatorio["ajustes"].append(
                            {"no": origem[:80], "mensagem": "Conexão para um nó que não existe."}
                        )
                        continue
                    chave = (origem, saida, nome, entrada)
                    if chave not in vistas and saida >= 0 and entrada >= 0:
                        vistas.add(chave)
                        arestas.append(
                            {
                                "de": ids[origem],
                                "saida": saida,
                                "para": ids[nome],
                                "entrada": entrada,
                            }
                        )
    return arestas


def _dados_fixos(pin, ids, relatorio):
    fixos = {}
    for nome, itens in (pin if isinstance(pin, dict) else {}).items():
        if nome not in ids or not isinstance(itens, list):
            continue
        lista = []
        for item in itens:
            if isinstance(item, dict) and isinstance(item.get("json"), dict):
                lista.append({"json": item["json"]})
            elif isinstance(item, dict):
                lista.append({"json": item})
        if lista:
            fixos[ids[nome]] = lista
        else:
            relatorio["ajustes"].append(
                {"no": nome[:80], "mensagem": "Dados fixos inválidos ignorados."}
            )
    return fixos


def importar(dados):
    """Dict do n8n → `(nome, descricao, grafo, relatorio)`."""
    nos_n8n = _validar_nos(dados)
    relatorio = imp.relatorio_vazio()
    notas, nos, usados = [], [], set()
    ids, tipos, por_nome = {}, {}, {}
    for no in nos_n8n:
        if no["type"] == PREFIXO + "stickyNote":
            _sticky(no, notas)
            continue
        titulo = _titulo_unico(no["name"], usados)
        novo = _converter_no(no, titulo, relatorio, notas)
        nos.append(novo)
        por_nome.setdefault(no["name"], novo)
    for nome, novo in por_nome.items():
        ids[nome] = novo["id"]
        tipos[nome] = novo["tipo"]
    arestas = _arestas(_dict(dados.get("connections")), ids, tipos, relatorio)
    por_id = {n["id"]: n for n in nos}
    for aresta in arestas:
        destino = por_id[aresta["para"]]
        if destino["tipo"] == "juntar":
            destino["config"]["entradas"] = min(
                4, max(destino["config"]["entradas"], aresta["entrada"] + 1)
            )
    grafo = {
        "versao": 2,
        "nos": nos,
        "arestas": arestas,
        "notas": notas,
        "dados_fixos": _dados_fixos(dados.get("pinData"), ids, relatorio),
    }
    for no in nos:
        imp.trocar_segredos(no, relatorio)
        imp.marcar_expressoes(no, relatorio)
    imp.desativar_codigo(grafo, relatorio)
    return _txt(dados.get("name")), "", grafo, relatorio


__all__ = ["importar"]
