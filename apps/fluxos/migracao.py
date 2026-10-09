"""Migração do grafo v1 para o v2 (MV2-03, MV2-12 L1). Função pura, sem banco.

- nós ganham `desativado=False`, `executar_uma_vez=False`, `em_erro="parar"`;
- arestas ganham `saida=0` e `entrada=0`; o grafo ganha `notas=[]` e `dados_fixos={}`;
- nó http: `corpo` (texto) vira `{tipo, conteudo}`; ganha `credencial=None`,
  `resposta="automatica"`, `paginacao=None` e `resposta_completa=True` (a saída v1 era
  {status, headers, corpo});
- `{{ anterior.a.0.b }}` vira `{{ $json.a[0].b }}` (mesmo significado: o item v2 do nó http com
  `resposta_completa` tem a mesma forma da saída v1).

Entrada malformada passa sem mudança nos trechos que não reconhece: quem valida é o `validar`.
"""

import copy
import re

_PLACEHOLDER = re.compile(r"(\{\{)(.*?)(\}\})", re.DOTALL)
_ANTERIOR = re.compile(r"(?<![\w$.])anterior((?:\.[A-Za-z0-9_-]+)+)")
_IDENTIFICADOR = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _caminho_js(achado):
    saida = "$json"
    for segmento in achado.group(1)[1:].split("."):
        if segmento.isdigit():
            saida += f"[{segmento}]"
        elif _IDENTIFICADOR.fullmatch(segmento):
            saida += f".{segmento}"
        else:
            saida += f'["{segmento}"]'
    return saida


def reescrever_placeholders(texto):
    """`{{ anterior.x }}` → `{{ $json.x }}` em todos os blocos do texto."""
    if not isinstance(texto, str):
        return texto
    return _PLACEHOLDER.sub(
        lambda bloco: bloco.group(1) + _ANTERIOR.sub(_caminho_js, bloco.group(2)) + bloco.group(3),
        texto,
    )


def _pares(pares):
    if not isinstance(pares, list):
        return pares
    return [
        {
            **par,
            "nome": reescrever_placeholders(par.get("nome")),
            "valor": reescrever_placeholders(par.get("valor")),
        }
        if isinstance(par, dict)
        else par
        for par in pares
    ]


def _config_http(config):
    config = dict(config)
    corpo = config.get("corpo", "")
    if isinstance(corpo, str):
        config["corpo"] = {
            "tipo": "json" if corpo.strip() else "nenhum",
            "conteudo": reescrever_placeholders(corpo),
        }
    if "url" in config:
        config["url"] = reescrever_placeholders(config["url"])
    for campo in ("headers", "query"):
        if campo in config:
            config[campo] = _pares(config[campo])
    config.setdefault("credencial", None)
    config.setdefault("resposta", "automatica")
    config.setdefault("resposta_completa", True)
    config.setdefault("paginacao", None)
    return config


def migrar_v1_para_v2(grafo):
    """Devolve uma CÓPIA do grafo v1 no formato v2. Grafo que não é v1 volta como cópia."""
    if (
        not isinstance(grafo, dict)
        or grafo.get("versao") != 1
        or isinstance(grafo.get("versao"), bool)
    ):
        return copy.deepcopy(grafo)
    novo = copy.deepcopy(grafo)
    novo["versao"] = 2
    novo.setdefault("notas", [])
    novo.setdefault("dados_fixos", {})
    if isinstance(novo.get("nos"), list):
        for no in novo["nos"]:
            if not isinstance(no, dict):
                continue
            no.setdefault("desativado", False)
            no.setdefault("executar_uma_vez", False)
            no.setdefault("em_erro", "parar")
            if no.get("tipo") == "http" and isinstance(no.get("config"), dict):
                no["config"] = _config_http(no["config"])
    if isinstance(novo.get("arestas"), list):
        for aresta in novo["arestas"]:
            if isinstance(aresta, dict):
                aresta.setdefault("saida", 0)
                aresta.setdefault("entrada", 0)
    return novo


def para_v2(grafo):
    """Converte se for v1; v2 (ou lixo) volta inalterado (mesmo objeto)."""
    if (
        isinstance(grafo, dict)
        and grafo.get("versao") == 1
        and not isinstance(grafo.get("versao"), bool)
    ):
        return migrar_v1_para_v2(grafo)
    return grafo
