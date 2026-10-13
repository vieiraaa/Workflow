"""Uso de credenciais pelos nós (CRD-02, SEG-18). Tudo vira `FalhaNo("credencial", ...)`."""

import base64

from django.db.models import Q

from apps.credenciais import cofre
from apps.credenciais.models import Credencial

from .erros import FalhaNo


def carregar(nome, setor_id, tipos_aceitos):
    """Credencial `nome` (sem diferenciar maiúsculas) visível ao setor do fluxo, já decifrada.

    Devolve `(tipo, dados)`. Levanta `FalhaNo("credencial")` se não existe, é de outro setor, é de
    tipo que o nó não aceita ou o cofre não consegue abri-la (sem chave / chave diferente).
    """
    credencial = Credencial.objects.filter(nome__iexact=str(nome).strip()).first()
    if credencial is None or (credencial.setor_id is not None and credencial.setor_id != setor_id):
        raise FalhaNo("credencial", "Credencial não encontrada para este fluxo.")
    if credencial.tipo not in tipos_aceitos:
        raise FalhaNo(
            "credencial", f"Credencial do tipo {credencial.tipo_rotulo} não serve para este nó."
        )
    try:
        return credencial.tipo, credencial.dados()
    except cofre.ErroCofre as erro:
        raise FalhaNo("credencial", erro.mensagem) from None


def cabecalho_http(tipo, dados):
    """(nome, valor, segredos) do header que a credencial injeta no nó HTTP."""
    valor = dados.get("valor", "")
    if tipo == Credencial.BEARER:
        return "Authorization", f"Bearer {valor}", {valor}
    if tipo == Credencial.HEADER:
        return dados.get("header_nome") or "X-Api-Key", valor, {valor}
    basico = base64.b64encode(f"{dados.get('usuario', '')}:{valor}".encode()).decode()
    return "Authorization", f"Basic {basico}", {valor, basico}


def segredos_do_setor(setor_id):
    """Valores de todas as credenciais visíveis ao setor (para mascarar o que é gravado)."""
    segredos = set()
    for credencial in Credencial.objects.filter(Q(setor__isnull=True) | Q(setor_id=setor_id)):
        try:
            segredos |= cabecalho_http(credencial.tipo, credencial.dados())[2]
        except cofre.ErroCofre, KeyError, TypeError, AttributeError:
            continue
    return {s for s in segredos if isinstance(s, str) and len(s) >= 4}
