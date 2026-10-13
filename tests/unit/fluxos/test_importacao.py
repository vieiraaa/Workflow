"""Importação/exportação (T-056): funções puras de `importacao`, `n8n` e `exportacao`."""

import json

import pytest

from apps.fluxos import exportacao, importacao
from apps.fluxos.grafo import MARCA_CREDENCIAL, validar

P = "n8n-nodes-base."


def _n8n(*nos, conexoes=None, **raiz):
    return json.dumps(
        {"name": "Teste", "nodes": list(nos), "connections": conexoes or {}, **raiz}
    ).encode()


def _no(nome, tipo, params=None, pos=(0, 0)):
    return {"name": nome, "type": P + tipo, "position": list(pos), "parameters": params or {}}


def test_importar_n8n_gera_grafo_valido_com_ids_novos():
    nome, _, grafo, relatorio = importacao.importar(
        _n8n(
            _no("Início", "manualTrigger"),
            _no("Fim", "noOp", pos=(1, 0)),
            conexoes={"Início": {"main": [[{"node": "Fim", "type": "main", "index": 0}]]}},
        )
    )
    assert nome == "Teste" and validar(grafo) == ([], [])
    assert {n["id"] for n in grafo["nos"]}.isdisjoint({"Início", "Fim"})
    assert relatorio["importados"] == ["Início", "Fim"]


def test_codigo_entra_desativado_e_segredo_e_trocado():
    segredo = "Kq7Zp3Xv9Lm2Nb5Tc8Rd1Sg4Hj6Wf0Yz3AaBbCcDd"
    _, _, grafo, relatorio = importacao.importar(
        _n8n(
            _no("Início", "manualTrigger"),
            _no("Cod", "code", {"jsCode": f"const t = '{segredo}';"}),
        )
    )
    codigo = next(n for n in grafo["nos"] if n["tipo"] == "codigo")
    assert codigo["desativado"] is True and relatorio["codigo_desativado"] == ["Cod"]
    assert MARCA_CREDENCIAL in codigo["config"]["codigo"] and segredo not in json.dumps(grafo)
    _, pendencias = validar(grafo)
    assert any(p["mensagem"] == "Mova este segredo para uma credencial." for p in pendencias)


@pytest.mark.parametrize("conteudo", [b"", b"[]", b"{nao", b'{"formato": "x"}', b'{"nodes": []}'])
def test_arquivo_invalido_levanta_erro_proprio(conteudo):
    with pytest.raises(importacao.ErroImportacao):
        importacao.importar(conteudo)


def test_arquivo_grande_demais_e_recusado():
    with pytest.raises(importacao.ErroImportacao):
        importacao.ler_json(b" " * (importacao.LIMITE_BYTES + 1))


def test_slug_e_credenciais_usadas():
    assert exportacao.slug("Pedidos do Dia — Ação!") == "pedidos-do-dia-acao"
    grafo = {
        "nos": [
            {"tipo": "http", "config": {"credencial": "B"}},
            {"tipo": "http", "config": {"credencial": "A"}},
        ]
    }
    assert exportacao.credenciais_usadas(grafo) == ["A", "B"]


def test_detector_cobre_zero_width_url_dados_fixos_e_notas():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJmaWN0aWNpbyJ9.assinaturaficticia1234567890abc"
    sticky = _no("Nota", "stickyNote", {"content": f"token {jwt}"})
    http = _no(
        "Chama",
        "httpRequest",
        {"url": "https://x.test/a?apikey=Rg5Hh1BnCc7DdEe9Ff", "sendHeaders": True,
         "headerParameters": {"parameters": [{"name": "X-Api-Key", "value": "Abc123Def456Ghi7"}]}},
    )  # fmt: skip
    dados = _n8n(
        _no("Início", "manualTrigger"),
        http,
        sticky,
        pinData={"Chama": [{"json": {"t": jwt[:20] + "​" + jwt[20:]}}]},
    )
    _, _, grafo, relatorio = importacao.importar(dados)
    bruto = json.dumps(grafo, ensure_ascii=False)
    assert (
        jwt[:20] not in bruto
        and "Rg5Hh1BnCc7DdEe9Ff" not in bruto
        and "Abc123Def456Ghi7" not in bruto
    )
    assert len(relatorio["segredos"]) >= 4


def test_nome_com_nul_e_recusado():
    with pytest.raises(importacao.ErroImportacao):
        importacao.importar(
            _n8n(_no("Início", "manualTrigger"), name="a\x00b").replace(b'"Teste"', b'"a\\u0000b"')
        )
