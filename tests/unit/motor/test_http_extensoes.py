"""T-078: extensões do cliente HTTP do motor usadas pelo Jurídico (corpo binário, limite por
chamada, contexto TLS) — sem abrir caminho de rede novo."""

import ssl

import pytest

from apps.motor import http as cliente

pytestmark = pytest.mark.modulo("m8")


def test_corpo_binario_vai_sem_recodificar(liberado):
    dados = bytes(range(256))
    liberado.rotas["/bin"] = lambda r: (200, {"ok": True}, None)
    resposta = cliente.requisitar(
        metodo="POST",
        url=f"{liberado.base}/bin",
        headers=[{"nome": "Content-Type", "valor": "application/octet-stream"}],
        corpo=dados,
    )
    assert resposta["status"] == 200 and liberado.requisicoes[-1]["metodo"] == "POST"


def test_limite_de_corpo_por_chamada_pode_ampliar_e_reduzir(liberado, settings):
    settings.MOTOR_LIMITE_RESPOSTA = 1024
    url = f"{liberado.base}/exato"  # 1024 bytes
    assert cliente.requisitar(metodo="GET", url=url, corpo_max=512)["truncado"] is True
    grande = f"{liberado.base}/grande"  # 1,5 MB
    assert cliente.requisitar(metodo="GET", url=grande)["truncado"] is True
    ampliado = cliente.requisitar(metodo="GET", url=grande, corpo_max=2 * 1024 * 1024)
    assert ampliado["truncado"] is False and len(ampliado["texto"]) == 1536 * 1024


def test_contexto_tls_customizado_e_aceito_e_ssrf_continua(liberado):
    contexto = ssl.create_default_context()
    resposta = cliente.requisitar(metodo="GET", url=f"{liberado.base}/ok", contexto_tls=contexto)
    assert resposta["status"] == 200
    with pytest.raises(cliente.ErroHttp) as erro:
        cliente.requisitar(metodo="GET", url="http://127.0.0.1:9/x", contexto_tls=contexto)
    assert erro.value.categoria == "bloqueado_ssrf"
