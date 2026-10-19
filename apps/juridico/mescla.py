"""Mesclagem PDF > manual > CNJ (CAD-11), pendências/status (CAD-12), audiências (CAD-20) e
comparação com o DataJud (CAD-10, CAD-23 §6). Funções sobre `Processo` sem tocar rede."""

import re
from datetime import date, datetime

from django.utils import timezone

from . import apresentacao, cnj
from .models import CAMPOS_LONGOS, CAMPOS_MANUAIS, CAMPOS_TEXTO, Processo

CAMPOS_DADOS = tuple(
    c for c in (*CAMPOS_TEXTO, *CAMPOS_LONGOS) if c not in CAMPOS_MANUAIS and c != "observacoes"
) + ("fase_atual", "distribuido_em", "data_citacao", "valor_causa")
OBRIGATORIOS = (
    ("numero", "Número"),
    ("tribunal", "Tribunal"),
    ("comarca", "Comarca"),
    ("juizo", "Juízo"),
    ("adverso_nome", "Adverso"),
    ("valor_causa", "Valor da causa"),
    ("distribuido_em", "Distribuído em"),
)
PREFIXOS_FIXOS = ("Valor da causa ilegível:",)
MSG_DV = "Número CNJ com dígito verificador inválido: confira no PDF."


def _vazio(valor):
    return valor is None or valor == "" or valor == []


# ---------------------------------------------------------------- mesclagem
def aplicar_pdf(processo, campos, quando=None):
    """O PDF substitui todo campo que trouxer preenchido e diferente. Devolve os campos mudados."""
    quando = quando or timezone.now()
    mudou = []
    for campo in CAMPOS_DADOS:
        novo = campos.get(campo)
        if _vazio(novo) or getattr(processo, campo) == novo:
            continue
        setattr(processo, campo, novo)
        processo.origem_campos[campo] = "pdf"
        mudou.append(campo)
    processo.andamentos = juntar_andamentos(
        processo.andamentos, campos.get("andamentos") or [], "pdf"
    )
    if mudou and processo.pk:  # processo já existia: anota a mudança (observações manuais ficam)
        linha = (
            f"Atualizado pelo PDF em {timezone.localtime(quando):%d/%m/%Y %H:%M}: "
            + ", ".join(_rotulo(c) for c in mudou)
            + "."
        )
        processo.observacoes = f"{processo.observacoes}\n{linha}".strip()
    elif not processo.pk and campos.get("observacoes"):
        processo.observacoes = campos["observacoes"]
        processo.origem_campos["observacoes"] = "pdf"
    return mudou


def aplicar_cnj(processo, campos):
    """O CNJ SÓ preenche campo vazio (nunca sobrescreve PDF nem edição manual)."""
    mudou = []
    for campo, novo in campos.items():
        if campo in ("andamentos",) or _vazio(novo):
            continue
        if _vazio(getattr(processo, campo, None)):
            setattr(processo, campo, novo)
            processo.origem_campos[campo] = "cnj"
            mudou.append(campo)
    processo.andamentos = juntar_andamentos(
        processo.andamentos, campos.get("andamentos") or [], "cnj"
    )
    return mudou


def juntar_andamentos(atuais, novos, fonte):
    """Sem repetir (mesma data e texto), ordem decrescente; PDF até 5 e CNJ os 15 mais recentes."""
    limites = {"pdf": 5, "cnj": 15}
    chave = lambda a: (a.get("data", ""), (a.get("evento") or "").strip().lower())  # noqa: E731
    mesma_fonte = [a for a in atuais if a.get("fonte") == fonte]
    outras = [a for a in atuais if a.get("fonte") != fonte]
    candidatos = sorted([*novos, *mesma_fonte], key=lambda a: a.get("data", ""), reverse=True)
    recortados, vistos = [], set()
    for andamento in candidatos:
        if chave(andamento) in vistos:
            continue
        vistos.add(chave(andamento))
        recortados.append(andamento)
    recortados = recortados[: limites[fonte]]
    final, vistos = [], set()
    for andamento in sorted([*outras, *recortados], key=lambda a: a.get("data", ""), reverse=True):
        if chave(andamento) not in vistos:
            vistos.add(chave(andamento))
            final.append(andamento)
    return final


def _rotulo(campo):
    return Processo._meta.get_field(campo).verbose_name.capitalize()


# ---------------------------------------------------------------- pendências e status
def recalcular(processo):
    """Pendências e status (CAD-12). CADASTRADO nunca volta sozinho."""
    pendencias = []
    if not processo.numero_valido and processo.numero:
        pendencias.append(MSG_DV)
    pendencias += [
        p
        for p in processo.pendencias
        if p.startswith(PREFIXOS_FIXOS) and processo.valor_causa is None
    ]
    if processo.criado_via == Processo.PDF and processo.carteira_id is None:
        pendencias.append("Carteira não identificada.")
    faltando = [rotulo for campo, rotulo in OBRIGATORIOS if _vazio(getattr(processo, campo))]
    if faltando:
        pendencias.append("Verificar: " + ", ".join(faltando))
    pendencias += [f"Divergência com o CNJ: {d}" for d in processo.cnj_divergencias]
    processo.pendencias = pendencias
    if processo.status != Processo.CADASTRADO:
        processo.status = Processo.COM_PENDENCIAS if pendencias else Processo.CONFERIR
    return faltando


def faltando_obrigatorios(processo):
    return [rotulo for campo, rotulo in OBRIGATORIOS if _vazio(getattr(processo, campo))]


# ---------------------------------------------------------------- audiências (CAD-20)
_RE_AUDIENCIA = re.compile(
    r"audi[eê]ncia[^.\n]{0,160}?(?:designada|marcada|redesignada)\s+para\s+(?:o\s+dia\s+)?"
    r"(\d{1,2})/(\d{1,2})/(\d{4})\s*,?\s*(?:[àa]s\s*)?(\d{1,2})\s*(?:[:h])\s*(\d{2})?",
    re.IGNORECASE,
)


def extrair_audiencia(processo, agora=None):
    """Próxima audiência futura mais próxima, extraída do texto das observações e andamentos."""
    agora = agora or timezone.now()
    fuso = timezone.get_current_timezone()
    textos = [processo.observacoes or "", *[a.get("evento", "") for a in processo.andamentos]]
    achadas = []
    for texto in textos:
        for dia, mes, ano, hora, minuto in _RE_AUDIENCIA.findall(texto):
            try:
                quando = datetime(int(ano), int(mes), int(dia), int(hora), int(minuto or 0))
            except ValueError:
                continue
            quando = timezone.make_aware(quando, fuso)
            if quando >= agora:
                achadas.append(quando)
    return min(achadas) if achadas else None


def atualizar_audiencia(processo, agora=None):
    if processo.origem_campos.get("proxima_audiencia") == "manual":
        return
    processo.proxima_audiencia = extrair_audiencia(processo, agora)


# ---------------------------------------------------------------- DataJud
def _data_iso(texto):
    achado = re.match(r"(\d{4})-(\d{2})-(\d{2})", texto or "") or re.match(
        r"(\d{4})(\d{2})(\d{2})", texto or ""
    )
    if not achado:
        return None
    try:
        return date(*(int(g) for g in achado.groups()))
    except ValueError:
        return None


def campos_do_datajud(fonte, alias):
    """Campos do modelo a partir do `_source` do DataJud (só o que o CNJ traz: sem partes/valor)."""
    orgao = (fonte.get("orgaoJulgador") or {}).get("nome") or ""
    comarca = re.search(r"comarca\s+d[aeo]s?\s+(.+)$", orgao, re.IGNORECASE)
    grau = str(fonte.get("grau") or "").upper()
    movimentos = [m for m in (fonte.get("movimentos") or []) if isinstance(m, dict)]
    movimentos.sort(key=lambda m: str(m.get("dataHora") or ""), reverse=True)
    andamentos = []
    for m in movimentos[:15]:
        quando = _data_iso(str(m.get("dataHora") or ""))
        andamentos.append(
            {
                "data": quando.isoformat() if quando else "",
                "evento": str(m.get("nome") or ""),
                "fonte": "cnj",
            }
        )
    assuntos = [
        str(a.get("nome"))
        for a in (fonte.get("assuntos") or [])
        if isinstance(a, dict) and a.get("nome")
    ]
    return {
        "tipo_acao": str((fonte.get("classe") or {}).get("nome") or ""),
        "juizo": orgao,
        "comarca": comarca.group(1).strip() if comarca else "",
        "instancia": {"G1": "1° Grau de Jurisdição", "G2": "2° Grau de Jurisdição"}.get(grau, ""),
        "tribunal": str(fonte.get("tribunal") or alias.replace("-", "").upper()),
        "distribuido_em": _data_iso(str(fonte.get("dataAjuizamento") or "")),
        "meio_tramitacao": "Eletrônico"
        if (fonte.get("formato") or {}).get("nome", "").lower().startswith("eletr")
        else "",
        "assuntos_cnj": "; ".join(assuntos),
        "andamentos": andamentos,
        "fase_atual": _fase_dos_movimentos(movimentos),
    }


def _fase_dos_movimentos(movimentos):
    """Estimativa provisória (D-034): do movimento mais recente para o mais antigo."""
    for m in movimentos:
        nome = cnj.sem_acento(str(m.get("nome") or ""))
        if "arquiv" in nome or "baixa" in nome:
            return "ARQUIVADO"
        if "execu" in nome or "cumprimento" in nome:
            return "EXECUCAO_CUMPRIMENTO"
        if "recurso" in nome or "apelacao" in nome:
            return "RECURSAL"
        if "sentenca" in nome:
            return "DECISORIA"
    return None


def _so_letras(texto):
    return re.sub(r"[^a-z ]", "", cnj.sem_acento(texto)).strip()


def comparar(processo, fonte):
    """Divergências entre o que o PDF trouxe e o `_source` do DataJud (CAD-23 §6)."""
    divergencias = []
    pdf_trib = re.sub(r"[\s.\-]", "", processo.tribunal or "").upper()
    cnj_trib = re.sub(r"[\s.\-]", "", str(fonte.get("tribunal") or "")).upper()
    if pdf_trib and cnj_trib and pdf_trib != cnj_trib:
        divergencias.append(f"tribunal (PDF: {processo.tribunal} · CNJ: {fonte.get('tribunal')})")
    data_cnj = _data_iso(str(fonte.get("dataAjuizamento") or ""))
    if processo.distribuido_em and data_cnj and processo.distribuido_em != data_cnj:
        divergencias.append(
            f"distribuído em (PDF: {apresentacao.data(processo.distribuido_em)} · "
            f"CNJ: {apresentacao.data(data_cnj)})"
        )
    orgao = (fonte.get("orgaoJulgador") or {}).get("nome") or ""
    comarca = _so_letras(processo.comarca or "")
    if comarca and orgao and comarca not in _so_letras(orgao):
        divergencias.append(f"comarca (PDF: {processo.comarca} · CNJ: {orgao})")
    return divergencias
