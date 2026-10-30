"""Recebimentos do n8n (D-048): API de entrada → fila de aprovação → cadastro por CNJ.

O n8n trata o e-mail das intimações/citações e manda a lista de itens (JSON) para a API. Cada item
vira um `Recebimento` pendente; repetido (mesmo conteúdo, ex.: o n8n reenviou) é ignorado. Quem
tem `cadastro.aprovar` aprova (vira item de um Envio por CNJ, a mesma fila do "Cadastrar pelo
CNJ") ou descarta. Só itens com número CNJ válido podem ser aprovados.
"""

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import date, datetime, time

from django.db import transaction
from django.utils import timezone

from . import cnj
from .models import ConfigCadastro, Envio, ItemEnvio, Recebimento

MAX_ITENS = 500
MAX_BYTES = 2 * 1024 * 1024
PREFIXO_CHAVE = "cwj_"
SESSAO_CHAVE_NOVA = "juridico_chave_api_nova"  # a chave recém-gerada, exibida uma vez
# Campos que mudam com a posição no e-mail; não entram na identidade do item.
# `email` (D-059/D-060) fica fora: o mesmo registro pela API ou pela importação manual é um item só.
VOLATEIS = ("linha", "tabela", "linhas_mesmo_processo", "email")

ALERTAS = {
    "processo_repetido_no_email": "Processo repetido no e-mail",
    "uf_inferida_do_processo": "UF deduzida do número",
    "processo_invalido": "Número inválido",
    "uf_diferente_do_tribunal_do_processo": "UF diferente do tribunal",
    "data_nao_reconhecida": "Data não reconhecida",
    "sem_processo": "Sem número de processo",
}
ALERTAS_GRAVES = {"processo_invalido", "sem_processo"}


# ------------------------------------------------------------------ chave da API
def _resumo(chave):
    return hashlib.sha256(chave.encode()).hexdigest()


def gerar_chave():
    """Gera e guarda uma chave nova (a anterior deixa de valer). Devolve o valor, uma única vez."""
    chave = PREFIXO_CHAVE + secrets.token_urlsafe(32)
    config = ConfigCadastro.obter()
    config.api_chave_hash = _resumo(chave)
    config.api_chave_inicio = chave[:10]
    config.api_chave_criada_em = timezone.now()
    config.save(update_fields=["api_chave_hash", "api_chave_inicio", "api_chave_criada_em"])
    return chave


def chave_confere(chave):
    """None se não há chave configurada; senão True/False (comparação em tempo constante)."""
    esperado = ConfigCadastro.obter().api_chave_hash
    if not esperado:
        return None
    return bool(chave) and hmac.compare_digest(_resumo(chave), esperado)


def chave_do_pedido(request):
    """`Authorization: Bearer <chave>` ou `X-Api-Key: <chave>`."""
    autorizacao = request.headers.get("authorization", "")
    if autorizacao[:7].lower() == "bearer ":
        return autorizacao[7:].strip()
    return request.headers.get("x-api-key", "").strip()


# ------------------------------------------------------------------ leitura do item
def _texto(valor, limite):
    if valor is None or isinstance(valor, (dict, list)):
        return ""
    return str(valor).strip()[:limite]


def _data(valor):
    try:
        return date.fromisoformat(str(valor)[:10]) if valor else None
    except ValueError:
        return None


def _hora(valor):
    try:
        return time.fromisoformat(str(valor)[:8]) if valor else None
    except ValueError:
        return None


def chave_do_item(item):
    estavel = {k: v for k, v in item.items() if k not in VOLATEIS}
    texto = json.dumps(estavel, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(texto.encode()).hexdigest()


def montar(item, lote):
    """Recebimento (não salvo) a partir de um item do n8n. O número é validado aqui (dígito
    verificador), não confiamos no `processo_valido` que veio."""
    digitos = cnj.so_digitos(_texto(item.get("processo"), 60))
    valido = cnj.valido(digitos)
    alertas = [a for a in item.get("alertas") or [] if isinstance(a, str)][:20]
    if digitos and not valido and "processo_invalido" not in alertas:
        alertas.append("processo_invalido")
    if not digitos and "sem_processo" not in alertas:
        alertas.append("sem_processo")
    outras = item.get("outras_colunas") if isinstance(item.get("outras_colunas"), dict) else {}
    return Recebimento(
        lote=lote,
        chave=chave_do_item(item),
        numero=cnj.formatar(digitos) if len(digitos) == 20 else _texto(item.get("processo"), 40),
        numero_digitos=digitos[:20],
        numero_valido=valido,
        tipo=_texto(item.get("tipo_padronizado") or item.get("tipo"), 300),
        remetente=_texto(item.get("remetente"), 300),
        remetente_sigla=_texto(item.get("remetente_sigla"), 30),
        origem=_texto(item.get("origem"), 30),
        numero_controle=_texto(item.get("numero_controle"), 60),
        cliente=_texto(item.get("cliente"), 300),
        uf=_texto(item.get("uf"), 2).upper(),
        tribunal=_texto(item.get("processo_tribunal"), 30),
        data=_data(item.get("data")),
        hora=_hora(item.get("hora")),
        motivo=_texto(item.get("motivo"), 300),
        prazo=_texto(outras.get("PRAZO") or outras.get("prazo"), 100),
        alertas=alertas,
        dados=item,
    )


def extrair_itens(corpo):
    """Lista de itens do corpo, ou None se o formato não for reconhecido. Aceita (D-059):
    a lista de itens; {"itens": [...]}; o envelope do n8n {"email", "resumo", "registros": [...]}
    sozinho ou numa lista de envelopes. Cada registro de um envelope leva junto o `email` (assunto,
    remetente, data), para rastrear de onde veio."""
    if isinstance(corpo, dict):
        if isinstance(corpo.get("itens"), list):
            return corpo["itens"]
        corpo = [corpo] if isinstance(corpo.get("registros"), list) else None
    if not isinstance(corpo, list):
        return None
    if not corpo or not all(
        isinstance(e, dict) and isinstance(e.get("registros"), list) for e in corpo
    ):
        return corpo
    itens = []
    for envelope in corpo:
        email = envelope.get("email") if isinstance(envelope.get("email"), dict) else None
        for registro in envelope["registros"]:
            itens.append(
                {**registro, "email": email} if isinstance(registro, dict) and email else registro
            )
    return itens


def registrar(itens):
    """Grava os itens válidos como pendentes. Devolve {lote, recebidos, novos, repetidos,
    invalidos: [{indice, mensagem}]}."""
    lote, agora = uuid.uuid4(), timezone.now()  # mesmo instante: a lista segue a ordem do n8n
    invalidos, novos, chaves = [], [], set()
    for indice, item in enumerate(itens):
        if not isinstance(item, dict):
            invalidos.append({"indice": indice, "mensagem": "O item precisa ser um objeto JSON."})
            continue
        recebimento = montar(item, lote)
        recebimento.recebido_em = agora
        if recebimento.chave in chaves:
            continue  # repetido dentro do mesmo envio
        chaves.add(recebimento.chave)
        novos.append(recebimento)
    ja_existem = set(Recebimento.objects.filter(chave__in=chaves).values_list("chave", flat=True))
    a_gravar = [r for r in novos if r.chave not in ja_existem]
    Recebimento.objects.bulk_create(a_gravar, ignore_conflicts=True)
    validos = len(itens) - len(invalidos)
    return {
        "lote": str(lote),
        "recebidos": len(itens),
        "novos": len(a_gravar),
        "repetidos": validos - len(a_gravar),
        "invalidos": invalidos,
    }


# ------------------------------------------------------------------ decisão
@transaction.atomic
def aprovar(usuario, ids, carteira=None):
    """Aprova os pendentes de `ids` com número válido: um Envio por CNJ, um item por número
    (repetidos do mesmo número apontam para o mesmo item). Devolve (envio | None, números na
    fila, ignorados: pendentes sem número válido)."""
    pendentes = list(
        Recebimento.objects.select_for_update()
        .filter(pk__in=ids, status=Recebimento.PENDENTE)
        .order_by("pk")
    )
    aprovaveis = [r for r in pendentes if r.numero_valido]
    if not aprovaveis:
        return None, 0, len(pendentes)
    envio = Envio.objects.create(origem=Envio.CNJ, enviado_por=usuario, carteira=carteira)
    agora, por_numero = timezone.now(), {}
    for r in aprovaveis:
        if r.numero_digitos not in por_numero:
            por_numero[r.numero_digitos] = ItemEnvio.objects.create(
                envio=envio, numero_informado=r.numero_digitos
            )
        r.status, r.decidido_por, r.decidido_em = Recebimento.APROVADO, usuario, agora
        r.item_envio = por_numero[r.numero_digitos]
    Recebimento.objects.bulk_update(
        aprovaveis, ["status", "decidido_por", "decidido_em", "item_envio"]
    )
    return envio, len(por_numero), len(pendentes) - len(aprovaveis)


def descartar(usuario, ids, motivo=""):
    """Descarta os pendentes de `ids`. Devolve quantos."""
    return Recebimento.objects.filter(pk__in=ids, status=Recebimento.PENDENTE).update(
        status=Recebimento.DESCARTADO,
        decidido_por=usuario,
        decidido_em=timezone.now(),
        motivo_descarte=(motivo or "").strip()[:300],
    )


def total_pendentes():
    return Recebimento.objects.filter(status=Recebimento.PENDENTE).count()


def rotulo_alerta(codigo):
    return ALERTAS.get(codigo) or codigo.replace("_", " ").capitalize()


def quando(recebimento):
    """Data/hora do aviso no tribunal (o que veio do n8n), para exibir."""
    if recebimento.data is None:
        return ""
    if recebimento.hora is None:
        return recebimento.data.strftime("%d/%m/%Y")
    return datetime.combine(recebimento.data, recebimento.hora).strftime("%d/%m/%Y %H:%M")
