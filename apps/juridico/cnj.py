"""Número único do CNJ (CAD-06, CAD-10): dígitos, validação (módulo 97), formato e alias DataJud.

Funções puras, sem Django nem rede.
"""

import re
import unicodedata

# Código TR (segmento 8 = Justiça Estadual; 6 = Eleitoral) → UF, na ordem oficial do CNJ.
UFS = "ac al ap am ba ce dft es go ma mt ms mg pa pb pr pe pi rj rn rs ro rr sc se sp to".split()
_RE_NUMERO = re.compile(r"[^0-9]")  # \D aceitaria dígitos Unicode (largura total, árabe-índicos)


def so_digitos(texto):
    """Só [0-9] ASCII. Dígitos Unicode (largura total, árabe-índicos...) valem pelo valor
    decimal: viram o mesmo número ASCII e nunca furam a unicidade."""
    ascii_ = "".join(str(int(c)) if c.isdecimal() else c for c in (texto or ""))
    return _RE_NUMERO.sub("", ascii_)


def valido(numero):
    """True se tem 20 dígitos e o dígito verificador confere (módulo 97 = 1)."""
    digitos = so_digitos(numero)
    if len(digitos) != 20 or digitos == "0" * 20:
        return False
    sem_dv = digitos[:7] + digitos[9:] + digitos[7:9]
    return int(sem_dv) % 97 == 1


def formatar(numero):
    """NNNNNNN-DD.AAAA.J.TR.OOOO se tem 20 dígitos; senão devolve o texto aparado."""
    digitos = so_digitos(numero)
    if len(digitos) != 20:
        return (numero or "").strip()
    base, dv, ano, j, tr, origem = (
        digitos[:7], digitos[7:9], digitos[9:13], digitos[13], digitos[14:16], digitos[16:],
    )  # fmt: skip
    return f"{base}-{dv}.{ano}.{j}.{tr}.{origem}"


def gerar_digito(sequencial, ano, j, tr, origem):
    """Dígito verificador de um número (útil em testes e semente de demo)."""
    base = f"{int(sequencial):07d}{int(ano):04d}{int(j)}{int(tr):02d}{int(origem):04d}"
    return f"{98 - (int(base + '00') % 97):02d}"


def numero_valido_de(sequencial, ano, j, tr, origem):
    dv = gerar_digito(sequencial, ano, j, tr, origem)
    return formatar(
        f"{int(sequencial):07d}{dv}{int(ano):04d}{int(j)}{int(tr):02d}{int(origem):04d}"
    )


def alias_datajud(numero):
    """Alias do índice DataJud (`tjsp`, `trf4`, `trt9`, `tre-sp`) ou None se não suportado."""
    digitos = so_digitos(numero)
    if len(digitos) != 20:
        return None
    segmento, tr = digitos[13], int(digitos[14:16])
    if segmento == "8" and 1 <= tr <= len(UFS):
        return f"tj{UFS[tr - 1]}"
    if segmento == "4" and 1 <= tr <= 6:
        return f"trf{tr}"
    if segmento == "5" and 1 <= tr <= 24:
        return f"trt{tr}"
    if segmento == "6" and 1 <= tr <= len(UFS):
        return f"tre-{UFS[tr - 1]}"
    return None


JUSTICAS = {
    "1": "STF",
    "2": "CNJ",
    "3": "STJ",
    "4": "federal",
    "5": "trabalho",
    "6": "eleitoral",
    "7": "militar da União",
    "8": "estadual",
    "9": "militar estadual",
}
SEM_SIGLA = "—"


def sigla_exibicao(numero):
    """Sigla para a ficha (TJSP, TJDFT, TRF3, TRT2, TRE-SP); outro segmento ou TR fora do mapa
    → '—' (CAD-23 §9)."""
    digitos = so_digitos(numero)
    if len(digitos) != 20:
        return SEM_SIGLA
    segmento, tr = digitos[13], int(digitos[14:16])
    if segmento == "8" and 1 <= tr <= len(UFS):
        return "TJ" + UFS[tr - 1].upper()
    if segmento == "4" and 1 <= tr <= 6:
        return f"TRF{tr}"
    if segmento == "5" and 1 <= tr <= 24:
        return f"TRT{tr}"
    if segmento == "6" and 1 <= tr <= len(UFS):
        uf = UFS[tr - 1].upper()
        return "TRE-" + ("DF" if uf == "DFT" else uf)
    return SEM_SIGLA


def decompor(numero):
    """CNJ decomposto para a ficha: {valido, partes [{valor, legenda}], sigla}. Inválido (dígito
    verificador ou formato) → {valido: False, partes: [], sigla: ''}."""
    digitos = so_digitos(numero)
    if not valido(numero) or len(digitos) != 20:
        return {"valido": False, "partes": [], "sigla": ""}
    sigla = sigla_exibicao(digitos)
    partes = [
        (digitos[:7], "sequencial"),
        (digitos[7:9], "dígito"),
        (digitos[9:13], "ano"),
        (digitos[13], JUSTICAS.get(digitos[13], SEM_SIGLA)),
        (digitos[14:16], sigla),
        (digitos[16:], "origem"),
    ]
    return {
        "valido": True,
        "partes": [{"valor": valor, "legenda": legenda} for valor, legenda in partes],
        "sigla": sigla,
    }


def sem_acento(texto):
    base = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(base.lower().split())


def sigla_tribunal(numero):
    """Sigla (TJSP, TRF4...) deduzida do número, ou ''."""
    alias = alias_datajud(numero)
    return alias.replace("-", "").upper() if alias else ""
