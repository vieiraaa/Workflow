from django.urls import path

from . import views

app_name = "execucoes"

urlpatterns = [
    path("", views.ExecucaoListaView.as_view(), name="lista"),
    path("<int:pk>/", views.ExecucaoDetalheView.as_view(), name="detalhe"),
]
