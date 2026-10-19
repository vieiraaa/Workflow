"""T-083: correções do adversarial do M8 (dígitos ASCII, PEM, URLs, carteira, segredos, DataJud)."""

import pytest

from apps.juridico import clientes, cnj, mescla
from apps.juridico.forms import ConfigForm, ProcessoForm, _url_http
from apps.juridico.models import Carteira

pytestmark = pytest.mark.modulo("m8")

CERT = (
    "-----BEGIN CERTIFICATE-----\n"
    "MIIBszCCAVmgAwIBAgIUQ0wYB2l7bXq3v0nQYh2pL3cJ2gUwCgYIKoZIzj0EAwIw\n"
    "-----END CERTIFICATE-----"
)


def test_so_digitos_ascii():
    numero = cnj.numero_valido_de(1234567, 2024, 8, 26, 1)
    largos = "".join(chr(ord(c) + 0xFEE0) if c.isdigit() else c for c in numero)
    arabes = "".join(chr(ord("٠") + int(c)) if c.isdigit() else c for c in numero)
    # Unicode vira o MESMO número ASCII (valor decimal): nunca um 2º "válido" nem dígito não ASCII
    assert cnj.so_digitos(largos) == cnj.so_digitos(arabes) == cnj.so_digitos(numero)
    assert cnj.so_digitos(arabes).isascii() and cnj.so_digitos(arabes).isdigit()
    assert cnj.so_digitos(" " + numero + " (apenso)") == cnj.so_digitos(numero)
    assert cnj.valido(largos) and cnj.valido(arabes)  # mesmo número, mesma unicidade


@pytest.mark.parametrize(
    "pem",
    [
        "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----\nAAAA\n-----END RSA PRIVATE KEY-----",
        CERT + "\n-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----",
        CERT + "\n-----BEGIN CERTIFICATE REQUEST-----\nAAAA\n-----END CERTIFICATE REQUEST-----",
        "lixo -----BEGIN CERTIFICATE-----",
        "sem blocos",
    ],
)
def test_pem_so_aceita_certificados(pem):
    with pytest.raises(ValueError, match="Certificado inválido"):
        clientes.normalizar_pem(pem)


def test_pem_vazio_e_aceito():
    assert clientes.normalizar_pem("  ") == ""


@pytest.mark.parametrize(
    "url",
    [
        "ftp://dify.exemplo.test/api",
        "//dify.exemplo.test/api",
        "https://dify.exemplo.test‮/api",
        "https://difу.exemplo.test",
        "javascript:alert(1)",
        "https://",
        "https://host com espaço/api",
        "",
    ],
)
def test_urls_hostis_sao_recusadas(url):
    with pytest.raises(Exception, match="URL"):
        _url_http(url)


def test_urls_validas_passam():
    assert _url_http(" https://eemdevjurdyapi.eem-adv.org/service/api/v1 ").startswith("https://")
    assert _url_http("http://localhost:8001/dify") == "http://localhost:8001/dify"


@pytest.mark.django_db
def test_config_recusa_pem_com_chave_e_url_ftp():
    dados = {
        "dify_url": "ftp://x.test",
        "dify_usuario": "u",
        "datajud_url": "https://api-publica.datajud.cnj.jus.br",
        "dify_ca_pem": "-----BEGIN PRIVATE KEY-----\nAAAA\n-----END PRIVATE KEY-----",
    }
    form = ConfigForm(dados)
    assert not form.is_valid() and {"dify_url", "dify_ca_pem"} <= set(form.errors)


@pytest.mark.django_db
def test_carteira_do_processo_nao_aceita_inativa_nem_invalida():
    ativa = Carteira.objects.get(nome="Ativos")
    inativa = Carteira.objects.create(nome="Velha", ativa=False)
    form = ProcessoForm()
    assert set(form.fields["carteira"].queryset) >= {ativa} and inativa not in set(
        form.fields["carteira"].queryset
    )
    for valor in (str(inativa.pk), "abc", "999999"):
        assert not ProcessoForm({"numero": "x", "carteira": valor}).is_valid()


def test_mascarar_dados_por_valor_em_estruturas():
    segredos = {"CHAVE-SECRETA-123"}
    dados = {
        "adverso_nome": "Fulano CHAVE-SECRETA-123",
        "andamentos": [{"evento": "x CHAVE-SECRETA-123 y", "n": 3}],
        "valor": None,
    }
    saida = clientes.mascarar_dados(dados, segredos)
    assert "CHAVE-SECRETA-123" not in str(saida) and saida["andamentos"][0]["n"] == 3
    assert clientes.mascarar_dados("sem segredo", set()) == "sem segredo"


@pytest.mark.parametrize(
    "mudanca",
    [{"orgaoJulgador": "texto"}, {"classe": "x"}, {"formato": ["a"]}, {"tribunal": ["TJSP"]}],
)
def test_datajud_em_forma_inesperada_nao_explode(mudanca):
    from apps.juridico.models import Processo

    fonte = {"tribunal": "TJSP", "dataAjuizamento": "2022-03-15", **mudanca}
    processo = Processo(comarca="São Paulo", tribunal="TJSP")
    mescla.comparar(processo, fonte)  # não levanta
    assert isinstance(mescla.campos_do_datajud(fonte, "tjsp"), dict)
