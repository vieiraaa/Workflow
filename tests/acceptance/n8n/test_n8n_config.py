"""Aceite T-073 · pendências, aviso e salvamento (N8N-01/02/07). Servidor local; nada de internet."""
import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("n8n")]

URL_OK = "https://n8n.exemplo.test/webhook/abc-123"


@pytest.fixture
def salvar_n8n(cliente_adm, fabrica_fluxo, salvar_grafo, h):
    def _s(config, **extra):
        f = fabrica_fluxo(grafo=h.cadeia2(), status="rascunho")
        r = salvar_grafo(cliente_adm, f, h.cadeia2(h.no2("n", "chamar_n8n", config, x=1, **extra)))
        return r, f

    return _s


def _msgs(r, chave="pendencias"):
    return [p["mensagem"] for p in r.json()[chave] if p["no"] == "n"]


def test_config_valida_salva_sem_pendencia_e_sem_aviso(salvar_n8n, cfg):
    """N8N-01/02: config completa e válida → 200, ok, sem pendências nem avisos."""
    r, _ = salvar_n8n(cfg(URL_OK))
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["pendencias"] == [] and r.json()["avisos"] == []


def test_url_vazia_e_pendencia(salvar_n8n, cfg):
    """N8N-02: url vazia → 'Informe a URL do webhook do n8n.'"""
    r, _ = salvar_n8n(cfg(""))
    assert r.status_code == 200 and "Informe a URL do webhook do n8n." in _msgs(r)


@pytest.mark.parametrize("url", ["ftp://n8n.exemplo.test/webhook/x", "file:///etc/passwd", "n8n.exemplo.test/webhook/x",
                                 "javascript:alert(1)"])
def test_url_que_nao_e_http_e_pendencia(salvar_n8n, cfg, url):
    """N8N-02: url literal sem http(s) → mensagem exata."""
    r, _ = salvar_n8n(cfg(url))
    assert "A URL do webhook deve começar com https:// (ou http://)." in _msgs(r)


@pytest.mark.parametrize("url", ["http://n8n.exemplo.test/webhook/x", URL_OK, "{{ $json.alvo }}", "={{ $json.alvo }}"])
def test_url_http_https_ou_expressao_nao_e_pendencia_de_url(salvar_n8n, cfg, url):
    """N8N-01/02: http, https e expressão (resolvida só na execução) não geram pendência de URL."""
    r, _ = salvar_n8n(cfg(url))
    assert r.status_code == 200 and r.json()["pendencias"] == []


def test_personalizado_sem_corpo_e_pendencia(salvar_n8n, cfg):
    """N8N-02: enviar=personalizado e corpo vazio → 'Informe o corpo a enviar.'; com corpo, não."""
    r, _ = salvar_n8n(cfg(URL_OK, enviar="personalizado", corpo=""))
    assert "Informe o corpo a enviar." in _msgs(r)
    r, _ = salvar_n8n(cfg(URL_OK, enviar="personalizado", corpo="={{ $json }}"))
    assert "Informe o corpo a enviar." not in _msgs(r)


def test_corpo_nao_e_exigido_em_item_e_todos(salvar_n8n, cfg):
    """N8N-01/02: o corpo só vale em personalizado."""
    for modo in ("item", "todos"):
        r, _ = salvar_n8n(cfg(URL_OK, enviar=modo, corpo=""))
        assert "Informe o corpo a enviar." not in _msgs(r)


@pytest.mark.parametrize("t", [0, -1, 56, 1000])
def test_tempo_limite_fora_da_faixa_e_pendencia(salvar_n8n, cfg, t):
    """N8N-01/02: tempo_limite_s fora de 1..55 → 'Tempo limite entre 1 e 55 segundos.'"""
    r, _ = salvar_n8n(cfg(URL_OK, tempo_limite_s=t))
    assert r.status_code == 200 and "Tempo limite entre 1 e 55 segundos." in _msgs(r)


@pytest.mark.parametrize("t", [1, 30, 55])
def test_tempo_limite_nos_limites_e_valido(salvar_n8n, cfg, t):
    """N8N-01: 1, 30 e 55 são válidos."""
    r, _ = salvar_n8n(cfg(URL_OK, tempo_limite_s=t))
    assert "Tempo limite entre 1 e 55 segundos." not in _msgs(r)


def test_pendencia_bloqueia_executar(cliente_adm, fabrica_fluxo, h, cfg, modelos, liberado):
    """N8N-02: pendência bloqueia executar (nenhuma execução criada, nada enviado)."""
    g = h.cadeia2(h.no2("n", "chamar_n8n", cfg(""), x=1))
    f = fabrica_fluxo(grafo=g, status="ativo")
    cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    assert modelos.Execucao.objects.count() == 0 and liberado.requisicoes == []


def test_aviso_de_url_de_teste(salvar_n8n, cfg):
    """N8N-02/07: /webhook-test/ → aviso {no, campo:'url', mensagem exata}; não é pendência; salva."""
    r, f = salvar_n8n(cfg("https://n8n.exemplo.test/webhook-test/abc"))
    msg = ("URL de TESTE do n8n: só funciona enquanto o n8n estiver em 'Listen for test event'. "
           "Para uso real, ative o fluxo no n8n e use /webhook/.")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert {"no": "n", "campo": "url", "mensagem": msg} in r.json()["avisos"]
    assert msg not in _msgs(r)
    f.refresh_from_db()
    assert any(n["tipo"] == "chamar_n8n" for n in f.grafo["nos"])


def test_url_de_producao_nao_gera_aviso(salvar_n8n, cfg):
    """N8N-02: /webhook/ não gera aviso."""
    r, _ = salvar_n8n(cfg("https://n8n.exemplo.test/webhook/abc"))
    assert r.json()["avisos"] == []


def test_aviso_nao_impede_executar(cliente_adm, fabrica_fluxo, h, cfg, liberado, modelos):
    """N8N-07: aviso não impede executar."""
    liberado.rotas["/webhook-test/x"] = lambda req: (200, {"ok": 1}, None)
    g = h.cadeia2(h.no2("n", "chamar_n8n", cfg(f"{liberado.base}/webhook-test/x"), x=1))
    f = fabrica_fluxo(grafo=g, status="ativo")
    cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    assert modelos.Execucao.objects.get().status == "sucesso" and len(liberado.hits("/webhook-test/")) == 1


def test_editor_recebe_avisos_no_json_script(cliente_adm, fabrica_fluxo, h, cfg):
    """N8N-07: o editor traz o json_script `editor-avisos` com o aviso do nó."""
    import json
    import re
    g = h.cadeia2(h.no2("n", "chamar_n8n", cfg("https://n8n.exemplo.test/webhook-test/abc"), x=1))
    f = fabrica_fluxo(grafo=g)
    r = cliente_adm.get(reverse("fluxos:editor", kwargs={"pk": f.pk}))
    m = re.search(r'<script id="editor-avisos"[^>]*>(.*?)</script>', r.content.decode(), re.S)
    assert m, "json_script editor-avisos ausente"
    avisos = json.loads(m.group(1))
    assert any(a["no"] == "n" and a["campo"] == "url" and "URL de TESTE do n8n" in a["mensagem"] for a in avisos)


def test_credencial_inexistente_nao_e_pendencia(salvar_n8n, cfg):
    """N8N-07(3): credencial inexistente NÃO é pendência ao salvar (é erro de execução)."""
    r, _ = salvar_n8n(cfg(URL_OK, credencial="Fantasma"))
    assert r.status_code == 200 and r.json()["pendencias"] == []


def test_padroes_do_no_novo(salvar_n8n):
    """N8N-01: config mínima {url} salva (padrões POST/item/aguardar=true/30 s aplicados na execução)."""
    r, _ = salvar_n8n({"url": URL_OK})
    assert r.status_code == 200 and r.json()["pendencias"] == []


def test_exportar_nativo_preserva_o_no(cliente_adm, fabrica_fluxo, h, cfg):
    """N8N-06: exportar JSON nativo preserva o nó chamar_n8n e a config; nunca valor de credencial."""
    import json
    g = h.cadeia2(h.no2("n", "chamar_n8n", cfg(URL_OK, credencial="Cofre n8n", enviar="todos"), x=1))
    f = fabrica_fluxo(grafo=g)
    r = cliente_adm.get(reverse("fluxos:exportar", kwargs={"pk": f.pk}))
    dados = json.loads(r.content)
    n = next(x for x in dados["grafo"]["nos"] if x["id"] == "n")
    assert n["tipo"] == "chamar_n8n" and n["config"]["url"] == URL_OK and n["config"]["enviar"] == "todos"
    assert "Cofre n8n" in dados["credenciais_usadas"]


def test_importar_nativo_preserva_o_no(cliente_adm, fabrica_fluxo, h, cfg, modelos):
    """N8N-06: exportar e importar de volta (formato nativo) recria o fluxo com o nó chamar_n8n."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    g = h.cadeia2(h.no2("n", "chamar_n8n", cfg(URL_OK), x=1))
    f = fabrica_fluxo(grafo=g)
    exportado = cliente_adm.get(reverse("fluxos:exportar", kwargs={"pk": f.pk})).content
    antes = set(modelos.Fluxo.objects.values_list("pk", flat=True))
    cliente_adm.post(reverse("fluxos:importar"), {"arquivo": SimpleUploadedFile("f.json", exportado, "application/json")})
    novo = modelos.Fluxo.objects.exclude(pk__in=antes).get()
    n = next(x for x in novo.grafo["nos"] if x["tipo"] == "chamar_n8n")
    assert n["config"]["url"] == URL_OK


def test_importar_do_n8n_http_request_continua_http(cliente_adm, modelos):
    """N8N-06: importação de n8n NÃO cria chamar_n8n; um HTTP Request vira http (mesmo com URL /webhook/)."""
    import json

    from django.core.files.uploadedfile import SimpleUploadedFile
    n8n = {"name": "Fluxo n8n fictício", "nodes": [
        {"id": "id-a", "name": "Chamada", "type": "n8n-nodes-base.httpRequest", "typeVersion": 4, "position": [0, 0],
         "parameters": {"method": "POST", "url": "https://n8n.exemplo.test/webhook/abc"}}],
        "connections": {}, "pinData": {}, "active": False, "settings": {}}
    antes = set(modelos.Fluxo.objects.values_list("pk", flat=True))
    cliente_adm.post(reverse("fluxos:importar"),
                     {"arquivo": SimpleUploadedFile("n.json", json.dumps(n8n).encode(), "application/json")})
    novo = modelos.Fluxo.objects.exclude(pk__in=antes).get()
    tipos = [x["tipo"] for x in novo.grafo["nos"]]
    assert "http" in tipos and "chamar_n8n" not in tipos
