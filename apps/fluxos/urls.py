from django.urls import path

from . import views

app_name = "fluxos"

urlpatterns = [
    path("", views.FluxoListaView.as_view(), name="lista"),
    path("novo/", views.FluxoNovoView.as_view(), name="novo"),
    path("<int:pk>/", views.FluxoEditorView.as_view(), name="editor"),
    path("<int:pk>/editar/", views.FluxoEditarView.as_view(), name="editar"),
    path("<int:pk>/excluir/", views.FluxoExcluirView.as_view(), name="excluir"),
    path("<int:pk>/status/", views.FluxoStatusView.as_view(), name="status"),
    path("<int:pk>/grafo/", views.SalvarGrafoView.as_view(), name="salvar_grafo"),
    path("<int:pk>/executar/", views.FluxoExecutarView.as_view(), name="executar"),
]
