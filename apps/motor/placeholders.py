"""Placeholders `{{ anterior.<caminho> }}` (PLH-01..04), com parser próprio e restrito.

Sem eval, exec, engine de template nem getattr: o caminho só indexa dicts (por chave) e listas
(por índice numérico) da saída do nó anterior. Qualquer coisa dentro de `{{ ... }}` que não seja
exatamente `anterior.<segmentos>` é erro do nó (categoria `placeholder`).

Inserção segura por contexto (PLH-04):
- URL: valor percent-encoded (não injeta `/`, `?`, `#`, `@`);
- header/query (nome e valor): texto; CR/LF é recusado;
- corpo JSON: escapado como conteúdo de string JSON (só vale dentro de valores string).
Objetos e listas viram JSON compacto.
"""

import json
import re
from urllib.parse import quote

CATEGORIA = "placeholder"
MAX_RESOLVIDO = 1_000_000  # caracteres por texto resolvido (evita explosão por repetição)

_BLOCO = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
_CAMINHO = re.compile(r"[ \t]*anterior((?:\.[A-Za-z0-9_-]+)+)[ \t]*")


class ErroPlaceholder(Exception):
    """Erro de placeholder: `categoria` fixa e `mensagem` própria (nunca texto de exceção)."""

    categoria = CATEGORIA

    def __init__(self, mensagem):
        super().__init__(mensagem)
        self.mensagem = mensagem


def _resumo(trecho):
    trecho = " ".join(trecho.split())
    return trecho if len(trecho) <= 60 else trecho[:57] + "..."


def tem_placeholder(texto):
    return isinstance(texto, str) and _BLOCO.search(texto) is not None


def resolver_caminho(anterior, caminho):
    """Valor em `anterior` para `a.b.0.c` (sem o prefixo `anterior.`). Erro se não existir."""
    atual = anterior
    for segmento in caminho.split("."):
        if isinstance(atual, dict) and segmento in atual:
            atual = atual[segmento]
        elif isinstance(atual, list) and segmento.isdigit() and int(segmento) < len(atual):
            atual = atual[int(segmento)]
        else:
            raise ErroPlaceholder(f"Caminho inexistente: anterior.{caminho}")
    return atual


def como_texto(valor):
    """Texto de um valor resolvido: string como está; objetos e listas em JSON compacto."""
    if isinstance(valor, str):
        return valor
    try:
        return json.dumps(valor, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except ValueError:
        raise ErroPlaceholder("O valor resolvido não pode ser escrito como JSON.") from None


def _substituir(texto, anterior, formatar):
    saida, posicao = [], 0
    for achado in _BLOCO.finditer(texto):
        corresponde = _CAMINHO.fullmatch(achado.group(1))
        if corresponde is None:
            raise ErroPlaceholder(f"Placeholder inválido: {{{{{_resumo(achado.group(1))}}}}}")
        valor = como_texto(resolver_caminho(anterior, corresponde.group(1)[1:]))
        saida.append(texto[posicao : achado.start()])
        saida.append(formatar(valor))
        posicao = achado.end()
    saida.append(texto[posicao:])
    resultado = "".join(saida)
    if len(resultado) > MAX_RESOLVIDO:
        raise ErroPlaceholder("O valor resolvido é grande demais.")
    return resultado


def _sem_quebra(valor):
    if "\r" in valor or "\n" in valor:
        raise ErroPlaceholder(
            "O valor contém quebra de linha e não pode ir em cabeçalho ou parâmetro."
        )
    return valor


def _como_conteudo_de_string_json(valor):
    return json.dumps(valor, ensure_ascii=False)[1:-1]


def resolver_url(texto, anterior):
    return _substituir(texto, anterior, lambda valor: quote(valor, safe=""))


def resolver_valor(texto, anterior):
    """Nomes e valores de headers e query."""
    return _substituir(texto, anterior, _sem_quebra)


def resolver_corpo(texto, anterior):
    return _substituir(texto, anterior, _como_conteudo_de_string_json)
