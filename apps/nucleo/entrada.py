"""Sanitização de entrada textual vinda de querystring (reutilizável nas listas)."""

LIMITE_BUSCA = 200


def limpar_texto(valor, limite=LIMITE_BUSCA):
    """Remove NUL (o Postgres recusa em text), apara espaços e limita o tamanho."""
    return (valor or "").replace("\x00", "").strip()[:limite]
