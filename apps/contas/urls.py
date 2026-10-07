from django.urls import path

from . import views

urlpatterns = [
    path("entrar/", views.LoginView.as_view(), name="login"),
    path("sair/", views.LogoutView.as_view(), name="logout"),
    path("", views.InicioView.as_view(), name="inicio"),
]
