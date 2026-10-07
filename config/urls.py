from django.contrib import admin
from django.urls import include, path

handler403 = "apps.nucleo.views.erro_403"
handler404 = "apps.nucleo.views.erro_404"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.contas.urls")),
    path("fluxos/", include("apps.fluxos.urls")),
    path("execucoes/", include("apps.execucoes.urls")),
    path("usuarios/", include("apps.contas.urls_usuarios")),
]
