"""D-058: erro do DataJud sempre com o motivo por extenso; 429 espera e tenta de novo."""

from types import SimpleNamespace

import pytest

from apps.juridico import apresentacao, clientes
from apps.juridico.models import Processo
from apps.motor import http as http_motor

pytestmark = pytest.mark.modulo("m8")


@pytest.fixture
def datajud(monkeypatch, settings):
    """DataJud com cabeçalho fixo e _requisitar trocado por uma fila de respostas."""
    settings.JURIDICO_DATAJUD_INTERVALO_S = 0
    settings.JURIDICO_DATAJUD_ESPERAS_429_S = (5, 15)
    monkeypatch.setattr(
        clientes,
        "_cabecalho",
        lambda *a: ({"nome": "Authorization", "valor": "APIKey ficticia"}, set()),
    )
    esperas, chamadas, fila = [], [], []
    monkeypatch.setattr(clientes.time, "sleep", esperas.append)

    def requisitar(url, **kw):
        chamadas.append(url)
        item = fila.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(clientes, "_requisitar", requisitar)
    cliente = clientes.DataJud(
        SimpleNamespace(datajud_url="https://datajud.exemplo.test", datajud_credencial="x")
    )
    return SimpleNamespace(cliente=cliente, fila=fila, chamadas=chamadas, esperas=esperas)


def _resp(status, headers=None, corpo='{"hits": {"hits": []}}'):
    return {"status": status, "headers": headers or {}, "texto": corpo}


def test_429_tenta_de_novo_e_passa(datajud):
    datajud.fila += [_resp(429), _resp(429), _resp(200)]
    assert datajud.cliente.consultar("tjsp", "0" * 20) is None
    assert len(datajud.chamadas) == 3 and datajud.esperas == [5.0, 15.0]


def test_429_respeita_retry_after_com_teto(datajud):
    datajud.fila += [
        _resp(429, {"retry-after": "8"}),
        _resp(429, {"retry-after": "999"}),
        _resp(200),
    ]
    datajud.cliente.consultar("tjsp", "0" * 20)
    assert datajud.esperas == [8.0, 30.0]


def test_429_que_persiste_explica_o_motivo(datajud):
    datajud.fila += [_resp(429)] * 3
    with pytest.raises(clientes.ErroCliente) as erro:
        datajud.cliente.consultar("tjsp", "0" * 20)
    assert len(datajud.chamadas) == 3
    assert erro.value.mensagem.startswith("A consulta ao DataJud falhou: limite de consultas")
    assert "erro 429" in erro.value.mensagem and "Consultar CNJ" in erro.value.mensagem


@pytest.mark.parametrize(
    ("status", "trecho"),
    [
        (400, "inválida (erro 400)"),
        (404, "índice deste tribunal (erro 404)"),
        (500, "erro interno no DataJud (erro 500)"),
        (503, "fora do ar ou em manutenção (erro 503)"),
        (504, "demorou demais"),
        (418, "erro 418 (a consulta não foi aceita)"),
        (599, "erro 599 (do lado do CNJ)"),
    ],
)
def test_cada_status_tem_motivo(datajud, status, trecho):
    datajud.fila.append(_resp(status))
    with pytest.raises(clientes.ErroCliente) as erro:
        datajud.cliente.consultar("tjsp", "0" * 20)
    assert (
        erro.value.mensagem.startswith("A consulta ao DataJud falhou:")
        and trecho in erro.value.mensagem
    )
    assert datajud.esperas == []  # só o 429 tenta de novo


def test_falha_de_rede_diz_quem_falhou(datajud):
    datajud.fila.append(http_motor.ErroHttp("timeout"))
    with pytest.raises(clientes.ErroCliente) as erro:
        datajud.cliente.consultar("tjsp", "0" * 20)
    assert (
        erro.value.mensagem
        == "Não foi possível falar com o DataJud: a requisição excedeu o tempo limite."
    )


def test_selo_de_falha_traz_o_motivo_no_title():
    p = Processo(
        cnj_validacao="falhou",
        cnj_mensagem="A consulta ao DataJud falhou: x (erro 429).",
        status="CONFERIR",
    )
    assert (
        apresentacao.selos_integracao(p)[0]["titulo"]
        == "CNJ: A consulta ao DataJud falhou: x (erro 429)."
    )
