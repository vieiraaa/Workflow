from django.urls import path

from . import views

app_name = "execucoes"

urlpatterns = [
    path("", views.ExecucaoListaView.as_view(), name="lista"),
]
