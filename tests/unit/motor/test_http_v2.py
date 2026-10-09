"""T-054: nó HTTP v2 — credencial (CRD-02), modos de resposta e paginação (MV2-15/16)."""

import base64
import json

import pytest

from apps.credenciais.models import Credencial
from apps.fluxos import demo
from apps.motor import executor

pytestmark = [pytest.mark.modulo("m5"), pytest.mark.django_db]
SEGREDO = "TOKEN-FICTICIO-ABCDEF"


def _cfg(url, **extra):
    base = {
        "metodo": "GET",
        "url": url,
        "headers": [],
        "query": [],
        "corpo": {"tipo": "nenhum", "conteudo": ""},
        "credencial": None,
        "resposta": "automatica",
        "resposta_completa": False,
        "paginacao": None,
    }
    return {**base, **extra}


def _grafo(config):
    no = lambda i, t, x, c: {  # noqa: E731
        "id": i, "tipo": t, "titulo": i.upper(), "posicao": {"x": x, "y": 0}, "config": c,
        "desativado": False, "executar_uma_vez": False, "em_erro": "parar",
    }  # fmt: skip
    return {
        "versao": 2,
        "nos": [no("g", "gatilho", 0, {}), no("h", "http", 1, config)],
        "arestas": [{"de": "g", "saida": 0, "para": "h", "entrada": 0}],
        "notas": [],
        "dados_fixos": {},
    }


def _rodar(usuario, config):
    fluxo = demo.criar_fluxo(usuario, "F", "ativo", _grafo(config))
    execucao = executor.executar(fluxo, usuario)
    no = execucao.nos.get(no_id="h")
    return execucao, no


def _credencial(dono, tipo="bearer", valor=SEGREDO, setor=None, nome="Digisac", **dados):
    cred = Credencial(nome=nome, tipo=tipo, setor=setor, criado_por=dono)
    cred.definir_dados({"valor": valor, "usuario": "", "header_nome": "", **dados})
    cred.save()
    return cred


def _json(no):
    return [i["json"] for i in no.saida]


# ---------------------------------------------------------------- credencial
def test_bearer_header_e_basic_sao_injetados(usuario_coordenador, liberado, chave_credenciais):
    _credencial(usuario_coordenador)
    _rodar(usuario_coordenador, _cfg(f"{liberado.base}/eco", credencial="digisac"))
    assert liberado.requisicoes[-1]["headers"]["authorization"] == f"Bearer {SEGREDO}"
    _credencial(usuario_coordenador, "header", nome="H", header_nome="X-Chave")
    _rodar(usuario_coordenador, _cfg(f"{liberado.base}/eco", credencial="H"))
    assert liberado.requisicoes[-1]["headers"]["x-chave"] == SEGREDO
    _credencial(usuario_coordenador, "basic", "senha-ficticia", nome="B", usuario="maria")
    _rodar(usuario_coordenador, _cfg(f"{liberado.base}/eco", credencial="B"))
    esperado = "Basic " + base64.b64encode(b"maria:senha-ficticia").decode()
    assert liberado.requisicoes[-1]["headers"]["authorization"] == esperado


def test_credencial_substitui_header_igual_do_usuario(
    usuario_coordenador, liberado, chave_credenciais
):
    _credencial(usuario_coordenador)
    config = _cfg(
        f"{liberado.base}/eco",
        credencial="Digisac",
        headers=[{"nome": "authorization", "valor": "Bearer OUTRO"}],
    )
    _rodar(usuario_coordenador, config)
    assert liberado.requisicoes[-1]["headers"]["authorization"] == f"Bearer {SEGREDO}"


@pytest.mark.parametrize("nome", ["Fantasma", "Correio"])
def test_credencial_inexistente_ou_smtp_e_erro_sem_enviar(
    nome, usuario_coordenador, liberado, chave_credenciais
):
    _credencial(usuario_coordenador, "smtp", nome="Correio", host="h", porta=587)
    execucao, no = _rodar(usuario_coordenador, _cfg(f"{liberado.base}/eco", credencial=nome))
    assert execucao.status == "erro" and no.erro_categoria == "credencial"
    assert liberado.requisicoes == []


def test_credencial_de_outro_setor(usuario_coordenador, liberado, chave_credenciais):
    from apps.contas.models import Setor

    outro = Setor.objects.create(nome="Outro")
    _credencial(usuario_coordenador, setor=outro)
    execucao, no = _rodar(usuario_coordenador, _cfg(f"{liberado.base}/eco", credencial="Digisac"))
    assert no.erro_categoria == "credencial" and liberado.requisicoes == []
    Credencial.objects.update(setor=usuario_coordenador.setor)
    execucao, _ = _rodar(usuario_coordenador, _cfg(f"{liberado.base}/eco", credencial="Digisac"))
    assert execucao.status == "sucesso"


def test_sem_chave_ou_chave_trocada_vira_erro_credencial(
    usuario_coordenador, liberado, chave_credenciais, settings
):
    from cryptography.fernet import Fernet

    _credencial(usuario_coordenador)
    for chave in ("", Fernet.generate_key().decode()):
        settings.CREDENCIAIS_CHAVE = chave
        execucao, no = _rodar(
            usuario_coordenador, _cfg(f"{liberado.base}/eco", credencial="Digisac")
        )
        assert no.erro_categoria == "credencial" and "chave" in no.erro_mensagem.lower()
    assert liberado.requisicoes == []


def test_valor_nunca_aparece_no_que_e_gravado(usuario_coordenador, liberado, chave_credenciais):
    _credencial(usuario_coordenador)
    liberado.rotas["/nega"] = lambda req: (
        401,
        {"visto": req["headers"].get("authorization"), "token": SEGREDO},
        None,
    )
    for rota in ("/eco", "/nega"):
        execucao, no = _rodar(
            usuario_coordenador, _cfg(f"{liberado.base}{rota}", credencial="Digisac")
        )
        gravado = json.dumps(
            [no.entrada, no.saida, no.requisicoes, no.logs, no.erro_mensagem,
             execucao.erro_resumo, execucao.grafo_snapshot],
            ensure_ascii=False,
        )  # fmt: skip
        assert SEGREDO not in gravado
    assert execucao.status == "erro" and no.erro_categoria == "http_4xx"
    _, no = _rodar(usuario_coordenador, _cfg(f"{liberado.base}/eco", credencial="Digisac"))
    assert no.requisicoes[0]["headers"][-1]["valor"] == "••••"
    assert "••••" in json.dumps(no.saida, ensure_ascii=False)  # o /eco reflete o header no corpo


# ---------------------------------------------------------------- resposta
def test_modos_de_resposta(usuario_coordenador, liberado):
    _, no = _rodar(usuario_coordenador, _cfg(f"{liberado.base}/ok"))
    assert _json(no) == [{"ok": True}]
    _, no = _rodar(usuario_coordenador, _cfg(f"{liberado.base}/ok", resposta="texto"))
    assert _json(no) == [{"data": '{"ok": true}'}]
    _, no = _rodar(usuario_coordenador, _cfg(f"{liberado.base}/texto", resposta="json"))
    assert no.erro_categoria == "json_invalido"
    _, no = _rodar(usuario_coordenador, _cfg(f"{liberado.base}/texto"))
    assert _json(no) == [{"data": "nao e json"}]
    _, no = _rodar(usuario_coordenador, _cfg(f"{liberado.base}/ok", resposta_completa=True))
    assert _json(no)[0]["status"] == 200 and _json(no)[0]["corpo"] == {"ok": True}


def test_lista_vira_um_item_por_elemento(usuario_coordenador, liberado):
    liberado.rotas["/l"] = lambda req: (200, [{"a": 1}, 5, {"a": 2}], None)
    _, no = _rodar(usuario_coordenador, _cfg(f"{liberado.base}/l"))
    assert _json(no) == [{"a": 1}, {"data": 5}, {"a": 2}] and no.itens_saida == 3


def test_corpo_formulario_e_texto(usuario_coordenador, liberado):
    corpo = {
        "tipo": "formulario",
        "conteudo": [{"nome": "a", "valor": "x y"}, {"nome": "b", "valor": "2"}],
    }
    _rodar(usuario_coordenador, _cfg(f"{liberado.base}/eco", metodo="POST", corpo=corpo))
    req = liberado.requisicoes[-1]
    assert req["corpo"] == "a=x%20y&b=2"
    assert req["headers"]["content-type"] == "application/x-www-form-urlencoded"
    corpo = {"tipo": "texto", "conteudo": "olá"}
    _rodar(usuario_coordenador, _cfg(f"{liberado.base}/eco", metodo="POST", corpo=corpo))
    assert liberado.requisicoes[-1]["headers"]["content-type"].startswith("text/plain")


# ---------------------------------------------------------------- paginação
def _paginas(liberado, paginas, rota="/p"):
    """Servidor que devolve `paginas[n-1]` para ?pagina=n (lista vazia depois)."""

    def tratar(req):
        n = int(req["query"].get("pagina", ["1"])[0])
        return 200, (paginas[n - 1] if n <= len(paginas) else []), None

    liberado.rotas[rota] = tratar


def _pag(**extra):
    base = {
        "modo": "atualizar_parametro", "onde": "query", "nome": "pagina",
        "valor": "{{ $pageCount + 1 }}", "parar_quando": "resposta_vazia",
        "limite_paginas": 10, "intervalo_ms": 0,
    }  # fmt: skip
    return {**base, **extra}


def test_paginacao_ate_resposta_vazia(usuario_coordenador, liberado):
    _paginas(liberado, [[{"i": 1}, {"i": 2}], [{"i": 3}]])
    execucao, no = _rodar(usuario_coordenador, _cfg(f"{liberado.base}/p", paginacao=_pag()))
    assert execucao.status == "sucesso" and [j["i"] for j in _json(no)] == [1, 2, 3]
    assert [r["query"].get("pagina") for r in liberado.requisicoes] == [None, ["2"], ["3"]]
    assert len(no.requisicoes) == 3 and no.requisicoes[0]["status"] == 200


def test_paginacao_limite_para_sem_erro(usuario_coordenador, liberado):
    _paginas(liberado, [[{"i": n}] for n in range(1, 9)])
    execucao, no = _rodar(
        usuario_coordenador, _cfg(f"{liberado.base}/p", paginacao=_pag(limite_paginas=3))
    )
    assert execucao.status == "sucesso" and len(_json(no)) == 3 and len(liberado.requisicoes) == 3


def test_paginacao_parar_por_status_nao_inclui_a_pagina(usuario_coordenador, liberado):
    def tratar(req):
        n = int(req["query"].get("pagina", ["1"])[0])
        return (200, [{"i": n}], None) if n < 3 else (404, {"erro": "fim"}, None)

    liberado.rotas["/p"] = tratar
    pag = _pag(parar_quando="status", codigos=[404])
    execucao, no = _rodar(usuario_coordenador, _cfg(f"{liberado.base}/p", paginacao=pag))
    assert execucao.status == "sucesso" and [j["i"] for j in _json(no)] == [1, 2]


def test_paginacao_parar_por_expressao_inclui_a_pagina(usuario_coordenador, liberado):
    liberado.rotas["/p"] = lambda req: (
        200,
        {"itens": [{"n": 1}], "fim": req["query"].get("pagina") == ["2"]},
        None,
    )
    pag = _pag(parar_quando="expressao", expressao="{{ $response.body.fim }}")
    _, no = _rodar(usuario_coordenador, _cfg(f"{liberado.base}/p", paginacao=pag))
    assert len(_json(no)) == 2 and len(liberado.requisicoes) == 2


def test_paginacao_proxima_url(usuario_coordenador, liberado):
    base = liberado.base

    def tratar(req):
        n = int(req["query"].get("n", ["1"])[0])
        proxima = f"{base}/p?n={n + 1}" if n < 3 else None
        return 200, {"proxima": proxima, "i": n}, None

    liberado.rotas["/p"] = tratar
    pag = {
        "modo": "proxima_url",
        "url": "{{ $response.body.proxima }}",
        "parar_quando": "expressao",
        "expressao": "{{ !$response.body.proxima }}",
        "limite_paginas": 10,
    }
    _, no = _rodar(usuario_coordenador, _cfg(f"{base}/p", paginacao=pag))
    assert [j["i"] for j in _json(no)] == [1, 2, 3]


def test_paginacao_no_corpo_json_e_header(usuario_coordenador, liberado):
    liberado.rotas["/p"] = lambda req: (
        200,
        [] if json.loads(req["corpo"])["a"]["b"] >= 3 else [{"v": 1}],
        None,
    )
    corpo = {"tipo": "json", "conteudo": '{"a": {"b": 1}}'}
    pag = _pag(onde="corpo", nome="a.b")
    _, no = _rodar(
        usuario_coordenador, _cfg(f"{liberado.base}/p", metodo="POST", corpo=corpo, paginacao=pag)
    )
    assert len(_json(no)) == 2
    assert [json.loads(r["corpo"])["a"]["b"] for r in liberado.requisicoes] == [1, 2, 3]
    pag = _pag(onde="header", nome="X-Pagina")
    _rodar(
        usuario_coordenador,
        _cfg(
            f"{liberado.base}/eco", paginacao=_pag(onde="header", nome="X-Pagina", limite_paginas=2)
        ),
    )
    assert liberado.requisicoes[-1]["headers"]["x-pagina"] == "2"


def test_paginacao_passa_pelo_ssrf_a_cada_pagina(usuario_coordenador, liberado, servidor):
    base = liberado.base
    liberado.rotas["/p"] = lambda req: (200, {"proxima": "http://169.254.169.254/x"}, None)
    pag = {
        "modo": "proxima_url",
        "url": "{{ $response.body.proxima }}",
        "parar_quando": "resposta_vazia",
    }
    execucao, no = _rodar(usuario_coordenador, _cfg(f"{base}/p", paginacao=pag))
    assert no.erro_categoria == "bloqueado_ssrf" and execucao.status == "erro"
    assert len(liberado.requisicoes) == 1


def test_pageCount_e_response_so_existem_na_paginacao(usuario_coordenador, liberado):
    config = _cfg(f"{liberado.base}/eco?p={{{{ $pageCount }}}}")
    execucao, no = _rodar(usuario_coordenador, config)
    assert execucao.status == "sucesso" and liberado.requisicoes[-1]["path"].endswith("?p=")
