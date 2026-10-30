"""Easter egg (D-045): 5 cliques seguidos no botão de tema abrem `easteregg/video.mp4` em tela
cheia, só para quem está em `easteregg/usuarios.txt` (login de rede ou e-mail, um por linha).
Quem não está na lista nem recebe o endereço do vídeo, e o vídeo responde 404 para essa pessoa."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import FileResponse, Http404
from django.views import View


def _pasta():
    return Path(getattr(settings, "EASTEREGG_DIR", Path(__file__).resolve().parent / "easteregg"))


def _lista():
    try:
        linhas = (_pasta() / "usuarios.txt").read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {
        linha.strip().lower()
        for linha in linhas
        if linha.strip() and not linha.lstrip().startswith("#")
    }


def liberado(usuario):
    if not getattr(usuario, "is_authenticated", False) or not usuario.is_active:
        return False
    email = (usuario.email or "").lower()
    lista = _lista()
    return bool(email) and (email in lista or email.split("@")[0] in lista)


class VideoView(LoginRequiredMixin, View):
    """GET do vídeo do easter egg: só para quem está na lista; os demais recebem 404."""

    http_method_names = ["get", "head", "options"]

    def get(self, request):
        video = _pasta() / "video.mp4"
        if not liberado(request.user) or not video.is_file():
            raise Http404
        resposta = FileResponse(video.open("rb"), content_type="video/mp4")
        resposta["Cache-Control"] = "private, max-age=3600"
        return resposta
