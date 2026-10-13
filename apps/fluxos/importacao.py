"""Importação de fluxos (IMP-01..05, SEG-19, MV2-18 C6–C9): formato nativo e n8n.

JSON externo é DADO NÃO CONFIÁVEL: validação fechada, limite de 2 MB, Código entra desativado,
segredos viram `{{ $credencial }}` (com pendência) e nenhum campo do arquivo escolhe dono, setor,
id ou status do fluxo criado. Nada aqui toca o banco: devolve `(nome, descricao, grafo, relatorio)`.
"""

import json
import re

from apps.motor.expressoes import analisar, expressoes_do_texto

from . import n8n
from .grafo import MARCA_CREDENCIAL, normalizar, validar

LIMITE_BYTES = 2 * 1024 * 1024
NOME_PADRAO = "Fluxo importado"
CHAVES_NATIVO = {"formato", "versao", "fluxo", "grafo", "credenciais_usadas"}
CHAVES_NATIVO_FLUXO = {"nome", "descricao"}
LISTAS_AVISO = (
    "ajustes",
    "sem_equivalente",
    "expressoes_nao_suportadas",
    "segredos",
    "codigo_desativado",
)

_JWT = re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]*")
_BEARER = re.compile(r"Bearer [A-Za-z0-9._~+/=-]{20,}")
_CHAVE = re.compile(r"[A-Za-z0-9_-]{32,}")
_LITERAL_DE_CODIGO = re.compile(r"""(['"`])([A-Za-z0-9_-]{32,})\1""")


class ErroImportacao(Exception):
    """Arquivo recusado (nada é criado). `mensagem` é própria e segura para mostrar."""

    def __init__(self, mensagem):
        super().__init__(mensagem)
        self.mensagem = mensagem


def relatorio_vazio():
    return {
        "importados": [],
        "ajustes": [],
        "sem_equivalente": [],
        "expressoes_nao_suportadas": [],
        "segredos": [],
        "codigo_desativado": [],
    }


def total_de_avisos(relatorio):
    return sum(len(relatorio.get(chave, [])) for chave in LISTAS_AVISO)


# ---------------------------------------------------------------- leitura do arquivo
def _recusar_constante(nome):
    raise ValueError(nome)


def ler_json(conteudo):
    """Bytes → objeto JSON (dict). Recusa vazio, > 2 MB, não-UTF-8, NaN/Infinity e aninhamento."""
    if not conteudo:
        raise ErroImportacao("o arquivo está vazio")
    if len(conteudo) > LIMITE_BYTES:
        raise ErroImportacao("o arquivo passa de 2 MB")
    try:
        dados = json.loads(conteudo.decode("utf-8"), parse_constant=_recusar_constante)
    except ValueError, RecursionError:
        raise ErroImportacao("o arquivo não é um JSON válido") from None
    if not isinstance(dados, dict):
        raise ErroImportacao("o arquivo precisa ser um objeto JSON")
    return dados


# ---------------------------------------------------------------- segredos (IMP-04, C7)
def _trocar_em_texto(texto, codigo):
    """(novo texto, achou). Em código, só o trecho do valor dentro das aspas é trocado."""
    if codigo:
        achou = False

        def literal(m):
            nonlocal achou
            achou = True
            return f"{m.group(1)}{MARCA_CREDENCIAL}{m.group(1)}"

        novo = _LITERAL_DE_CODIGO.sub(literal, texto)
        for padrao in (_JWT, _BEARER):
            novo, n = padrao.subn(MARCA_CREDENCIAL, novo)
            achou = achou or n > 0
        return novo, achou
    if _CHAVE.fullmatch(texto):
        return MARCA_CREDENCIAL, True
    achou = False
    for padrao in (_JWT, _BEARER):
        texto, n = padrao.subn(MARCA_CREDENCIAL, texto)
        achou = achou or n > 0
    return texto, achou


def _varrer(valor, codigo, achados):
    if isinstance(valor, str):
        novo, achou = _trocar_em_texto(valor, codigo)
        if achou:
            achados.append(True)
        return novo
    if isinstance(valor, list):
        return [_varrer(v, codigo, achados) for v in valor]
    if isinstance(valor, dict):
        return {k: _varrer(v, codigo, achados) for k, v in valor.items()}
    return valor


def trocar_segredos(no, relatorio):
    """Substitui segredos na config do nó (sem deixar o original em lugar nenhum) e registra."""
    config = no["config"]
    for chave in list(config):
        achados = []
        config[chave] = _varrer(
            config[chave], no["tipo"] == "codigo" and chave == "codigo", achados
        )
        for _ in achados:
            relatorio["segredos"].append({"no": no["titulo"], "campo": chave})


def _textos(valor, caminho):
    if isinstance(valor, str):
        yield caminho, valor
    elif isinstance(valor, list):
        for i, v in enumerate(valor):
            yield from _textos(v, f"{caminho}[{i}]")
    elif isinstance(valor, dict):
        for k, v in valor.items():
            yield from _textos(v, f"{caminho}.{k}" if caminho else k)


def marcar_expressoes(no, relatorio):
    """Expressões fora do subconjunto (MV2-10) vão para o relatório; o texto fica como está."""
    for caminho, texto in _textos(no["config"], ""):
        if caminho == "codigo" or MARCA_CREDENCIAL in texto:
            continue
        for fonte in expressoes_do_texto(texto):
            if analisar(fonte) is not None:
                relatorio["expressoes_nao_suportadas"].append(
                    {"no": no["titulo"], "campo": caminho, "expressao": fonte.strip()[:300]}
                )


def desativar_codigo(grafo, relatorio):
    for no in grafo["nos"]:
        if no["tipo"] == "codigo":
            no["desativado"] = True
            relatorio["codigo_desativado"].append(no["titulo"])


# ---------------------------------------------------------------- nativo
def _importar_nativo(dados):
    extras = set(dados) - CHAVES_NATIVO
    if extras:
        raise ErroImportacao("o arquivo tem campos que o formato não permite")
    if dados.get("versao") != 2 or isinstance(dados.get("versao"), bool):
        raise ErroImportacao("a versão do arquivo não é suportada")
    fluxo = dados.get("fluxo")
    if not isinstance(fluxo, dict) or set(fluxo) - CHAVES_NATIVO_FLUXO:
        raise ErroImportacao("o arquivo tem campos que o formato não permite")
    nome, descricao = fluxo.get("nome", ""), fluxo.get("descricao", "")
    if not isinstance(nome, str) or not isinstance(descricao, str):
        raise ErroImportacao("nome ou descrição inválidos")
    erros, _ = validar(dados.get("grafo"))
    if erros:
        raise ErroImportacao("o grafo do arquivo é inválido")
    grafo = normalizar(dados["grafo"])
    relatorio = relatorio_vazio()
    relatorio["importados"] = [no["titulo"] for no in grafo["nos"]]
    for no in grafo["nos"]:
        trocar_segredos(no, relatorio)
    desativar_codigo(grafo, relatorio)
    return nome, descricao, grafo, relatorio


def importar(conteudo):
    """Bytes do arquivo → `(nome, descricao, grafo, relatorio)`; `ErroImportacao` se recusado."""
    dados = ler_json(conteudo)
    if dados.get("formato") is not None:
        if dados["formato"] != "construtor-workflows":
            raise ErroImportacao("o formato do arquivo não é reconhecido")
        nome, descricao, grafo, relatorio = _importar_nativo(dados)
    elif "nodes" in dados:
        nome, descricao, grafo, relatorio = n8n.importar(dados)
    else:
        raise ErroImportacao("o formato do arquivo não é reconhecido")
    erros, _ = validar(grafo)
    if erros:
        raise ErroImportacao("o fluxo resultante é inválido")
    nome = (nome or "").strip()[:120] or NOME_PADRAO
    return nome, (descricao or "")[:1000], grafo, relatorio
