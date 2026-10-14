"""T-074: nó Chamar n8n (N8N-01..07) sobre o cliente HTTP do motor."""

import json

import pytest

from apps.credenciais.models import Credencial
from apps.fluxos import demo
from apps.motor import executor

pytestmark = [pytest.mark.modulo("m8"), pytest.mark.django_db]
SEGREDO = "TOKEN-FICTICIO-N8N-123"


def _grafo(config, itens=None, em_erro="parar"):
    def no(i, t, x, c, **extra):
        return {
            "id": i, "tipo": t, "titulo": i.upper(), "posicao": {"x": x, "y": 0}, "config": c,
            "desativado": False, "executar_uma_vez": False, "em_erro": "parar", **extra,
        }  # fmt: skip

    return {
        "versao": 2,
        "nos": [no("g", "gatilho", 0, {}), no("n", "chamar_n8n", 1, config, em_erro=em_erro)],
        "arestas": [{"de": "g", "saida": 0, "para": "n", "entrada": 0}],
        "notas": [],
        "dados_fixos": {"g": itens} if itens is not None else {},
    }


def _rodar(usuario, config, itens=None, **kw):
    fluxo = demo.criar_fluxo(usuario, "F", "ativo", _grafo(config, itens, **kw))
    execucao = executor.executar(fluxo, usuario)
    return execucao, execucao.nos.get(no_id="n")


def _itens(*dicts):
    return [{"json": d} for d in dicts]


def _json(no):
    return [i["json"] for i in no.saida]


def test_post_por_item_envia_json_do_item(usuario_coordenador, liberado):
    liberado.rotas["/hook"] = lambda r: (200, {"recebido": True}, None)
    _, no = _rodar(
        usuario_coordenador, {"url": f"{liberado.base}/hook"}, _itens({"a": 1}, {"a": 2})
    )
    assert no.status == "sucesso"
    assert [json.loads(r["corpo"]) for r in liberado.requisicoes] == [{"a": 1}, {"a": 2}]
    assert liberado.requisicoes[0]["headers"]["content-type"] == "application/json"
    assert _json(no) == [{"recebido": True}, {"recebido": True}]
    assert no.requisicoes and no.requisicoes[0]["metodo"] == "POST"


def test_todos_envia_uma_chamada_e_vazio_nao_chama(usuario_coordenador, liberado):
    liberado.rotas["/hook"] = lambda r: (200, [{"x": 1}, 5], None)
    config = {"url": f"{liberado.base}/hook", "enviar": "todos"}
    _, no = _rodar(usuario_coordenador, config, _itens({"a": 1}, {"a": 2}))
    assert len(liberado.requisicoes) == 1
    assert json.loads(liberado.requisicoes[0]["corpo"]) == {"itens": [{"a": 1}, {"a": 2}]}
    assert _json(no) == [{"x": 1}, {"valor": 5}]
    liberado.requisicoes.clear()
    _, no = _rodar(usuario_coordenador, config, [])
    assert liberado.requisicoes == [] and no.saida == []


def test_get_vai_em_query_so_com_escalares(usuario_coordenador, liberado):
    liberado.rotas["/hook"] = lambda r: (200, {"ok": 1}, None)
    config = {"url": f"{liberado.base}/hook", "metodo": "GET"}
    _rodar(usuario_coordenador, config, _itens({"a": "x", "n": 3, "b": True, "o": {"z": 1}}))
    req = liberado.requisicoes[0]
    assert req["metodo"] == "GET" and req["corpo"] == ""
    assert req["query"] == {"a": ["x"], "n": ["3"], "b": ["true"]}


def test_personalizado_avalia_corpo(usuario_coordenador, liberado):
    liberado.rotas["/hook"] = lambda r: (200, {}, None)
    config = {
        "url": f"{liberado.base}/hook",
        "enviar": "personalizado",
        "corpo": '{"nome": "{{ $json.nome }}"}',
    }
    _rodar(usuario_coordenador, config, _itens({"nome": "Ana"}))
    assert json.loads(liberado.requisicoes[0]["corpo"]) == {"nome": "Ana"}


@pytest.mark.parametrize(
    ("rota", "esperado"),
    [
        ((200, b"", None), [{"n8n_status": 200}]),
        ((200, b"texto puro", None), [{"resposta": "texto puro"}]),
        ((200, {"a": 1}, None), [{"a": 1}]),
    ],
)
def test_formas_de_resposta(usuario_coordenador, liberado, rota, esperado):
    liberado.rotas["/hook"] = lambda r: rota
    _, no = _rodar(usuario_coordenador, {"url": f"{liberado.base}/hook"}, _itens({}))
    assert _json(no) == esperado


def test_sem_aguardar_repete_entrada_com_status(usuario_coordenador, liberado):
    liberado.rotas["/hook"] = lambda r: (202, {"ignorado": 1}, None)
    config = {"url": f"{liberado.base}/hook", "aguardar_resposta": False}
    _, no = _rodar(usuario_coordenador, config, _itens({"a": 1}, {"a": 2}))
    assert _json(no) == [{"a": 1, "n8n_status": 202}, {"a": 2, "n8n_status": 202}]


@pytest.mark.parametrize(
    ("status", "categoria", "trecho"),
    [
        (404, "http_4xx", "Webhook do n8n não encontrado"),
        (401, "http_4xx", "recusou a autenticação"),
        (403, "http_4xx", "recusou a autenticação"),
        (500, "http_5xx", "O n8n respondeu 500."),
        (418, "http_4xx", "O n8n respondeu 418."),
    ],
)
def test_erros_por_status(usuario_coordenador, liberado, status, categoria, trecho):
    _, no = _rodar(usuario_coordenador, {"url": f"{liberado.base}/status/{status}"}, _itens({}))
    assert no.status == "erro"
    assert no.erro_categoria == categoria
    assert trecho in no.erro_mensagem


def test_tempo_esgotado(usuario_coordenador, liberado):
    config = {"url": f"{liberado.base}/lento", "tempo_limite_s": 1}
    _, no = _rodar(usuario_coordenador, config, _itens({}))
    assert no.erro_categoria == "timeout"
    assert "não respondeu em 1 s" in no.erro_mensagem


def test_texto_acima_de_1mb_e_resposta_grande(usuario_coordenador, liberado):
    _, no = _rodar(usuario_coordenador, {"url": f"{liberado.base}/grande"}, _itens({}))
    assert no.erro_categoria == "resposta_grande"


def test_ssrf_continua_bloqueado(usuario_coordenador):
    _, no = _rodar(usuario_coordenador, {"url": "http://127.0.0.1:9/hook"}, _itens({}))
    assert no.erro_categoria == "bloqueado_ssrf"


def test_credencial_inexistente_e_erro_de_execucao(usuario_coordenador, liberado):
    config = {"url": f"{liberado.base}/hook", "credencial": "nao-existe"}
    _, no = _rodar(usuario_coordenador, config, _itens({}))
    assert no.erro_categoria == "credencial"
    assert no.erro_mensagem == "Credencial não encontrada para este fluxo."
    assert liberado.requisicoes == []


def test_credencial_vai_no_header_e_nunca_no_historico(
    usuario_coordenador, liberado, chave_credenciais
):
    cred = Credencial(nome="n8n", tipo="bearer", criado_por=usuario_coordenador)
    cred.definir_dados({"valor": SEGREDO, "usuario": "", "header_nome": ""})
    cred.save()
    liberado.rotas["/hook"] = lambda r: (500, {"eco": SEGREDO}, None)
    config = {"url": f"{liberado.base}/hook", "credencial": "n8n"}
    execucao, no = _rodar(usuario_coordenador, config, _itens({}))
    assert liberado.requisicoes[0]["headers"]["authorization"] == f"Bearer {SEGREDO}"
    assert SEGREDO not in json.dumps(
        [no.erro_mensagem, no.requisicoes, no.saida, no.entrada], default=str
    )


def test_continuar_em_erro_segue_com_item_marcado(usuario_coordenador, liberado):
    config = {"url": f"{liberado.base}/status/404"}
    _, no = _rodar(usuario_coordenador, config, _itens({"a": 1}), em_erro="continuar")
    assert no.saida[0]["json"]["a"] == 1
    assert no.saida[0]["json"]["erro"]["categoria"] == "http_4xx"
