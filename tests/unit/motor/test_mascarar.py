from pathlib import Path

import pytest

from apps.motor.mascarar import (
    MASCARA,
    mascarar_entrada_http,
    mascarar_headers_dict,
    mascarar_pares,
    mascarar_saida_http,
    mascarar_url,
    sensivel,
)

pytestmark = pytest.mark.modulo("m3")


@pytest.mark.parametrize(
    "nome",
    [
        "Authorization",
        "AUTHORIZATION",
        "proxy-authorization",
        "Cookie",
        "Set-Cookie",
        "X-Api-Key",
        "x-api-key",
        "X-Auth-Token",
        "access_token",
        "TOKEN",
        "client-secret",
        "Secret",
        "senha",
        "Minha-Senha-Admin",
        "password",
        "X-Password-Hash",
        "my-api-key",
        "apikey",
        "api_key",
        "  Authorization  ",
    ],
)
def test_nomes_sensiveis(nome):
    assert sensivel(nome)


@pytest.mark.parametrize(
    "nome",
    [
        "Accept",
        "Content-Type",
        "User-Agent",
        "X-Request-Id",
        "page",
        "q",
        "",
        "tokenizer".upper()[:0],
    ],
)
def test_nomes_comuns_nao_sao_mascarados(nome):
    assert not sensivel(nome)


def test_pares_de_entrada():
    pares = [
        {"nome": "Authorization", "valor": "Bearer abc"},
        {"nome": "Accept", "valor": "application/json"},
        {"nome": "x-token", "valor": "t"},
    ]
    saida = mascarar_pares(pares)
    assert saida == [
        {"nome": "Authorization", "valor": MASCARA},
        {"nome": "Accept", "valor": "application/json"},
        {"nome": "x-token", "valor": MASCARA},
    ]
    assert pares[0]["valor"] == "Bearer abc"  # não altera o original
    assert mascarar_pares(None) == [] and mascarar_pares(saida) == saida  # idempotente


def test_headers_de_resposta():
    saida = mascarar_headers_dict(
        {"content-type": "x", "set-cookie": "sid=1", "x-api-key": "k", "x-secret-thing": "s"}
    )
    assert saida == {
        "content-type": "x",
        "set-cookie": MASCARA,
        "x-api-key": MASCARA,
        "x-secret-thing": MASCARA,
    }
    assert mascarar_headers_dict(None) == {}


@pytest.mark.parametrize(
    ("url", "esperada"),
    [
        ("https://e.test/x?token=abc&q=1", f"https://e.test/x?token={MASCARA}&q=1"),
        ("https://e.test/x?q=1&api-key=zz#f", f"https://e.test/x?q=1&api-key={MASCARA}#f"),
        (
            "https://e.test/x?PASSWORD=p&senha=s",
            f"https://e.test/x?PASSWORD={MASCARA}&senha={MASCARA}",
        ),
        ("https://e.test/x?q=1", "https://e.test/x?q=1"),
        ("https://e.test/token/abc", "https://e.test/token/abc"),
        ("https://e.test/x?token=", f"https://e.test/x?token={MASCARA}"),
    ],
)
def test_url_mascara_parametros_sensiveis(url, esperada):
    assert mascarar_url(url) == esperada


def test_entrada_e_saida_http_completas():
    entrada = {
        "metodo": "GET",
        "url": "https://e.test/?secret=1",
        "headers": [{"nome": "Cookie", "valor": "a=b"}],
        "query": [{"nome": "token", "valor": "t"}, {"nome": "q", "valor": "ok"}],
        "corpo": "",
    }
    masc = mascarar_entrada_http(entrada)
    assert masc["url"] == f"https://e.test/?secret={MASCARA}"
    assert masc["headers"][0]["valor"] == MASCARA
    assert [p["valor"] for p in masc["query"]] == [MASCARA, "ok"]
    assert entrada["headers"][0]["valor"] == "a=b"
    saida = mascarar_saida_http(
        {"status": 200, "headers": {"set-cookie": "x"}, "corpo": "t", "truncado": False}
    )
    assert saida["headers"]["set-cookie"] == MASCARA and saida["status"] == 200


def test_mascarar_nao_usa_eval():
    fonte = Path("apps/motor/mascarar.py").read_text(encoding="utf-8")
    assert "eval(" not in fonte and "exec(" not in fonte
