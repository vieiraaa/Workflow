"""Testes do front da Fase 0: render do login/início/erros e higiene dos templates."""

import re
from pathlib import Path

import pytest
from django.urls import reverse

RAIZ = Path(__file__).resolve().parents[3]
TEMPLATES = RAIZ / "templates"
STATIC = RAIZ / "static"

pytestmark = pytest.mark.modulo("m0")


def test_login_renderiza_template_especifico(client):
    resposta = client.get(reverse("login"))
    assert resposta.status_code == 200
    assert "registration/login.html" in [t.name for t in resposta.templates]
    assert "base_publica.html" in [t.name for t in resposta.templates]
    assert b'name="username"' in resposta.content and b'name="password"' in resposta.content


@pytest.mark.django_db
def test_login_erro_credenciais_mostra_alerta(client):
    resposta = client.post(reverse("login"), {"username": "x@y.com", "password": "errada"})
    assert resposta.status_code == 200
    assert b'data-estado="erro_credenciais"' in resposta.content


def test_inicio_usa_shell(cliente_adm):
    resposta = cliente_adm.get(reverse("inicio"))
    nomes = [t.name for t in resposta.templates]
    assert "inicio/inicio.html" in nomes and "base.html" in nomes
    assert b'action="' + reverse("logout").encode() in resposta.content


def test_nao_encontrado_usa_template_404(cliente_adm):
    resposta = cliente_adm.get("/nao-existe/")
    assert resposta.status_code == 404
    assert "erros/404.html" in [t.name for t in resposta.templates]


def test_base_sem_cdn():
    for arquivo in [
        TEMPLATES / "base.html",
        TEMPLATES / "base_publica.html",
        STATIC / "css/app.css",
        STATIC / "js/app.js",
    ]:
        assert not re.search(r"https?://", arquivo.read_text(encoding="utf-8")), arquivo.name


def test_templates_sem_safe():
    for arquivo in TEMPLATES.rglob("*.html"):
        texto = arquivo.read_text(encoding="utf-8")
        assert (
            "|safe" not in texto and "mark_safe" not in texto and "autoescape off" not in texto
        ), arquivo


def test_templates_sem_user_groups():
    for arquivo in TEMPLATES.rglob("*.html"):
        assert "user.groups" not in arquivo.read_text(encoding="utf-8"), arquivo


def test_post_com_csrf():
    for arquivo in TEMPLATES.rglob("*.html"):
        texto = arquivo.read_text(encoding="utf-8")
        for form in re.findall(r"<form[^>]*method=\"post\"[^>]*>.*?</form>", texto, re.S):
            assert "csrf_token" in form, arquivo


def test_componentes_obrigatorios_existem():
    nomes = "icone card grupo botao campo tabela vazio badge_status paginacao modal toast bloco_codigo segmentado toggle carregando".split()
    for nome in nomes:
        assert (TEMPLATES / "componentes" / f"{nome}.html").exists(), nome


def test_vendor_com_licenca():
    for lib in ("inter", "lucide"):
        licencas = list((STATIC / "vendor" / lib).glob("*/LICENSE"))
        assert licencas, lib


def test_403_sem_papel_oferece_sair(client, db):
    from apps.contas.models import Usuario

    Usuario.objects.create_user(email="sem@exemplo.test", password="Senha-forte-123", nome="Sem")
    client.login(username="sem@exemplo.test", password="Senha-forte-123")
    resposta = client.get(reverse("inicio"))
    assert resposta.status_code == 403
    assert "erros/403.html" in [t.name for t in resposta.templates]
    assert reverse("logout").encode() in resposta.content
    assert "Ir para o início".encode() not in resposta.content
