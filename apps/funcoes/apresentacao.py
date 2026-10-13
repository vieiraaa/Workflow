"""Texto de apresentação das Funções (puro: o template escapa)."""

from django.utils import timezone


def quando_relativo(momento, agora=None):
    """'agora', 'há 5 min', 'há 3 h', 'há 2 d' ou a data (acima de 30 dias)."""
    agora = agora or timezone.now()
    segundos = max(int((agora - momento).total_seconds()), 0)
    if segundos < 60:
        return "agora"
    if segundos < 3600:
        return f"há {segundos // 60} min"
    if segundos < 86400:
        return f"há {segundos // 3600} h"
    if segundos < 30 * 86400:
        return f"há {segundos // 86400} d"
    return timezone.localtime(momento).strftime("%d/%m/%Y")
