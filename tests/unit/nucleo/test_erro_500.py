import pytest
from django.template import TemplateDoesNotExist
from django.test import Client, RequestFactory
from django.urls import path

from apps.nucleo import views

pytestmark = pytest.mark.modulo("m2")


def test_handler500_configurado():
    from config import urls

    assert urls.handler500 == "apps.nucleo.views.erro_500"


def test_erro_500_sem_banco_nem_context_processors():
    # sem a marca django_db, qualquer acesso ao banco levanta erro: o handler não pode usá-lo
    resposta = views.erro_500(RequestFactory().get("/"))
    assert resposta.status_code == 500
    assert b"<html" in resposta.content.lower()


def test_erro_500_cai_no_html_minimo_se_o_template_falha(monkeypatch):
    def quebrado(*args, **kwargs):
        raise TemplateDoesNotExist("erros/500.html")

    monkeypatch.setattr(views, "render_to_string", quebrado)
    resposta = views.erro_500(RequestFactory().get("/"))
    assert resposta.status_code == 500
    assert "Algo deu errado" in resposta.content.decode()


def test_erro_500_nao_vaza_detalhes(monkeypatch):
    def quebrado(*args, **kwargs):
        raise RuntimeError("segredo-interno postgres://u:p@h/db")

    monkeypatch.setattr(views, "render_to_string", quebrado)
    assert "segredo" not in views.erro_500(RequestFactory().get("/")).content.decode()


def test_excecao_em_view_vira_500_do_produto(settings):
    import types

    def explode(request):
        raise RuntimeError("falha interna")

    urlconf = types.ModuleType("urlconf_500")
    urlconf.urlpatterns = [path("boom/", explode)]
    urlconf.handler500 = "apps.nucleo.views.erro_500"
    settings.ROOT_URLCONF = urlconf
    cliente = Client(raise_request_exception=False)
    resposta = cliente.get("/boom/")
    assert resposta.status_code == 500
    assert b"falha interna" not in resposta.content
