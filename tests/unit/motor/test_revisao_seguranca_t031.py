import gzip
import json
import zlib

import pytest

from apps.motor import http, mascarar

pytestmark = pytest.mark.modulo("m3")


# ---- sanitização de JSON/texto da resposta remota
@pytest.mark.parametrize(
    ("bruto", "esperado"),
    [
        ('{"x": "\\ud800"}', {"x": "�"}),
        ('{"x": "\\udc00"}', {"x": "�"}),
        ('{"x": "\\ud83d\\ude00"}', {"x": "😀"}),  # par válido fica
        ('{"x": "\\ud83dA"}', {"x": "�A"}),
        ('{"x": "\\ud83d\\ud83d"}', {"x": "��"}),
        ('{"x": "\\u0000a"}', {"x": "�a"}),
        ('{"x": "\\\\ud800"}', {"x": "\\ud800"}),  # barra escapada + texto 'ud800': intacto
        ('{"\\ud800": 1}', {"�": 1}),
    ],
)
def test_sanear_json_bruto(bruto, esperado):
    assert json.loads(http.sanear_json_bruto(bruto)) == esperado


def test_corpo_json_com_surrogate_vira_dado_gravavel():
    corpo = http._decodificar_corpo(b'{"a": ["\\ud800", {"b": "\\u0000"}]}', "application/json")
    json.dumps(corpo, ensure_ascii=False).encode("utf-8")  # não levanta
    assert corpo == {"a": ["�", {"b": "�"}]}


def test_texto_com_nul_e_sanitizado():
    assert http._decodificar_corpo(b"a\x00b", "text/plain") == "a�b"
    assert http.sanear_texto("a\x00b\udc80") == "a�b�"


# ---- descompactação incremental com limite
def _alimentar(codificacao, dados, limite):
    d = http._Descompactador(codificacao)
    saida = d.alimentar(dados, limite)
    return saida, d


def test_bomba_gzip_nao_passa_do_max_length():
    saida, d = _alimentar("gzip", gzip.compress(b"\0" * 50_000_000), 1000)
    assert len(saida) == 1000 and d.pendente


def test_gzip_deflate_e_identity_basicos():
    assert _alimentar("gzip", gzip.compress(b"abc"), 100)[0] == b"abc"
    assert _alimentar("x-gzip", gzip.compress(b"abc"), 100)[0] == b"abc"
    assert _alimentar("deflate", zlib.compress(b"abc"), 100)[0] == b"abc"
    assert _alimentar("identity", b"abc", 100)[0] == b"abc"
    assert _alimentar(None, b"abc", 100)[0] == b"abc"


@pytest.mark.parametrize("codificacao", ["br", "zstd", "compress"])
def test_codificacao_nao_suportada_e_recusada(codificacao):
    with pytest.raises(http.ErroHttp) as erro:
        http._Descompactador(codificacao)
    assert erro.value.categoria == "conexao"


def test_gzip_corrompido_vira_erro_proprio():
    with pytest.raises(http.ErroHttp) as erro:
        _alimentar("gzip", b"nao e gzip", 100)
    assert "zlib" not in erro.value.mensagem


def test_accept_encoding_do_usuario_e_ignorado(liberado):
    http.requisitar(
        metodo="GET",
        url=f"{liberado.base}/eco",
        headers=[{"nome": "Accept-Encoding", "valor": "br"}],
    )
    assert "br" not in liberado.requisicoes[-1]["headers"].get("accept-encoding", "")


# ---- máscara: percent-encode, placeholders e valores copiados
def test_nome_percent_encoded_na_url():
    assert mascarar.mascarar_url("https://e.test/x?api%5Fkey=S&q=1") == (
        f"https://e.test/x?api%5Fkey={mascarar.MASCARA}&q=1"
    )
    assert mascarar.sensivel("api%5Fkey", decodificar=True)
    assert not mascarar.sensivel("api%5Fkey")


def test_snapshot_mascara_nome_com_placeholder():
    grafo = {
        "nos": [
            {
                "tipo": "http",
                "config": {
                    "url": "https://e.test",
                    "headers": [
                        {"nome": "{{anterior.corpo.h}}", "valor": "Bearer S"},
                        {"nome": "X-Ok", "valor": "v"},
                    ],
                    "query": [{"nome": "{{ anterior.corpo.q }}", "valor": "S2"}],
                },
            }
        ]
    }
    config = mascarar.mascarar_grafo(grafo)["nos"][0]["config"]
    assert [p["valor"] for p in config["headers"]] == [mascarar.MASCARA, "v"]
    assert config["query"][0]["valor"] == mascarar.MASCARA


def test_valores_sensiveis_da_resposta():
    achados = mascarar.valores_sensiveis(
        {"set-cookie": "sessao=ABCDEF; Path=/", "x-publico": "visivel", "x-api-key": "k"}
    )
    assert {"sessao=ABCDEF; Path=/", "sessao=ABCDEF", "ABCDEF"} <= achados
    assert "visivel" not in achados and "k" not in achados  # curtos/públicos ficam de fora


def test_ocultar_valores_em_todas_as_formas():
    entrada = {
        "metodo": "GET",
        "url": "https://e.test/c/seg%C3%A7ret%22o",
        "headers": [{"nome": "X-A", "valor": 'pre-segçret"o-pos'}],
        "query": [{"nome": "q", "valor": 'segçret"o'}],
        "corpo": '{"v": "seg\\u00e7ret\\"o"}'.replace("\\u00e7", "ç"),
    }
    oculta = mascarar.ocultar_valores(entrada, {'segçret"o'})
    bruto = json.dumps(oculta, ensure_ascii=False)
    assert "segçret" not in bruto and "seg%C3%A7" not in bruto and 'segçret\\"o' not in bruto
    assert bruto.count(mascarar.MASCARA) == 4
    assert mascarar.ocultar_valores(entrada, set()) is entrada


# ---- prazo do nó
def test_prazo_vale_para_o_conjunto_dos_saltos(liberado, settings):
    import time

    settings.MOTOR_TIMEOUT_NO = 1
    inicio = time.monotonic()
    with pytest.raises(http.ErroHttp) as erro:
        http.requisitar(metodo="GET", url=f"{liberado.base}/lento", prazo_s=0.3)
    assert erro.value.categoria == "timeout" and time.monotonic() - inicio < 1.5
