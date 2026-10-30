"""Formatação para as telas e mensagens do cadastro (texto puro: o template escapa)."""

import re
from decimal import Decimal

from django.utils import timezone

from . import cnj


def data(valor):
    return valor.strftime("%d/%m/%Y") if valor else ""


def data_hora(valor):
    return timezone.localtime(valor).strftime("%d/%m/%Y %H:%M") if valor else ""


def valor_texto(valor):
    if valor is None:
        return ""
    inteiro, _, centavos = f"{Decimal(valor):,.2f}".partition(".")
    return f"R$ {inteiro.replace(',', '.')},{centavos}"


def _mascarar_um(documento):
    digitos = cnj.so_digitos(documento)
    if len(digitos) == 11:
        return f"***.{digitos[3:6]}.{digitos[6:9]}-**"
    if len(digitos) == 14:
        return f"**.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-**".replace("**.", "**.", 1)
    return "•••"


def mascarar_documento(texto):
    """CPF → ***.456.789-**; CNPJ → **.345.678/0001-**; outro tamanho → •••; vários: um a um."""
    partes = [p for p in re.split(r"\s*;\s*", texto or "") if p.strip()]
    return "; ".join(_mascarar_um(p) for p in partes)


def quem(usuario):
    if usuario is None:
        return "um usuário removido"
    return f"{usuario.nome or usuario.email} ({usuario.email})"


def origem_rotulo(origem):
    return {"pdf": "PDF", "cnj": "CNJ", "manual": "manual"}.get(origem, origem)


def nome(usuario):
    return (usuario.nome or usuario.email) if usuario is not None else "um usuário removido"


# Selos de integração no cartão do processo (D-052; visual D-054, opção C): texto curto por extenso,
# na ordem do fluxo DataJud (CNJ) → CSLog → Espaider. O símbolo inicial (✓ ! ? ×) carrega o estado
# junto com a cor (nunca só a cor); nada de logotipo de terceiro (design-base).
SELOS_CNJ = {
    "confere": ("ok", "✓ DataJud", "CNJ: confere (DataJud)"),
    "divergente": ("conf", "! DataJud diverge", "CNJ: diverge do PDF; vale o PDF (DataJud)"),
    "nao_encontrado": ("neutro", "? DataJud não encontrou", "CNJ: não encontrado no DataJud"),
    "falhou": ("erro", "× DataJud falhou", "CNJ: a consulta falhou"),
    "nao_consultado": ("vazio", "DataJud não consultado", "CNJ: ainda não consultado"),
}


def selos_integracao(processo):
    """[{chave, estado ok|conf|neutro|erro|vazio, texto, titulo}] na ordem do fluxo. O DataJud
    aparece sempre; o Espaider só quando lançado. Quando houver integração com o CSLog, ela entra
    entre os dois, com o mesmo formato."""
    estado, texto, titulo = SELOS_CNJ.get(processo.cnj_validacao, SELOS_CNJ["nao_consultado"])
    if processo.cnj_validacao == "falhou" and processo.cnj_mensagem:
        titulo = f"CNJ: {processo.cnj_mensagem}"  # o motivo da falha no title (D-058)
    elif processo.cnj_validacao == "confere" and processo.cnj_divergencias:
        titulo = f"{titulo}; só difere: {'; '.join(processo.cnj_divergencias)}"  # D-062
    selos = [{"chave": "cnj", "estado": estado, "texto": texto, "titulo": titulo}]
    if processo.status == "CADASTRADO":
        quando = data_hora(processo.cadastrado_espaider_em)
        titulo = f"Espaider: cadastrado em {quando}" if quando else "Espaider: cadastrado"
        selos.append({"chave": "espaider", "estado": "ok", "texto": "✓ Espaider", "titulo": titulo})
    return selos
