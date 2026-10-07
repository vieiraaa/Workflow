from django.urls import path

from . import views_usuarios

app_name = "contas"

urlpatterns = [
    path("", views_usuarios.UsuarioListaView.as_view(), name="usuarios"),
    path("minha-senha/", views_usuarios.TrocarSenhaView.as_view(), name="trocar_senha"),
    path("novo/", views_usuarios.UsuarioNovoView.as_view(), name="usuario_novo"),
    path("<int:pk>/", views_usuarios.UsuarioEditarView.as_view(), name="usuario_editar"),
    path(
        "<int:pk>/senha/",
        views_usuarios.UsuarioRedefinirSenhaView.as_view(),
        name="usuario_redefinir_senha",
    ),
]
