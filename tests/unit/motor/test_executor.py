import copy
import json

import pytest

from apps.execucoes.models import Execucao
from apps.fluxos import demo
from apps.motor import executor
from apps.motor.mascarar import MASCARA

pytestmark = [pytest.mark.modulo("m3"), pytest.mark.django_db]


def _no(id_, tipo, config=None):
    return {
        "id": id_,
        "tipo": tipo,
        "titulo": id_.upper(),
        "posicao": {"x": 0, "y": 0},
        "config": config or {},
    }


def _http(url, metodo="GET", headers=None, query=None, corpo=""):
    return {
        "metodo": metodo,
        "url": url,
        "headers": headers or [],
        "query": query or [],
        "corpo": corpo,
    }


def _cadeia(*configs):
    nos = [_no("g", "gatilho")]
    nos += [_no(f"h{i}", "http", c) for i, c in enumerate(configs, 1)]
    nos.append(_no("s", "saida"))
    ids = [n["id"] for n in nos]
    return {
        "versao": 1,
        "nos": nos,
        "arestas": [{"de": a, "para": b} for a, b in zip(ids, ids[1:], strict=False)],
    }


def _rodar(usuario, grafo, status="ativo"):
    fluxo = demo.criar_fluxo(usuario, "Fluxo X", status, grafo)
    return executor.executar(fluxo, usuario), fluxo


def _nos(execucao):
    return {n.no_id: n for n in execucao.nos.all()}


def test_sucesso_grava_um_no_por_no_em_ordem(usuario_coordenador, liberado):
    execucao, _ = _rodar(usuario_coordenador, _cadeia(_http(f"{liberado.base}/ok")))
    assert execucao.status == "sucesso" and execucao.finalizada_em and execucao.erro_resumo == ""
    assert [(n.ordem, n.no_id, n.status) for n in execucao.nos.all()] == [
        (0, "g", "sucesso"),
        (1, "h1", "sucesso"),
        (2, "s", "sucesso"),
    ]
    nos = _nos(execucao)
    assert nos["h1"].saida["status"] == 200 and nos["h1"].saida["corpo"] == {"ok": True}
    assert nos["s"].saida == nos["h1"].saida
    assert nos["g"].saida["executado_por"] == usuario_coordenador.email


def test_pendencias_nao_criam_execucao(usuario_coordenador):
    fluxo = demo.criar_fluxo(
        usuario_coordenador, "Vazio", "rascunho", {"versao": 1, "nos": [], "arestas": []}
    )
    with pytest.raises(executor.FluxoComPendencias) as erro:
        executor.executar(fluxo, usuario_coordenador)
    assert erro.value.pendencias and Execucao.objects.count() == 0


def test_falha_para_e_marca_o_resto_como_nao_executado(usuario_coordenador, liberado):
    grafo = _cadeia(_http(f"{liberado.base}/status/503"), _http(f"{liberado.base}/ok"))
    execucao, _ = _rodar(usuario_coordenador, grafo)
    nos = _nos(execucao)
    assert [nos[i].status for i in ("g", "h1", "h2", "s")] == [
        "sucesso",
        "erro",
        "nao_executado",
        "nao_executado",
    ]
    assert nos["h1"].erro_categoria == "http_5xx" and "503" in nos["h1"].erro_mensagem
    assert nos["h1"].saida["status"] == 503 and nos["h1"].saida["corpo"] == {"erro": "x"}
    assert execucao.status == "erro" and "H1" in execucao.erro_resumo
    assert liberado.caminhos.count("/ok") == 0


def test_placeholder_do_no_anterior_e_percent_encode(usuario_coordenador, liberado):
    grafo = _cadeia(
        _http(f"{liberado.base}/eco"),
        _http(
            f"{liberado.base}/eco?x={{{{ anterior.corpo.metodo }}}}",
            query=[{"nome": "p", "valor": "{{ anterior.status }}"}],
        ),
    )
    execucao, _ = _rodar(usuario_coordenador, grafo)
    h2 = _nos(execucao)["h2"]
    assert execucao.status == "sucesso"
    assert h2.entrada["url"].endswith("?x=GET") and h2.entrada["query"] == [
        {"nome": "p", "valor": "200"}
    ]


def test_placeholder_inexistente_e_erro_de_placeholder_sem_enviar(usuario_coordenador, liberado):
    grafo = _cadeia(
        _http(f"{liberado.base}/ok"),
        _http(f"{liberado.base}/eco/{{{{ anterior.corpo.nao_existe }}}}"),
    )
    execucao, _ = _rodar(usuario_coordenador, grafo)
    h2 = _nos(execucao)["h2"]
    assert h2.erro_categoria == "placeholder" and "anterior.corpo.nao_existe" in h2.erro_mensagem
    assert len(liberado.requisicoes) == 1


def test_crlf_de_placeholder_em_header_ou_query_e_recusado_sem_enviar(
    usuario_coordenador, liberado
):
    for config in (
        _http(
            f"{liberado.base}/eco", headers=[{"nome": "X-A", "valor": "{{ anterior.corpo.crlf }}"}]
        ),
        _http(f"{liberado.base}/eco", query=[{"nome": "q", "valor": "{{ anterior.corpo.crlf }}"}]),
    ):
        antes = len(liberado.requisicoes)
        execucao, _ = _rodar(
            usuario_coordenador, _cadeia(_http(f"{liberado.base}/valores"), config)
        )
        h2 = _nos(execucao)["h2"]
        assert h2.erro_categoria == "placeholder" and execucao.status == "erro"
        assert len(liberado.requisicoes) == antes + 1  # só o /valores saiu


def test_corpo_truncado_em_placeholder_falha_com_resposta_grande(usuario_coordenador, liberado):
    grafo = _cadeia(
        _http(f"{liberado.base}/grande"),
        _http(f"{liberado.base}/eco", "POST", corpo='{"a": "{{ anterior.corpo }}"}'),
    )
    execucao, _ = _rodar(usuario_coordenador, grafo)
    nos = _nos(execucao)
    assert nos["h1"].status == "sucesso" and nos["h1"].saida["truncado"] is True
    assert nos["h2"].erro_categoria == "resposta_grande" and len(liberado.requisicoes) == 1


def test_truncado_nao_atrapalha_placeholder_de_status(usuario_coordenador, liberado):
    grafo = _cadeia(
        _http(f"{liberado.base}/grande"), _http(f"{liberado.base}/eco?s={{{{ anterior.status }}}}")
    )
    execucao, _ = _rodar(usuario_coordenador, grafo)
    assert execucao.status == "sucesso"


def test_corpo_json_invalido_apos_resolver(usuario_coordenador, liberado):
    grafo = _cadeia(
        _http(f"{liberado.base}/ok"),
        _http(f"{liberado.base}/eco", "POST", corpo='{"a": {{ anterior.status }}x}'),
    )
    # o grafo tem pendência (JSON inválido) → não executa; o defensivo cobre o caso resolvido
    with pytest.raises(executor.FluxoComPendencias):
        _rodar(usuario_coordenador, grafo)


def test_headers_e_query_sensiveis_mascarados_na_entrada_e_snapshot_mas_enviados(
    usuario_coordenador, liberado
):
    grafo = _cadeia(
        _http(
            f"{liberado.base}/eco?token=NA-URL",
            headers=[
                {"nome": "Authorization", "valor": "Bearer SEGREDO-H"},
                {"nome": "X-Ok", "valor": "v"},
            ],
            query=[{"nome": "api-key", "valor": "SEGREDO-Q"}, {"nome": "q", "valor": "livre"}],
        )
    )
    execucao, fluxo = _rodar(usuario_coordenador, grafo)
    h1 = _nos(execucao)["h1"]
    assert h1.entrada["headers"][0]["valor"] == MASCARA and h1.entrada["headers"][1]["valor"] == "v"
    assert (
        h1.entrada["url"].endswith(f"token={MASCARA}")
        and h1.entrada["query"][0]["valor"] == MASCARA
    )
    assert "SEGREDO" not in json.dumps(h1.entrada) + json.dumps(execucao.grafo_snapshot)
    assert liberado.requisicoes[-1]["headers"]["authorization"] == "Bearer SEGREDO-H"
    assert "api-key=SEGREDO-Q" in liberado.requisicoes[-1]["path"]
    fluxo.refresh_from_db()
    assert "SEGREDO-H" in json.dumps(fluxo.grafo)


def test_headers_de_resposta_mascarados_na_saida_mas_nao_no_placeholder(
    usuario_coordenador, liberado
):
    grafo = _cadeia(
        _http(f"{liberado.base}/cabecalhos"),
        _http(
            f"{liberado.base}/eco",
            headers=[{"nome": "X-Eco", "valor": "{{ anterior.headers.x-publico }}"}],
        ),
    )
    execucao, _ = _rodar(usuario_coordenador, grafo)
    nos = _nos(execucao)
    assert nos["h1"].saida["headers"]["set-cookie"] == MASCARA
    assert nos["h1"].saida["headers"]["x-api-key"] == MASCARA
    assert liberado.requisicoes[-1]["headers"]["x-eco"] == "visivel"


def test_erro_de_ssrf_vira_categoria_e_nada_sai(usuario_coordenador, servidor):
    grafo = _cadeia(_http(f"{servidor.base}/ok"))
    execucao, _ = _rodar(usuario_coordenador, grafo)
    h1 = _nos(execucao)["h1"]
    assert h1.erro_categoria == "bloqueado_ssrf" and servidor.requisicoes == []
    assert h1.entrada["url"] == f"{servidor.base}/ok"


def test_prazo_total_da_execucao(usuario_coordenador, liberado, settings):
    settings.MOTOR_TIMEOUT_EXECUCAO = 1
    settings.MOTOR_TIMEOUT_LEITURA = 30
    grafo = _cadeia(_http(f"{liberado.base}/lento"), _http(f"{liberado.base}/ok"))
    execucao, _ = _rodar(usuario_coordenador, grafo)
    nos = _nos(execucao)
    assert nos["h1"].erro_categoria == "timeout" and nos["h2"].status == "nao_executado"
    assert execucao.status == "erro"


def test_excecao_inesperada_vira_erro_do_no_sem_vazar(usuario_coordenador, liberado, monkeypatch):
    def quebra(**kwargs):
        raise RuntimeError("segredo-interno postgres://u:p@h/db")

    monkeypatch.setattr(executor.http, "requisitar", quebra)
    execucao, _ = _rodar(usuario_coordenador, _cadeia(_http(f"{liberado.base}/ok")))
    h1 = _nos(execucao)["h1"]
    assert h1.status == "erro" and "segredo-interno" not in h1.erro_mensagem + execucao.erro_resumo
    assert execucao.status == "erro" and execucao.finalizada_em


def test_snapshot_independe_do_fluxo_depois(usuario_coordenador, liberado):
    execucao, fluxo = _rodar(usuario_coordenador, _cadeia(_http(f"{liberado.base}/ok")))
    antes = copy.deepcopy(execucao.grafo_snapshot)
    fluxo.grafo = {"versao": 1, "nos": [], "arestas": []}
    fluxo.save()
    fluxo.delete()
    execucao.refresh_from_db()
    assert execucao.grafo_snapshot == antes and execucao.fluxo is None
