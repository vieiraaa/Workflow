"""Chave colada com espaço nas pontas (caso real do Dify, 23/10): o httpx recusava o header e o erro
saía como "não foi possível conectar". Bearer/Header são aparados; senha (Basic/SMTP) não."""

import pytest
from django.urls import reverse

from apps.credenciais.models import Credencial
from apps.juridico.forms import MSG_DIFY_PAGINA_WEB, ConfigForm
from apps.motor.credenciais import cabecalho_http

pytestmark = [pytest.mark.modulo("m5"), pytest.mark.django_db]
CHAVE = "app-FICTICIA0123456789abcdef"


def test_header_http_apara_bearer_e_header_mas_nao_senha():
    assert cabecalho_http(Credencial.BEARER, {"valor": f" {CHAVE}  \n"})[:2] == (
        "Authorization",
        f"Bearer {CHAVE}",
    )
    assert (
        cabecalho_http(Credencial.HEADER, {"valor": f"{CHAVE}  ", "header_nome": "X-Api-Key"})[1]
        == CHAVE
    )
    nome, valor, segredos = cabecalho_http(
        Credencial.BASIC, {"usuario": "u", "valor": "senha com espaço "}
    )
    assert "senha com espaço " in segredos  # a senha vai como foi digitada


def test_header_aparado_passa_pelo_httpx():
    import httpx

    valor = cabecalho_http(Credencial.BEARER, {"valor": f"{CHAVE}  "})[1]
    pedido = httpx.Client().build_request(
        "GET", "https://exemplo.test", headers={"authorization": valor}
    )
    assert pedido.headers["authorization"] == f"Bearer {CHAVE}"


@pytest.mark.parametrize("tipo", ["bearer", "header"])
def test_formulario_salva_bearer_e_header_sem_espacos(cliente_adm, chave_credenciais, tipo):
    dados = {
        "nome": "Dify",
        "tipo": tipo,
        "valor": f"  {CHAVE}  ",
        "setor": "",
        "header_nome": "X-Api-Key",
    }
    assert cliente_adm.post(reverse("credenciais:nova"), dados).status_code == 302
    assert Credencial.objects.get(nome="Dify").dados()["valor"] == CHAVE


def test_formulario_so_com_espacos_e_valor_vazio(cliente_adm, chave_credenciais):
    r = cliente_adm.post(
        reverse("credenciais:nova"), {"nome": "Dify", "tipo": "bearer", "valor": "   ", "setor": ""}
    )
    assert r.status_code == 200 and "valor" in r.context["form"].errors
    assert not Credencial.objects.exists()


def test_formulario_mantem_senha_basic_como_digitada(cliente_adm, chave_credenciais):
    dados = {"nome": "Smtp", "tipo": "basic", "valor": " senha ", "setor": "", "usuario": "u"}
    assert cliente_adm.post(reverse("credenciais:nova"), dados).status_code == 302
    assert Credencial.objects.get(nome="Smtp").dados()["valor"] == " senha "


@pytest.mark.parametrize(
    "url",
    [
        "https://eemdevjurdy.exemplo.test/chat/uCXAvCMooTQfWvDQ",
        "https://dify.exemplo.test/chatbot/AbCdEfGh12345678/",
        "https://dify.exemplo.test/workflow/AbCdEfGh12345678",
    ],
)
def test_config_recusa_link_da_pagina_web_do_dify(url):
    form = ConfigForm(
        data={"dify_url": url, "datajud_url": "https://api.exemplo.test", "dify_usuario": "u"}
    )
    assert not form.is_valid() and form.errors["dify_url"] == [MSG_DIFY_PAGINA_WEB]


@pytest.mark.parametrize(
    "url", ["https://dify.exemplo.test/v1", "https://eemdevjurdyapi.exemplo.test/service/api/v1"]
)
def test_config_aceita_url_da_api(url):
    form = ConfigForm(
        data={"dify_url": url, "datajud_url": "https://api.exemplo.test", "dify_usuario": "u"}
    )
    form.is_valid()
    assert "dify_url" not in form.errors


@pytest.fixture
def cofre(settings):
    from cryptography.fernet import Fernet

    settings.CREDENCIAIS_CHAVE = Fernet.generate_key().decode()


@pytest.mark.parametrize(
    "valor_salvo,enviado",
    [
        (CHAVE, f"APIKey {CHAVE}"),  # caso real de 26/10: colaram só a chave da wiki
        (f"  {CHAVE} ", f"APIKey {CHAVE}"),
        (f"APIKey {CHAVE}", f"APIKey {CHAVE}"),
        (f"apikey {CHAVE}", f"apikey {CHAVE}"),  # já tem esquema: vai como está
    ],
)
def test_datajud_aceita_a_chave_sem_o_prefixo_apikey(valor_salvo, enviado, monkeypatch, cofre):
    """D-051: o DataJud exige 'Authorization: APIKey <chave>'; colar só a chave também funciona."""
    from apps.juridico import clientes
    from apps.juridico.models import ConfigCadastro

    cred = Credencial(nome="DataJud", tipo=Credencial.HEADER)
    cred.definir_dados({"valor": valor_salvo, "header_nome": "Authorization"})
    cred.save()
    config = ConfigCadastro.obter()
    config.datajud_credencial = "DataJud"
    enviados = []

    def falso(url, *, metodo, headers, corpo, prazo_s, **extra):
        enviados.append({h["nome"]: h["valor"] for h in headers})
        return {"status": 200, "corpo": {"hits": {"hits": []}}}

    monkeypatch.setattr(clientes, "_requisitar", falso)
    monkeypatch.setattr(clientes, "_respeitar_intervalo", lambda: None)
    assert clientes.DataJud(config).consultar("tjpr", "00086559120258160024") is None
    assert enviados[0]["Authorization"] == enviado


def test_datajud_nao_mexe_em_header_com_outro_nome(cofre):
    from apps.juridico import clientes
    from apps.juridico.models import ConfigCadastro

    cred = Credencial(nome="DataJud", tipo=Credencial.HEADER)
    cred.definir_dados({"valor": CHAVE, "header_nome": "X-Api-Key"})
    cred.save()
    config = ConfigCadastro.obter()
    config.datajud_credencial = "DataJud"
    assert clientes.DataJud(config).cabecalho == {"nome": "X-Api-Key", "valor": CHAVE}
