"""Adversarial M4: XSS no nome do setor (SEG-13) em HTML, json_script e gráficos, no servidor e em chromium/webkit.

Nome de setor é entrada do Adm, mas aparece para outros papéis (coluna Setor, select, Home do Adm, gráfico por setor).
Os payloads cabem em 80 caracteres (SET-02).
"""

import json
import re

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m4")]

# U+2028/2029 crus são texto inerte em HTML e json_script moderno: fora desta lista de payloads.
PAYLOADS = [
    "<script>window.__pwn=1</script>",
    "</script><script>window.__pwn=1</script>",
    "<img src=x onerror=window.__pwn=1>",
    '"><svg onload=window.__pwn=1>',
    "'-window.__pwn=1-'",
    "</title><script>window.__pwn=1</script>",
    "javascript:window.__pwn=1",
    "<!--<script>window.__pwn=1</script>-->",
    "{{7*7}}{% debug %}",
]


def _h(r):
    return r.content.decode()


def _blocos_script_json(html):
    return re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', html, flags=re.S)


@pytest.fixture
def setor_xss(mundo, mk_setor, mk_usuario, mk_fluxo, mk_exec):
    """Cria (direto no banco, sem passar pelo formulário) um setor com o payload e dados nele, para aparecer em todo lugar."""

    def _criar(payload):
        s = mk_setor(payload)
        u = mk_usuario("Base", s)
        f = mk_fluxo(s, mundo.adm, "Fluxo Do Setor Xss")
        mk_exec(f, u)
        return s

    return _criar


@pytest.mark.parametrize("payload", PAYLOADS)
def test_servidor_escapa_nome_do_setor_em_todas_as_telas(mundo, setor_xss, payload):
    """SEG-13: nenhum payload cru em HTML (lista de setores, usuários, form de usuário, fluxos, Home) e json_script seguro."""
    s = setor_xss(payload)
    telas = [reverse("contas:setores"), reverse("contas:setor_editar", kwargs={"pk": s.pk}), reverse("contas:setor_novo"),
             reverse("contas:usuarios"), reverse("contas:usuario_novo"), reverse("fluxos:lista"), reverse("execucoes:lista"),
             reverse("inicio"), reverse("inicio") + "?periodo=1a"]
    for url in telas:
        r = mundo.c["adm"].get(url)
        assert r.status_code == 200, url
        h = _h(r)
        assert payload not in h or payload in ("javascript:window.__pwn=1", "{{7*7}}{% debug %}", "'-window.__pwn=1-'"), url
        if payload.startswith("javascript:"):
            assert not re.search(r'href="javascript:', h, re.I)
        # blocos json_script: parseáveis e sem "</script" cru nem "<" cru dentro
        for bloco in _blocos_script_json(h):
            json.loads(bloco)
            assert "</" not in bloco and "<script" not in bloco.lower(), url


@pytest.mark.parametrize("payload", PAYLOADS)
def test_servidor_nome_do_setor_enviado_pelo_formulario_e_escapado_na_lista(mundo, payload):
    """SEG-13: ida e volta pelo formulário (POST) → lista de setores escapada."""
    r = mundo.c["adm"].post(reverse("contas:setor_novo"), {"nome": payload, "ativo": "on"})
    assert r.status_code in (200, 302)
    h = _h(mundo.c["adm"].get(reverse("contas:setores")))
    assert "<script>window.__pwn" not in h and "<img src=x onerror" not in h and "<svg onload" not in h


@pytest.mark.parametrize("payload", PAYLOADS)
def test_gestor_e_base_nao_veem_payload_de_outro_setor_nem_o_proprio_cru(mundo, mk_setor, mk_usuario, logar, payload):
    """SEG-13/SET-06: gestor num setor com payload no nome vê o nome escapado; o setor de outro nunca aparece."""
    s = mk_setor(payload)
    g = mk_usuario("Coordenador", s)
    for quem in (g, mundo.gA):
        h = _h(logar(quem).get(reverse("inicio")))
        assert "<script>window.__pwn" not in h and "<img src=x onerror" not in h and "<svg onload" not in h
    assert payload not in _h(logar(mundo.gA).get(reverse("inicio"))) or payload in ("javascript:window.__pwn=1", "{{7*7}}{% debug %}", "'-window.__pwn=1-'")


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize("payload", PAYLOADS)
def test_navegador_nao_executa_payload_no_nome_do_setor(pagina_adm, setor_xss, payload):
    """SEG-13: em chromium e webkit, nenhuma página renderiza/executa o nome do setor (alert, window.__pwn, erro de JS), incluindo gráfico por setor, tooltip e tabela 'Ver dados'."""
    setor_xss(payload)
    p = pagina_adm
    for caminho in ("/", "/?periodo=1a", "/?periodo=24h", reverse("contas:setores"), reverse("contas:usuarios"), reverse("contas:usuario_novo"), reverse("fluxos:lista")):
        p.goto(p.live_url + caminho)
        p.wait_for_load_state("networkidle")
        # interage com o gráfico: passa o mouse em barras/segmentos (tooltip) e abre "Ver dados" se existir
        for sel in ("[data-setor]", ".grafico rect", ".grafico svg *", "summary", "[data-ver-dados]"):
            for el in p.query_selector_all(sel)[:6]:
                try:
                    el.hover(timeout=300)
                    if sel in ("summary", "[data-ver-dados]"):
                        el.click(timeout=300)
                except Exception:
                    pass
        assert p.evaluate("window.__pwn") is None, caminho
        assert p.dialogos == [], caminho
        assert [e for e in p.erros_js if "__pwn" in e] == [], caminho


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.parametrize("payload", PAYLOADS[:4])
def test_navegador_nome_do_setor_aparece_como_texto(pagina_adm, setor_xss, payload):
    """SEG-13: o nome aparece literal (como texto) na lista de setores — escapado, não sumiu nem foi interpretado."""
    setor_xss(payload)
    pagina_adm.goto(pagina_adm.live_url + reverse("contas:setores"))
    assert payload in pagina_adm.inner_text("body")
    assert pagina_adm.evaluate("window.__pwn") is None
