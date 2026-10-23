"""Fixtures do ADVERSARIAL do nó "Chamar n8n" (T-073, 2º item). Só pela spec: no-n8n.yaml, seguranca.yaml, motor-v2.yaml.

Servidor HTTP LOCAL em thread (nunca internet), liberado só via settings.MOTOR_SSRF_LIBERAR (SEG-08).
"""
import pytest

from tests.adversarial.m5.conftest import *  # noqa: F401,F403  (servidor, liberado, nao_liberado, h, modelos, no, executar…)


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
    """n8n_no(config, entrada=[{}], **extra_no) → (execucao, ExecucaoNo 'n' ou None se o motor não gravou o nó)."""

    def _n(config, entrada=None, **extra):
        g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                      h.no2("n", "chamar_n8n", config, x=2, titulo="n8n", **extra),
                      dados_fixos={"d": h.itens(*(entrada if entrada is not None else [{}]))})
        _, e, _ = executar(cliente_adm, g)
        assert e is not None
        from django.apps import apps
        return e, apps.get_model("execucoes", "ExecucaoNo").objects.filter(execucao=e, no_id="n").first()

    return _n


@pytest.fixture(autouse=True)
def sem_internet(monkeypatch):
    """Rede de segurança: resolução de nome que não seja local falha (nunca internet, nem por engano do motor)."""
    import socket

    original = socket.getaddrinfo

    def guardado(host, *a, **kw):
        if host in ("127.0.0.1", "localhost", "::1", None):
            return original(host, *a, **kw)
        raise socket.gaierror(socket.EAI_NONAME, "sem internet nos testes")

    monkeypatch.setattr(socket, "getaddrinfo", guardado)
