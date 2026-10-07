from django.urls import path

from . import views_usuarios

app_name = "contas"

urlpatterns = [
    path("", views_usuarios.UsuarioListaView.as_view(), name="usuarios"),
]
