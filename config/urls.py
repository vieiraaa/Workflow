from django.contrib import admin
from django.urls import include, path, re_path

from apps.juridico.api import RecebimentosApiView
from apps.nucleo.easteregg import VideoView

handler403 = "apps.nucleo.views.erro_403"
handler404 = "apps.nucleo.views.erro_404"
handler500 = "apps.nucleo.views.erro_500"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.contas.urls")),
    path("fluxos/", include("apps.fluxos.urls")),
    path("execucoes/", include("apps.execucoes.urls")),
    path("funcoes/", include("apps.funcoes.urls")),
    path("juridico/", include("apps.juridico.urls")),
    path("credenciais/", include("apps.credenciais.urls")),
    path("usuarios/", include("apps.contas.urls_usuarios")),
    path("easteregg/video/", VideoView.as_view(), name="easteregg_video"),
    # API de entrada do n8n (D-048); também sem a barra final (o POST não sobrevive a redirect).
    path(
        "api/juridico/recebimentos/",
        RecebimentosApiView.as_view(),
        name="api_juridico_recebimentos",
    ),
    re_path(r"^api/juridico/recebimentos$", RecebimentosApiView.as_view()),
]
