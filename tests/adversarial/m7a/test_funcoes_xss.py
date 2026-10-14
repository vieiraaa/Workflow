"""Adversarial M7a · XSS em nome, descrição, rótulos, opções, padrões e valores do resultado (SEG-13), servidor e navegador."""
import itertools
import json
import re

import pytest
from django.urls import reverse

from tests.acceptance.m7a.conftest import html

PAYLOADS = [
    "<script>window.__pwn=1</script>",
    "</script><script>window.__pwn=1</script>",
    "<img src=x onerror=window.__pwn=1>",
    '"><svg onload=window.__pwn=1>',
    "'-window.__pwn=1-'",
    "</title><script>window.__pwn=1</script>",
    "<!--<script>window.__pwn=1</script>-->",
    "<iframe srcdoc='<script>parent.__pwn=1</script>'>",
]
_n = itertools.count(1)
CRUS = ("<script>window.__pwn", "<img src=x onerror", "<svg onload", "<iframe srcdoc")


def _sem_cru(h):
    for c in CRUS:
        assert c not in h, c


@pytest.fixture
def mundo_xss(mundo7, mk_fluxo7, Funcao, h, modelos):
    """Função com o payload em nome, descrição, rótulo, opções e padrão; dados do fluxo com payload (saída da tabela)."""

    def _criar(p):
        n = next(_n)
        g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                      h.no2("calc", "editar_campos", h.cfg_editar([(p[:20] or "c", "{{ $parametros.nome }}", "texto")],
                                                                  incluir_outros=True), x=2, titulo="Calc"),
                      dados_fixos={"d": h.itens({"coluna": p, p[:10]: p, "obj": {"k": p}})})
        f = mk_fluxo7(mundo7.A, grafo=g, nome=f"Fluxo XSS {n}")
        ents = [{"nome": "nome", "rotulo": p, "tipo": "texto", "obrigatoria": False, "padrao": p, "opcoes": []},
                {"nome": "cor", "rotulo": "Cor", "tipo": "lista", "obrigatoria": False, "padrao": None, "opcoes": [p, "ok"]}]
        d = {"nome": p, "descricao": p, "icone": "zap", "fluxo": f.pk, "liberar_para": "todos",
             "entradas": json.dumps(ents), "ativa": "on"}
        r = mundo7.c["adm"].post(reverse("funcoes:nova"), d)
        _sem_cru(html(r))
        fn = Funcao.objects.filter(nome=p).first()
        if fn is None:  # recusado na validação: a página de erro também não pode refletir cru
            return None
        mundo7.c["adm"].post(reverse("funcoes:publicar", kwargs={"pk": fn.pk}))
        mundo7.c["bA"].post(reverse("funcoes:executar", kwargs={"pk": fn.pk}), {"nome": p, "cor": "ok"})
        return fn

    return _criar


@pytest.mark.django_db
@pytest.mark.modulo("m7a")
@pytest.mark.parametrize("payload", PAYLOADS)
def test_servidor_escapa_em_todas_as_telas_de_funcao(mundo7, mundo_xss, modelos, payload):
    """SEG-13: nenhum payload cru em catálogo, formulário de função, formulário de execução, resultado, lista de execuções, Home;
    blocos json_script parseáveis e sem '</' cru."""
    fn = mundo_xss(payload)
    assert fn is not None, "pré-condição: função com payload deveria ser aceita (texto livre)"
    e = modelos.Execucao.objects.filter(funcao=fn).first()
    assert e is not None, "pré-condição: execução para o resultado"
    telas = [(k, u) for k in ("adm", "bA") for u in (
        reverse("funcoes:catalogo"), reverse("funcoes:executar", kwargs={"pk": fn.pk}), reverse("execucoes:lista"), reverse("inicio"))]
    telas += [("adm", reverse("funcoes:editar", kwargs={"pk": fn.pk})), ("adm", reverse("funcoes:nova"))]
    if e is not None:
        telas += [(k, reverse("funcoes:resultado", kwargs={"pk": e.pk})) for k in ("adm", "bA")]
        telas += [("adm", reverse("execucoes:detalhe", kwargs={"pk": e.pk}))]
    for k, url in telas:
        r = mundo7.c[k].get(url)
        assert r.status_code == 200, (k, url)
        h = html(r)
        _sem_cru(h)
        for bloco in re.findall(r'<script[^>]*type="application/json"[^>]*>(.*?)</script>', h, flags=re.S):
            json.loads(bloco)
            assert "</" not in bloco and "<script" not in bloco.lower(), url
    # erro de validação reflete o valor digitado: também escapado
    r = mundo7.c["bA"].post(reverse("funcoes:executar", kwargs={"pk": fn.pk}), {"nome": payload, "cor": payload})
    _sem_cru(html(r))


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
@pytest.mark.modulo("m7a")
@pytest.mark.parametrize("payload", PAYLOADS)
def test_navegador_nao_executa_payload_em_telas_de_funcao(mundo7, mundo_xss, modelos, abrir_pagina, payload):
    """SEG-13: em chromium e webkit, nenhuma tela de função executa o payload (window.__pwn, alert, erro de JS), inclusive
    ao enviar o formulário com valor inválido e ao abrir o resultado."""
    fn = mundo_xss(payload)
    if fn is None:
        return
    e = modelos.Execucao.objects.filter(funcao=fn).first()
    caminhos = [(mundo7.adm, reverse("funcoes:catalogo")), (mundo7.adm, reverse("funcoes:editar", kwargs={"pk": fn.pk})),
                (mundo7.bA, reverse("funcoes:catalogo")), (mundo7.bA, reverse("funcoes:executar", kwargs={"pk": fn.pk})),
                (mundo7.bA, reverse("execucoes:lista"))]
    if e is not None:
        caminhos += [(mundo7.bA, reverse("funcoes:resultado", kwargs={"pk": e.pk})),
                     (mundo7.adm, reverse("funcoes:resultado", kwargs={"pk": e.pk}))]
    paginas = {}
    for usuario, caminho in caminhos:
        p = paginas.setdefault(usuario.pk, abrir_pagina(usuario))
        p.goto(p.live_url + caminho)
        p.wait_for_load_state("networkidle")
        for sel in ("summary", "[data-menu]", "button"):
            for el in p.query_selector_all(sel)[:4]:
                try:
                    el.hover(timeout=300)
                except Exception:
                    pass
        assert p.evaluate("window.__pwn") is None, caminho
        assert p.dialogos == [] and [x for x in p.erros_js if "__pwn" in x] == [], caminho
