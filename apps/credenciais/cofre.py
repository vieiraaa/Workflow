"""Cofre de credenciais (CRD-01, SEG-18): cifra/decifra com Fernet.

A chave vem só de `settings.CREDENCIAIS_CHAVE` (ambiente; lida em runtime, vazia = ausente). O valor
em claro nunca é gravado, logado nem devolvido; as mensagens de erro são próprias (sem texto de
exceção da biblioteca) e sempre citam a chave para o Adm saber o que corrigir.
"""

import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

MSG_SEM_CHAVE = "A chave de credenciais (CREDENCIAIS_CHAVE) não está configurada no servidor."
MSG_CHAVE_INVALIDA = "A chave de credenciais configurada no servidor é inválida."
MSG_CHAVE_TROCADA = (
    "Não foi possível abrir a credencial: a chave de credenciais do servidor "
    "é diferente da que a cifrou."
)


class ErroCofre(Exception):
    """Falha do cofre; `mensagem` é própria e segura."""

    def __init__(self, mensagem):
        super().__init__(mensagem)
        self.mensagem = mensagem


def chave_configurada():
    return bool((getattr(settings, "CREDENCIAIS_CHAVE", "") or "").strip())


def _fernet():
    chave = (getattr(settings, "CREDENCIAIS_CHAVE", "") or "").strip()
    if not chave:
        raise ErroCofre(MSG_SEM_CHAVE)
    try:
        return Fernet(chave.encode())
    except ValueError, TypeError:
        raise ErroCofre(MSG_CHAVE_INVALIDA) from None


def cifrar(dados):
    """Dict JSON → token Fernet (texto)."""
    bruto = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).encode()
    return _fernet().encrypt(bruto).decode()


def decifrar(token):
    """Token Fernet → dict. `ErroCofre` se não há chave, ela é inválida ou não é a que cifrou."""
    fernet = _fernet()
    try:
        return json.loads(fernet.decrypt(token.encode()))
    except InvalidToken, ValueError:
        raise ErroCofre(MSG_CHAVE_TROCADA) from None
