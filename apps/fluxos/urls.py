from django.urls import path

from . import views

app_name = "fluxos"

urlpatterns = [
    path("", views.FluxoListaView.as_view(), name="lista"),
    path("novo/", views.FluxoNovoView.as_view(), name="novo"),
    path("<int:pk>/editor/", views.FluxoEditorView.as_view(), name="editor"),
    path("<int:pk>/editar/", views.FluxoEditarView.as_view(), name="editar"),
    path("<int:pk>/excluir/", views.FluxoExcluirView.as_view(), name="excluir"),
    path("<int:pk>/status/", views.FluxoStatusView.as_view(), name="status"),
    path("<int:pk>/grafo/", views.SalvarGrafoView.as_view(), name="salvar_grafo"),
    path("importar/", views.FluxoImportarView.as_view(), name="importar"),
    path("<int:pk>/exportar/", views.FluxoExportarView.as_view(), name="exportar"),
    path("<int:pk>/exportar-n8n/", views.FluxoExportarN8nView.as_view(), name="exportar_n8n"),
    path("<int:pk>/executar/", views.FluxoExecutarView.as_view(), name="executar"),
    path("<int:pk>/executar-no/", views.FluxoExecutarNoView.as_view(), name="executar_no"),
]
