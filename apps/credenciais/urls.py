from django.urls import path

from . import views

app_name = "credenciais"

urlpatterns = [
    path("", views.CredencialListaView.as_view(), name="lista"),
    path("nova/", views.CredencialNovaView.as_view(), name="nova"),
    path("<int:pk>/", views.CredencialEditarView.as_view(), name="editar"),
    path("<int:pk>/excluir/", views.CredencialExcluirView.as_view(), name="excluir"),
]
