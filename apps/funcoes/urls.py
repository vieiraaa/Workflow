from django.urls import path

from . import views

app_name = "funcoes"

urlpatterns = [
    path("", views.CatalogoView.as_view(), name="catalogo"),
]
