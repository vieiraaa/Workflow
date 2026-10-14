"""T-074: validação do nó Chamar n8n (N8N-01/02/07)."""

import pytest

from apps.fluxos import grafo as g

pytestmark = pytest.mark.modulo("m8")


def _grafo(config):
    return {
        "versao": 2,
        "nos": [
            {"id": "g", "tipo": "gatilho", "titulo": "G", "posicao": {"x": 0, "y": 0}, "config": {}},
            {"id": "n", "tipo": "chamar_n8n", "titulo": "N", "posicao": {"x": 1, "y": 0},
             "config": config},
        ],
        "arestas": [{"de": "g", "para": "n"}],
    }  # fmt: skip


def _pend(config):
    erros, pendencias = g.validar(_grafo(config))
    assert erros == []
    return {(p["campo"], p["mensagem"]) for p in pendencias}


def test_config_valida_sem_pendencias():
    assert _pend({"url": "https://n8n.exemplo.com/webhook/abc"}) == set()


@pytest.mark.parametrize(
    ("config", "campo", "mensagem"),
    [
        ({}, "url", "Informe a URL do webhook do n8n."),
        ({"url": "ftp://x/y"}, "url", "A URL do webhook deve começar com https:// (ou http://)."),
        ({"url": "https://a.b/w", "enviar": "personalizado"}, "corpo", "Informe o corpo a enviar."),
        ({"url": "https://a.b/w", "tempo_limite_s": 56}, "tempo_limite_s",
         "Tempo limite entre 1 e 55 segundos."),
        ({"url": "https://a.b/w", "tempo_limite_s": 0}, "tempo_limite_s",
         "Tempo limite entre 1 e 55 segundos."),
    ],
)  # fmt: skip
def test_pendencias(config, campo, mensagem):
    assert (campo, mensagem) in _pend(config)


def test_expressao_na_url_nao_e_pendencia():
    assert _pend({"url": "{{ $json.url }}"}) == set()


def test_enums_e_chaves_desconhecidas_sao_erro_de_formato():
    for config in ({"url": "https://a.b", "metodo": "PUT"}, {"url": "https://a.b", "x": 1}):
        assert g.validar(_grafo(config))[0]


def test_aviso_de_url_de_teste_nao_bloqueia():
    config = {"url": "https://n8n.exemplo.com/webhook-test/abc"}
    assert _pend(config) == set()
    avisos = g.avisos(_grafo(config))
    assert [(a["no"], a["campo"]) for a in avisos] == [("n", "url")]
    assert avisos[0]["mensagem"].startswith("URL de TESTE do n8n")
    assert g.avisos(_grafo({"url": "https://n8n.exemplo.com/webhook/abc"})) == []


@pytest.mark.django_db
def test_salvar_grafo_devolve_avisos_e_editor_emite_json_script(cliente_adm, usuario_adm):
    import json

    from django.urls import reverse

    from apps.fluxos import demo

    fluxo = demo.criar_fluxo(usuario_adm, "F")
    grafo = _grafo({"url": "https://n8n.exemplo.com/webhook-test/abc"})
    resposta = cliente_adm.post(
        reverse("fluxos:salvar_grafo", kwargs={"pk": fluxo.pk}),
        json.dumps({"grafo": grafo, "atualizado_em": fluxo.atualizado_em.isoformat()}),
        content_type="application/json",
    )
    dados = resposta.json()
    assert dados["ok"] is True
    assert [(a["no"], a["campo"]) for a in dados["avisos"]] == [("n", "url")]
    editor = cliente_adm.get(reverse("fluxos:editor", kwargs={"pk": fluxo.pk}))
    assert [a["no"] for a in editor.context["avisos"]] == ["n"]
