from django.urls import path

from . import views

app_name = "funcoes"

urlpatterns = [
    path("", views.CatalogoView.as_view(), name="catalogo"),
    path("nova/", views.FuncaoNovaView.as_view(), name="nova"),
    path("<int:pk>/editar/", views.FuncaoEditarView.as_view(), name="editar"),
    path("<int:pk>/publicar/", views.FuncaoPublicarView.as_view(), name="publicar"),
    path("<int:pk>/alternar/", views.FuncaoAlternarView.as_view(), name="alternar"),
    path("<int:pk>/executar/", views.FuncaoExecutarView.as_view(), name="executar"),
    path("execucoes/<int:pk>/", views.FuncaoResultadoView.as_view(), name="resultado"),
]
