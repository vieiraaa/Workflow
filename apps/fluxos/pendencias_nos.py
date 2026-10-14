"""Pendências de configuração dos nós de dados/fluxo/código (GRF-04, NOV-02..04, NOV-06).

Devolve `[(campo, mensagem)]` para um nó (dict v2 já com tipos de config válidos). Não toca o banco.
"""

from urllib.parse import urlsplit

from . import catalogo

MSG_CAMPO = "Informe este campo."


def _texto_vazio(valor):
    return not isinstance(valor, str) or not valor.strip()


def _condicao(condicao, prefixo):
    if not isinstance(condicao, dict):
        return [(prefixo, "Condição inválida.")]
    achados = []
    operador, tipo = condicao.get("operador"), condicao.get("tipo", "texto")
    if operador not in catalogo.OPERADORES:
        achados.append((f"{prefixo}.operador", "Escolha um operador."))
    if tipo not in catalogo.TIPOS_CONDICAO:
        achados.append((f"{prefixo}.tipo", "Escolha um tipo de valor."))
    if _texto_vazio(condicao.get("esquerda")):
        achados.append((f"{prefixo}.esquerda", "Informe o valor a comparar."))
    direita = condicao.get("direita")
    if operador not in catalogo.SEM_DIREITA and operador in catalogo.OPERADORES:
        if direita is None or (isinstance(direita, str) and direita == ""):
            achados.append((f"{prefixo}.direita", "Informe o valor de comparação."))
    if operador == "regex" and isinstance(direita, str) and len(direita) > catalogo.MAX_REGEX:
        achados.append((f"{prefixo}.direita", "A regex pode ter no máximo 200 caracteres."))
    return achados


def _condicoes(condicoes, combinar, prefixo):
    achados = []
    if not isinstance(condicoes, list) or not condicoes:
        return [(prefixo, "Inclua pelo menos uma condição.")]
    for indice, condicao in enumerate(condicoes):
        achados += _condicao(condicao, f"{prefixo}[{indice}]")
    if combinar not in (None, "e", "ou"):
        achados.append((f"{prefixo}.combinar", "Combine por 'e' ou 'ou'."))
    return achados


def _escolher(config):
    regras = config.get("regras", [])
    if not regras:
        return [("regras", "Inclua pelo menos uma regra.")]
    achados = []
    if len(regras) > catalogo.MAX_REGRAS_ESCOLHER:
        achados.append(("regras", "Use no máximo 10 regras."))
    for indice, regra in enumerate(regras):
        if not isinstance(regra, dict):
            achados.append((f"regras[{indice}]", "Regra inválida."))
            continue
        achados += _condicoes(regra.get("condicoes"), regra.get("combinar"), f"regras[{indice}]")
    return achados


def _juntar(config):
    achados = []
    entradas = config.get("entradas", 2)
    if not catalogo.ENTRADAS_JUNTAR[0] <= entradas <= catalogo.ENTRADAS_JUNTAR[1]:
        achados.append(("entradas", "O Juntar aceita de 2 a 4 entradas."))
    modo = config.get("modo", "anexar")
    if modo == "combinar_por_campo":
        for campo in ("campo1", "campo2"):
            if _texto_vazio(config.get(campo)):
                achados.append((campo, MSG_CAMPO))
    if modo == "escolher_entrada":
        entrada = config.get("entrada")
        if not isinstance(entrada, int) or not 0 <= entrada < max(entradas, 1):
            achados.append(("entrada", "Escolha uma entrada existente (a primeira é 0)."))
    return achados


def _lista_de_texto(config, campo, mensagem):
    valores = config.get(campo)
    if (
        not isinstance(valores, list)
        or not valores
        or not all(isinstance(v, str) and v.strip() for v in valores)
    ):
        return [(campo, mensagem)]
    return []


def _ordenar(config):
    campos = config.get("campos")
    if not isinstance(campos, list) or not campos:
        return [("campos", "Informe pelo menos um campo para ordenar.")]
    achados = []
    for indice, item in enumerate(campos):
        if not isinstance(item, dict) or _texto_vazio(item.get("campo")):
            achados.append((f"campos[{indice}]", "Informe o campo."))
        elif item.get("ordem", "asc") not in ("asc", "desc"):
            achados.append((f"campos[{indice}].ordem", "Use asc ou desc."))
    return achados


def _resumir(config):
    achados = []
    if not isinstance(config.get("agrupar_por", []), list):
        achados.append(("agrupar_por", "Lista de campos inválida."))
    operacoes = config.get("operacoes")
    if not isinstance(operacoes, list) or not operacoes:
        return [*achados, ("operacoes", "Inclua pelo menos uma operação.")]
    for indice, operacao in enumerate(operacoes):
        if (
            not isinstance(operacao, dict)
            or operacao.get("op") not in catalogo.OPS_RESUMIR
            or _texto_vazio(operacao.get("campo"))
        ):
            achados.append((f"operacoes[{indice}]", "Informe o campo e a operação."))
    return achados


def _data_hora(config):
    operacao = config.get("operacao")
    if operacao is None:
        return [("operacao", "Escolha a operação.")]
    achados = []
    if operacao != "agora" and _texto_vazio(config.get("campo")):
        achados.append(("campo", MSG_CAMPO))
    if (
        operacao == "agora"
        and _texto_vazio(config.get("saida"))
        and _texto_vazio(config.get("campo"))
    ):
        achados.append(("saida", "Informe o campo onde gravar."))
    if operacao == "formatar" and _texto_vazio(config.get("formato")):
        achados.append(("formato", MSG_CAMPO))
    if operacao in ("somar", "subtrair", "diferenca"):
        if config.get("unidade") not in catalogo.UNIDADES_DATA:
            achados.append(("unidade", "Escolha a unidade de tempo."))
        if operacao != "diferenca" and "quantidade" not in config:
            achados.append(("quantidade", MSG_CAMPO))
    if operacao == "diferenca" and _texto_vazio(config.get("campo2")):
        achados.append(("campo2", MSG_CAMPO))
    if operacao == "inicio_de" and config.get("unidade") not in catalogo.UNIDADES_INICIO:
        achados.append(("unidade", "Escolha dia, semana, mes ou hora."))
    return achados


def _editar(config):
    if config.get("modo", "manual") == "json":
        return [("json", MSG_CAMPO)] if _texto_vazio(config.get("json")) else []
    campos = config.get("campos")
    if not isinstance(campos, list) or not campos:
        return [("campos", "Inclua pelo menos um campo.")]
    achados = []
    for indice, campo in enumerate(campos):
        if not isinstance(campo, dict) or _texto_vazio(campo.get("nome")):
            achados.append((f"campos[{indice}].nome", "Informe o nome do campo."))
        elif campo.get("tipo", "texto") not in ("texto", "numero", "booleano", "lista", "objeto"):
            achados.append((f"campos[{indice}].tipo", "Escolha um tipo."))
    return achados


def _url_n8n(config):
    url = config.get("url", "")
    if _texto_vazio(url):
        return [("url", "Informe a URL do webhook do n8n.")]
    if url.lstrip().startswith(("{{", "=")):
        return []  # expressão fornece esquema/host: o executor valida
    try:
        partes = urlsplit(url.strip())
        valida = partes.scheme.lower() in ("http", "https") and bool(partes.netloc)
    except ValueError:
        valida = False
    if not valida:
        return [("url", "A URL do webhook deve começar com https:// (ou http://).")]
    return []


def _chamar_n8n(config):
    achados = _url_n8n(config)
    if config.get("enviar", "item") == "personalizado" and _texto_vazio(config.get("corpo")):
        achados.append(("corpo", "Informe o corpo a enviar."))
    tempo = config.get("tempo_limite_s", catalogo.PADROES_N8N["tempo_limite_s"])
    if not catalogo.TEMPO_N8N[0] <= tempo <= catalogo.TEMPO_N8N[1]:
        achados.append(("tempo_limite_s", "Tempo limite entre 1 e 55 segundos."))
    return achados


def avisos_do_no(no):
    """Avisos (não bloqueiam) de um nó: `[(campo, mensagem)]` (N8N-02/07)."""
    if no.get("tipo") == "chamar_n8n":
        url = no["config"].get("url")
        if isinstance(url, str) and "/webhook-test/" in url:
            return [("url", catalogo.AVISO_N8N_TESTE)]
    return []


def pendencias_do_no(no):
    tipo, config = no["tipo"], no["config"]
    if tipo == "chamar_n8n":
        return _chamar_n8n(config)
    if tipo in ("se", "filtrar"):
        return _condicoes(config.get("condicoes"), config.get("combinar"), "condicoes")
    if tipo == "escolher":
        return _escolher(config)
    if tipo == "juntar":
        return _juntar(config)
    if tipo == "ordenar":
        return _ordenar(config)
    if tipo == "limitar":
        quantidade = config.get("quantidade")
        if not isinstance(quantidade, int) or quantidade < 0:
            return [("quantidade", "Informe uma quantidade a partir de 0.")]
        return []
    if tipo == "remover_duplicados":
        if config.get("comparar") == "campos":
            return _lista_de_texto(config, "campos", "Informe os campos a comparar.")
        return []
    if tipo == "separar_lista":
        return [("campo", MSG_CAMPO)] if _texto_vazio(config.get("campo")) else []
    if tipo == "agregar":
        if config.get("modo") == "campos":
            return _lista_de_texto(config, "campos", "Informe os campos a agregar.")
        return []
    if tipo == "resumir":
        return _resumir(config)
    if tipo == "data_hora":
        return _data_hora(config)
    if tipo == "editar_campos":
        return _editar(config)
    if tipo == "repetir_em_lotes":
        tamanho = config.get("tamanho_lote")
        if not isinstance(tamanho, int) or tamanho < 1:
            return [("tamanho_lote", "O tamanho do lote precisa ser de 1 em diante.")]
        return []
    if tipo == "parar_com_erro":
        return [("mensagem", MSG_CAMPO)] if _texto_vazio(config.get("mensagem")) else []
    if tipo == "codigo":
        codigo = config.get("codigo")
        if _texto_vazio(codigo):
            return [("codigo", "Escreva o código.")]
        if len(codigo) > catalogo.MAX_CODIGO:
            return [("codigo", "O código pode ter no máximo 50.000 caracteres.")]
    return []
