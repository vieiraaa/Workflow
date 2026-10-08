from django.urls import path

from . import views_setores, views_usuarios

app_name = "contas"

urlpatterns = [
    path("", views_usuarios.UsuarioListaView.as_view(), name="usuarios"),
    path("setores/", views_setores.SetorListaView.as_view(), name="setores"),
    path("setores/novo/", views_setores.SetorNovoView.as_view(), name="setor_novo"),
    path("setores/<int:pk>/", views_setores.SetorEditarView.as_view(), name="setor_editar"),
    path("minha-senha/", views_usuarios.TrocarSenhaView.as_view(), name="trocar_senha"),
    path("novo/", views_usuarios.UsuarioNovoView.as_view(), name="usuario_novo"),
    path("<int:pk>/", views_usuarios.UsuarioEditarView.as_view(), name="usuario_editar"),
    path(
        "<int:pk>/senha/",
        views_usuarios.UsuarioRedefinirSenhaView.as_view(),
        name="usuario_redefinir_senha",
    ),
]
