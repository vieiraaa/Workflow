"""Leitura da resposta do Dify (CAD-08, CAD-23 §1): `answer` → campos do modelo + pendências.

O texto vindo da IA é DADO: nunca é avaliado, só parseado como JSON e copiado como texto.
"""

import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from apps.motor.http import aninhamento_excede

MSG_FORMATO = "A IA não devolveu os dados no formato esperado."
MSG_SEM_DADOS = "A IA não encontrou dados de processo neste PDF (talvez não seja um processo)."
MAX_ANINHAMENTO = 20
CANONICAS = (
    "numero_cnj", "numero_contrato_operacao", "empresa", "condicao", "advogado_empresa",
    "adverso_nome", "adverso_cpf_cnpj", "advogado_adverso_nome", "advogado_adverso_oab",
    "tipo_acao", "rito", "natureza", "meio_tramitacao", "instancia", "distribuido_em",
    "tribunal", "juizo", "comarca", "estado", "desdobramento", "fase_atual", "data_citacao",
    "valor_causa", "pedidos_completos", "ultimas_movimentacoes", "observacoes",
)  # fmt: skip
ALTERNATIVAS = {
    "numero_processo": "numero_cnj", "numero": "numero_cnj",
    "adverso": "adverso_nome", "parte_adversa": "adverso_nome",
    "cpf_cnpj_adverso": "adverso_cpf_cnpj", "adverso_cpf": "adverso_cpf_cnpj",
    "adverso_cnpj": "adverso_cpf_cnpj",
    "advogado_adverso": "advogado_adverso_nome", "oab_advogado_adverso": "advogado_adverso_oab",
    "classe": "tipo_acao", "classe_acao": "tipo_acao",
    "valor_da_causa": "valor_causa",
    "vara": "juizo", "orgao_julgador": "juizo",
    "pedidos": "pedidos_completos",
    "andamentos": "ultimas_movimentacoes", "movimentacoes": "ultimas_movimentacoes",
    "operacoes_vinculadas": "numero_contrato_operacao",
    "numero_contrato": "numero_contrato_operacao",
    "contrato": "numero_contrato_operacao",
    "parte_empresa": "empresa", "polo_empresa": "condicao",
    "data_distribuicao": "distribuido_em",
}  # fmt: skip
PARA_MODELO = {
    "numero_cnj": "numero",
    "numero_contrato_operacao": "operacoes_vinculadas",
    "pedidos_completos": "pedidos",
}
FASES = {
    "POSTULATORIA": "POSTULATORIA",
    "INSTRUTORIA": "INSTRUTORIA",
    "DECISORIA": "DECISORIA",
    "RECURSAL": "RECURSAL",
    "EXECUCAOCUMPRIMENTO": "EXECUCAO_CUMPRIMENTO",
    "EXECUCAO": "EXECUCAO_CUMPRIMENTO",
    "CUMPRIMENTO": "EXECUCAO_CUMPRIMENTO",
    "SENTENCA": "DECISORIA",
    "ARQUIVADO": "ARQUIVADO",
}
_RE_VAZIO = re.compile(r"^n[aã]o\s+(localizad|encontrad|informad|consta)", re.IGNORECASE)
_RE_DATA = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


class ErroLeitura(Exception):
    def __init__(self, mensagem):
        super().__init__(mensagem)
        self.mensagem = mensagem


def chave_normal(chave):
    base = unicodedata.normalize("NFKD", str(chave)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", base.lower())


_POR_NORMAL = {chave_normal(c): c for c in CANONICAS}
_POR_NORMAL.update({chave_normal(a): c for a, c in ALTERNATIVAS.items()})


def extrair_json(answer):
    texto = re.sub(r"```(?:json|JSON)?", "", answer or "")
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fim <= inicio:
        raise ErroLeitura(MSG_FORMATO)
    trecho = texto[inicio : fim + 1]
    if aninhamento_excede(trecho, MAX_ANINHAMENTO):
        raise ErroLeitura(MSG_FORMATO)
    try:
        dados = json.loads(trecho)
    except ValueError, RecursionError:
        raise ErroLeitura(MSG_FORMATO) from None
    if not isinstance(dados, dict):
        raise ErroLeitura(MSG_FORMATO)
    return dados


def _texto(valor):
    if valor is None or isinstance(valor, dict | list):
        return ""
    texto = str(valor).replace("\x00", "").strip()
    return "" if _RE_VAZIO.match(texto) else texto


def converter_data(texto):
    achado = _RE_DATA.search(texto or "")
    if not achado:
        return None
    dia, mes, ano = (int(g) for g in achado.groups())
    try:
        return date(ano, mes, dia)
    except ValueError:
        return None


def converter_valor(texto):
    """'R$ 1.234,56' → Decimal; None se ilegível."""
    limpo = re.sub(r"[^\d,.\-]", "", texto or "")
    if not limpo:
        return None
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif limpo.count(".") > 1 or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", limpo):
        limpo = limpo.replace(".", "")
    try:
        valor = Decimal(limpo).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return valor if abs(valor) < Decimal("1e12") else None


def converter_fase(texto):
    return FASES.get(chave_normal(texto).upper())


def _andamentos(valor):
    itens = []
    for bruto in (valor if isinstance(valor, list) else [])[:5]:
        if not isinstance(bruto, dict):
            continue
        evento = _texto(bruto.get("evento"))
        quando = converter_data(_texto(bruto.get("data")))
        if evento or quando:
            itens.append(
                {"data": quando.isoformat() if quando else "", "evento": evento, "fonte": "pdf"}
            )
    return itens


def ler_resposta(answer):
    """(campos do modelo, pendências) do `answer` do Dify; `ErroLeitura` se inutilizável."""
    bruto = extrair_json(answer)
    canonico = {}
    for chave, valor in bruto.items():
        destino = _POR_NORMAL.get(chave_normal(chave))
        if destino and destino not in canonico:
            canonico[destino] = valor
    pendencias, campos = [], {}
    for chave in CANONICAS:
        if chave in ("ultimas_movimentacoes",):
            continue
        campos[chave] = _texto(canonico.get(chave))
    preenchidos = sum(1 for c, v in campos.items() if v and c != "observacoes")
    if preenchidos < 3:
        raise ErroLeitura(MSG_SEM_DADOS)
    saida = {}
    for chave, valor in campos.items():
        saida[PARA_MODELO.get(chave, chave)] = valor
    saida["distribuido_em"] = converter_data(campos["distribuido_em"])
    saida["data_citacao"] = converter_data(campos["data_citacao"])
    saida["fase_atual"] = converter_fase(campos["fase_atual"]) if campos["fase_atual"] else None
    texto_valor = campos["valor_causa"]
    saida["valor_causa"] = converter_valor(texto_valor) if texto_valor else None
    if texto_valor and saida["valor_causa"] is None:
        pendencias.append(f"Valor da causa ilegível: {texto_valor[:80]}")
    saida["andamentos"] = _andamentos(canonico.get("ultimas_movimentacoes"))
    if saida["tribunal"]:
        saida["tribunal"] = saida["tribunal"].upper()
    return saida, pendencias


def normalizar_texto(texto):
    """Normalização da query (igual ao n8n): espaços/tabs → 1 espaço; quebras → 1 quebra; trim."""
    texto = re.sub(r"[ \t\f\v\r\xa0]+", " ", texto or "")
    texto = re.sub(r" ?\n[ \n]*", "\n", texto)
    return texto.strip()


def cortar(texto, maximo, inicio, fim):
    """Acima de `maximo` caracteres: primeiros `inicio` + marca + últimos `fim` (CAD-07)."""
    if len(texto) <= maximo:
        return texto
    return texto[:inicio] + "\n[... trecho do meio omitido ...]\n" + texto[-fim:]
