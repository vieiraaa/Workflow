from django.contrib.sessions.models import Session
from django.utils import timezone


def encerrar_sessoes(usuario):
    """Apaga todas as sessões abertas do usuário (ex.: ao desativá-lo)."""
    alvo = str(usuario.pk)
    for sessao in Session.objects.filter(expire_date__gt=timezone.now()):
        if sessao.get_decoded().get("_auth_user_id") == alvo:
            sessao.delete()
