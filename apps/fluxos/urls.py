from django.urls import path

from . import views

app_name = "fluxos"

urlpatterns = [
    path("", views.FluxoListaView.as_view(), name="lista"),
]
