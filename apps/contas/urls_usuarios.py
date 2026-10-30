from django.urls import path

from . import views_perfil, views_setores, views_simulacao, views_usuarios

app_name = "contas"

urlpatterns = [
    path("", views_usuarios.UsuarioListaView.as_view(), name="usuarios"),
    path("simular/", views_simulacao.SimularListaView.as_view(), name="simular"),
    path(
        "simular/encerrar/",
        views_simulacao.SimulacaoEncerrarView.as_view(),
        name="simulacao_encerrar",
    ),
    path(
        "<int:pk>/simular/",
        views_simulacao.SimularIniciarView.as_view(),
        name="simular_iniciar",
    ),
    path("setores/", views_setores.SetorListaView.as_view(), name="setores"),
    path("setores/novo/", views_setores.SetorNovoView.as_view(), name="setor_novo"),
    path("setores/<int:pk>/", views_setores.SetorEditarView.as_view(), name="setor_editar"),
    path("minha-senha/", views_usuarios.TrocarSenhaView.as_view(), name="trocar_senha"),
    path("perfil/", views_perfil.PerfilView.as_view(), name="meu_perfil"),
    path("<int:pk>/perfil/", views_perfil.PerfilView.as_view(), name="perfil"),
    path("<int:pk>/perfil/editar/", views_perfil.PerfilEditarView.as_view(), name="perfil_editar"),
    path("<int:pk>/perfil/acesso/", views_perfil.PerfilAcessoView.as_view(), name="perfil_acesso"),
    path("novo/", views_usuarios.UsuarioNovoView.as_view(), name="usuario_novo"),
    path("<int:pk>/", views_usuarios.UsuarioEditarView.as_view(), name="usuario_editar"),
    path(
        "<int:pk>/senha/",
        views_usuarios.UsuarioRedefinirSenhaView.as_view(),
        name="usuario_redefinir_senha",
    ),
]
