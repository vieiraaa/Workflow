"""Exportação de fluxos (IMP-01, IMP-05, MV2-18 C9): formato nativo e n8n (melhor esforço).

Funções puras (sem banco). Credenciais saem só como NOME (nativo) ou referência vazia (n8n):
o valor nunca passa por aqui.
"""

import re
import unicodedata

from . import n8n as mapa

PREFIXO = mapa.PREFIXO
INVERSO_TIPOS = {nativo: n8n for n8n, nativo in mapa.TIPOS.items()}
INVERSO_TIPOS["saida"] = "noOp"  # equivalência "último nó" (MV2-20)
INVERSO_OPERADORES = {v: k for k, v in mapa.OPERADORES.items()}
INVERSO_TIPOS_COND = {v: k for k, v in mapa.TIPOS_COND.items()}
INVERSO_OPS_RESUMIR = {v: k for k, v in mapa.OPS_RESUMIR.items()}
INVERSO_JUNCAO = {v: k for k, v in mapa.JUNCAO.items()}
CORES_N8N = {"amarela": 1, "cinza": 2, "verde": 4, "azul": 5}
VERSOES = {
    "gatilho": 1,
    "http": 4.2,
    "codigo": 2,
    "editar_campos": 3.4,
    "filtrar": 2.2,
    "se": 2.2,
    "escolher": 3.2,
    "juntar": 3,
    "ordenar": 1,
    "limitar": 1,
    "remover_duplicados": 2,
    "separar_lista": 1,
    "agregar": 1,
    "resumir": 1,
    "repetir_em_lotes": 3,
    "parar_com_erro": 1,
    "sem_operacao": 1,
    "saida": 1,
}
SEM_EXPORTACAO = {
    "data_hora": "Operações de data e hora ainda não têm exportação para o n8n.",
    "chamar_n8n": "O nó Chamar n8n chama um fluxo do n8n e não tem equivalente na exportação.",
}


def slug(nome):
    texto = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    texto = re.sub(r"[^A-Za-z0-9]+", "-", texto).strip("-").lower()
    return texto[:60] or "fluxo"


def credenciais_usadas(grafo):
    nomes = {
        no["config"]["credencial"]
        for no in grafo.get("nos", [])
        if no.get("tipo") in ("http", "chamar_n8n")
        and isinstance(no["config"].get("credencial"), str)
    }
    return sorted(n for n in nomes if n)


def exportar_nativo(fluxo):
    return {
        "formato": "construtor-workflows",
        "versao": 2,
        "fluxo": {"nome": fluxo.nome, "descricao": fluxo.descricao},
        "grafo": fluxo.grafo,
        "credenciais_usadas": credenciais_usadas(fluxo.grafo),
    }


# ---------------------------------------------------------------- n8n
def _pares(pares):
    return {"parameters": [{"name": p["nome"], "value": p["valor"]} for p in pares]}


def _condicoes(config):
    return {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
        "conditions": [
            {
                "id": f"c{i}",
                "leftValue": c.get("esquerda", ""),
                **({"rightValue": c["direita"]} if "direita" in c else {}),
                "operator": {
                    "type": INVERSO_TIPOS_COND.get(c.get("tipo"), "string"),
                    "operation": INVERSO_OPERADORES.get(c.get("operador"), "equals"),
                },
            }
            for i, c in enumerate(config.get("condicoes", []))
        ],
        "combinator": "or" if config.get("combinar") == "ou" else "and",
    }


def _http(c):
    params = {"method": c.get("metodo", "GET"), "url": c.get("url", "")}
    if c.get("query"):
        params.update(sendQuery=True, queryParameters=_pares(c["query"]))
    if c.get("headers"):
        params.update(sendHeaders=True, headerParameters=_pares(c["headers"]))
    corpo = c.get("corpo") or {}
    tipo = corpo.get("tipo", "nenhum")
    if tipo == "json":
        params.update(
            sendBody=True,
            contentType="json",
            specifyBody="json",
            jsonBody=corpo.get("conteudo", ""),
        )
    elif tipo == "formulario":
        params.update(
            sendBody=True,
            contentType="form-urlencoded",
            specifyBody="keypair",
            bodyParameters=_pares(corpo.get("conteudo", [])),
        )
    elif tipo == "texto":
        params.update(
            sendBody=True,
            contentType="raw",
            rawContentType="text/plain",
            body=corpo.get("conteudo", ""),
        )
    resposta = {
        "responseFormat": {"json": "json", "texto": "text"}.get(c.get("resposta"), "autodetect")
    }
    if c.get("resposta_completa"):
        resposta["fullResponse"] = True
    opcoes = {"response": {"response": resposta}}
    pag = c.get("paginacao")
    if pag:
        opcoes["pagination"] = {"pagination": _paginacao(pag)}
    params["options"] = opcoes
    return params


def _paginacao(pag):
    saida = {"limitPagesFetched": True, "maxRequests": pag.get("limite_paginas", 10)}
    if pag.get("modo") == "proxima_url":
        saida.update(paginationMode="responseContainsNextURL", nextURL=pag.get("url", ""))
    else:
        tipo = {"query": "qs", "corpo": "body", "header": "headers"}.get(pag.get("onde"), "qs")
        saida["parameters"] = {
            "parameters": [
                {"type": tipo, "name": pag.get("nome", ""), "value": pag.get("valor", "")}
            ]
        }
    quando = pag.get("parar_quando")
    if quando == "expressao":
        saida.update(paginationCompleteWhen="other", completeExpression=pag.get("expressao", ""))
    elif quando == "status":
        saida.update(
            paginationCompleteWhen="receiveSpecificStatusCodes",
            statusCodesWhenComplete=",".join(str(x) for x in pag.get("codigos", [])),
        )
    else:
        saida["paginationCompleteWhen"] = "responseIsEmpty"
    return saida


def _parametros(no):
    tipo, c = no["tipo"], no["config"]
    if tipo == "http":
        return _http(c)
    if tipo == "codigo":
        modo = "runOnceForEachItem" if c.get("modo") == "uma_vez_por_item" else "runOnceForAllItems"
        return {"mode": modo, "jsCode": c.get("codigo", "")}
    if tipo in ("se", "filtrar"):
        return {"conditions": _condicoes(c)}
    if tipo == "editar_campos":
        if c.get("modo") == "json":
            return {
                "mode": "raw",
                "jsonOutput": c.get("json", ""),
                "includeOtherFields": bool(c.get("incluir_outros")),
            }
        campos = [
            {
                "id": f"a{i}",
                "name": x.get("nome", ""),
                "value": x.get("valor"),
                "type": INVERSO_TIPOS_COND.get(x.get("tipo"), "string"),
            }
            for i, x in enumerate(c.get("campos", []))
        ]
        return {
            "mode": "manual",
            "assignments": {"assignments": campos},
            "includeOtherFields": bool(c.get("incluir_outros")),
        }
    if tipo == "escolher":
        valores = [
            {"conditions": _condicoes(r), "renameOutput": True, "outputKey": r.get("rotulo", "")}
            for r in c.get("regras", [])
        ]
        extra = {"fallbackOutput": "extra"} if c.get("saida_outros") else {}
        return {"rules": {"values": valores}, "options": extra}
    if tipo == "juntar":
        modo = c.get("modo")
        if modo == "combinar_por_campo":
            return {
                "mode": "combine",
                "combineBy": "combineByFields",
                "fieldsToMatchString": c.get("campo1", ""),
                "joinMode": INVERSO_JUNCAO.get(c.get("tipo"), "keepMatches"),
            }
        if modo == "combinar_por_posicao":
            return {"mode": "combine", "combineBy": "combineByPosition"}
        if modo == "escolher_entrada":
            return {"mode": "chooseBranch"}
        return {"mode": "append"}
    if tipo == "ordenar":
        campos = [
            {
                "fieldName": x.get("campo", ""),
                "order": "descending" if x.get("ordem") == "desc" else "ascending",
            }
            for x in c.get("campos", [])
        ]
        return {"sortFieldsUi": {"sortField": campos}}
    if tipo == "limitar":
        return {
            "maxItems": c.get("quantidade", 1),
            "keep": "lastItems" if c.get("de") == "fim" else "firstItems",
        }
    if tipo == "remover_duplicados":
        if c.get("comparar") == "campos":
            return {"compare": "selectedFields", "fieldsToCompare": ",".join(c.get("campos", []))}
        return {"compare": "allFields"}
    if tipo == "separar_lista":
        return {
            "fieldToSplitOut": c.get("campo", ""),
            "include": "allOtherFields" if c.get("incluir") == "campos_pai" else "noOtherFields",
        }
    if tipo == "agregar":
        if c.get("modo") == "todos":
            return {
                "aggregate": "aggregateAllItemData",
                "destinationFieldName": c.get("saida", "data"),
            }
        return {
            "aggregate": "aggregateIndividualFields",
            "fieldsToAggregate": {
                "fieldToAggregate": [{"fieldToAggregate": x} for x in c.get("campos", [])]
            },
        }
    if tipo == "resumir":
        valores = [
            {
                "aggregation": INVERSO_OPS_RESUMIR.get(o.get("op"), "count"),
                "field": o.get("campo", ""),
            }
            for o in c.get("operacoes", [])
        ]
        return {
            "fieldsToSplitBy": ",".join(c.get("agrupar_por", [])),
            "fieldsToSummarize": {"values": valores},
        }
    if tipo == "repetir_em_lotes":
        return {"batchSize": c.get("tamanho_lote", 10)}
    if tipo == "parar_com_erro":
        return {"errorMessage": c.get("mensagem", ""), "errorType": "errorMessage"}
    return {}


def _no_n8n(no):
    tipo = no["tipo"]
    saida = {
        "id": no["id"],
        "name": no["titulo"],
        "type": PREFIXO + INVERSO_TIPOS[tipo],
        "typeVersion": VERSOES[tipo],
        "position": [no["posicao"]["x"], no["posicao"]["y"]],
        "parameters": _parametros(no),
    }
    if no.get("desativado"):
        saida["disabled"] = True
    if no.get("executar_uma_vez"):
        saida["executeOnce"] = True
    em_erro = {"continuar": "continueRegularOutput", "saida_de_erro": "continueErrorOutput"}.get(
        no.get("em_erro")
    )
    if em_erro:
        saida["onError"] = em_erro
    credencial = no["config"].get("credencial") if tipo == "http" else None
    if credencial:
        saida["credentials"] = {"httpCustomAuth": {}}  # referência vazia: nunca o valor
        saida["parameters"]["authentication"] = "genericCredentialType"
    return saida


def exportar_n8n(fluxo):
    grafo = fluxo.grafo
    nos, fora, exportados = [], [], {}
    for no in grafo["nos"]:
        if no["tipo"] in SEM_EXPORTACAO:
            fora.append(
                {"no": no["titulo"], "tipo": no["tipo"], "motivo": SEM_EXPORTACAO[no["tipo"]]}
            )
            continue
        exportados[no["id"]] = no
        nos.append(_no_n8n(no))
    conexoes = {}
    for aresta in grafo["arestas"]:
        origem, destino = exportados.get(aresta["de"]), exportados.get(aresta["para"])
        if origem is None or destino is None:
            continue
        saida = aresta.get("saida", 0)
        if origem["tipo"] == "repetir_em_lotes" and saida in (0, 1):
            saida = 1 - saida
        listas = conexoes.setdefault(origem["titulo"], {"main": []})["main"]
        while len(listas) <= saida:
            listas.append([])
        listas[saida].append(
            {"node": destino["titulo"], "type": "main", "index": aresta.get("entrada", 0)}
        )
    for nota in grafo.get("notas", []):
        tamanho = nota.get("tamanho") or {}
        nos.append(
            {
                "id": nota["id"],
                "name": f"Nota {nota['id']}"[:80],
                "type": PREFIXO + "stickyNote",
                "typeVersion": 1,
                "position": [nota["posicao"]["x"], nota["posicao"]["y"]],
                "parameters": {
                    "content": nota.get("texto", ""),
                    "width": tamanho.get("l", 240),
                    "height": tamanho.get("a", 160),
                    "color": CORES_N8N.get(nota.get("cor"), 1),
                },
            }
        )
    fixos = {
        exportados[chave]["titulo"]: itens
        for chave, itens in grafo.get("dados_fixos", {}).items()
        if chave in exportados
    }
    return {
        "name": fluxo.nome,
        "nodes": nos,
        "connections": conexoes,
        "pinData": fixos,
        "active": False,
        "settings": {},
        "construtor_relatorio": {"fora": fora},
    }
