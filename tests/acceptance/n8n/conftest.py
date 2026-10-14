"""Fixtures do aceite do nó "Chamar n8n" (T-073). Só pela spec: docs/spec/no-n8n.yaml (N8N-01..07) + motor-v2/seguranca.

CONTRATO: tipo do nó `chamar_n8n`; config {url, metodo, credencial, enviar, corpo, aguardar_resposta, tempo_limite_s}.
O "n8n" é um servidor HTTP LOCAL (fixtures do m5), liberado só via settings.MOTOR_SSRF_LIBERAR. Nunca internet.
"""
import pytest

from tests.acceptance.m5.conftest import *  # noqa: F401,F403  (servidor, liberado, nao_liberado, h, modelos, no, jsons, executar…)


def cfg_n8n(url, **extra):
    c = {"url": url, "metodo": "POST", "credencial": None, "enviar": "item", "corpo": "",
         "aguardar_resposta": True, "tempo_limite_s": 30}
    c.update(extra)
    return c


@pytest.fixture
def cfg():
    return cfg_n8n


@pytest.fixture
def n8n_no(executar, cliente_adm, h, no):
    """n8n_no(config, entrada=[{}], **extra_no) → (execucao, ExecucaoNo 'n'). Cadeia g → Dados(pin) → chamar_n8n 'n'."""

    def _n(config, entrada=None, **extra):
        g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                      h.no2("n", "chamar_n8n", config, x=2, titulo="n8n", **extra),
                      dados_fixos={"d": h.itens(*(entrada if entrada is not None else [{}]))})
        _, e, _ = executar(cliente_adm, g)
        assert e is not None
        return e, no(e, "n")

    return _n


@pytest.fixture
def webhook(liberado):
    """webhook(rota, status=200, corpo={...}, headers=None) registra rota do 'n8n' falso; devolve a URL completa."""

    def _w(rota, status=200, corpo=None, headers=None):
        liberado.rotas[rota] = lambda req: (status, {"ok": True} if corpo is None else corpo, headers)
        return f"{liberado.base}{rota}"

    return _w
