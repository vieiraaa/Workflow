"""Adversarial M5: prévia de expressão (MV2-23) e "Executar este nó" (MV2-06, MV2-12 L7, MV2-14 (3))."""

import json
import time

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]

SEGREDO = "SEGREDO-PREVIA-5e92aa"


@pytest.fixture
def fluxo(fabrica_fluxo, liberado, h):
    g = h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"),
                  h.no2("c", "editar_campos", h.cfg_editar([("r", "{{ $json.n + 1 }}", "numero")]), x=2, titulo="Calc"),
                  h.no2("h", "http", h.cfg_http2(f"{liberado.base}/ok"), x=3, titulo="HTTP"),
                  h.no2("cod", "codigo", {"modo": "uma_vez_para_todos", "codigo": "return $input.all();"}, x=4, titulo="Cod"),
                  dados_fixos={"d": h.itens({"n": 1, "segredo": "DADO-DO-DONO-DO-TESTE"}, {"n": 2})})
    return fabrica_fluxo(grafo=g, status="rascunho")


def _previa(cliente, f, expressao="{{ $json.n }}", no_id="c", campo="r", bruto=None, **kw):
    corpo = bruto if bruto is not None else json.dumps({"no_id": no_id, "campo": campo, "expressao": expressao})
    return cliente.post(reverse("fluxos:previa_expressao", kwargs={"pk": f.pk}), corpo, content_type="application/json", **kw)


def _teste(cliente, f, no_id="c"):
    return cliente.post(reverse("fluxos:executar_no", kwargs={"pk": f.pk}), {"no_id": no_id}, HTTP_ACCEPT="application/json")


# ---------------- prévia: permissões, CSRF, método ----------------

def test_previa_permissoes_metodo_e_csrf(cliente_adm, cliente_coordenador, cliente_base, cliente_anonimo, usuario_adm, fluxo):
    """MV2-23: só POST, ação fluxos.editar: Base 403, anônimo → login, GET 405, sem CSRF 403, pk inexistente 404."""
    assert _previa(cliente_base, fluxo).status_code == 403
    r = _previa(cliente_anonimo, fluxo)
    assert r.status_code == 302 and r["Location"].startswith(reverse("login"))
    assert cliente_adm.get(reverse("fluxos:previa_expressao", kwargs={"pk": fluxo.pk})).status_code == 405
    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_adm)
    assert _previa(c, fluxo).status_code == 403
    inex = type("F", (), {"pk": 999999})
    assert _previa(cliente_adm, inex).status_code == 404


def test_previa_e_executar_no_de_fluxo_de_outro_setor_sao_404(logar, setor_a, setor_b, fluxo_no_setor, h, liberado):
    """SET-06/PRM-03 (IDOR): Coordenador do setor B → 404 na prévia e no executar_no de fluxo do setor A; nenhuma execução criada."""
    f = fluxo_no_setor(setor_a, grafo=h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"), dados_fixos={"d": h.itens({"n": 1})}))
    coord_b, _ = logar("Coordenador", setor_b)
    assert _previa(coord_b, f, no_id="d").status_code == 404
    assert _teste(coord_b, f, "d").status_code == 404
    from django.apps import apps
    assert apps.get_model("execucoes", "Execucao").objects.count() == 0


# ---------------- prévia: dados só do próprio usuário ----------------

def test_previa_sem_execucao_de_teste_pede_para_executar(cliente_adm, fluxo):
    """MV2-23: sem execução de teste do usuário → {ok:false, erro: 'Execute o fluxo em teste para ver a prévia.'}."""
    r = _previa(cliente_adm, fluxo)
    assert r.status_code == 200 and r.json() == {"ok": False, "erro": "Execute o fluxo em teste para ver a prévia."}


def test_previa_nao_usa_dados_da_execucao_de_teste_de_outro_usuario(cliente_adm, fabrica_usuario, fluxo, logar, setor_a, modelos):
    """MV2-23/MV2-14 (3): a execução de teste de X NÃO alimenta a prévia de Y no mesmo fluxo (nem para outro Adm): Y recebe
    "Execute o fluxo em teste…" e nenhum dado de X."""
    assert _teste(cliente_adm, fluxo, "c").status_code == 200
    outro_adm, _ = logar("Adm")
    r = _previa(outro_adm, fluxo, "{{ $('Dados').first().json.segredo }}", no_id="c")
    assert "DADO-DO-DONO-DO-TESTE" not in r.content.decode()
    assert r.json()["ok"] is False
    r_dono = _previa(cliente_adm, fluxo, "{{ $('Dados').first().json.segredo }}", no_id="c")
    assert r_dono.json()["ok"] is True  # controle: o dono vê


def test_previa_nao_usa_execucao_oficial_nem_de_outro_fluxo(cliente_adm, fluxo, fabrica_fluxo, h, modelos):
    """MV2-23: só a ÚLTIMA execução de TESTE do próprio usuário NESTE fluxo conta: execução oficial e teste de outro fluxo não."""
    outro = fabrica_fluxo(grafo=h.cadeia2(h.no2("d", "sem_operacao", x=1, titulo="Dados"), h.no2("c", "sem_operacao", x=2),
                                          dados_fixos={"d": h.itens({"n": 99, "segredo": "DO-OUTRO-FLUXO"})}), status="ativo")
    _teste(cliente_adm, outro, "c")
    cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": fluxo.pk}))  # oficial
    r = _previa(cliente_adm, fluxo)
    assert r.json() == {"ok": False, "erro": "Execute o fluxo em teste para ver a prévia."}


# ---------------- prévia nunca executa nada ----------------

def test_previa_nunca_faz_requisicao_http_nem_roda_codigo_nem_cria_execucao(cliente_adm, fluxo, servidor, modelos):
    """MV2-23: prévia (de qualquer expressão, em qualquer nó) nunca executa nó: zero requisições ao servidor, zero Execucao/ExecucaoNo
    novas, e é rápida mesmo para um Código que dormiria."""
    _teste(cliente_adm, fluxo, "c")
    antes = (modelos.Execucao.objects.count(), modelos.ExecucaoNo.objects.count(), len(servidor.requisicoes))
    t0 = time.time()
    for expr in ("{{ $json.r }}", "{{ $('HTTP').first().json }}", "{{ $('Cod').first().json }}", "{{ $('HTTP').item.json.corpo }}",
                 "{{ $input.all().length }}", "{{ $now.toISO() }}"):
        for no_id in ("c", "h", "cod"):
            r = _previa(cliente_adm, fluxo, expr, no_id=no_id)
            assert r.status_code == 200 and r.json()["ok"] in (True, False)
    assert (modelos.Execucao.objects.count(), modelos.ExecucaoNo.objects.count(), len(servidor.requisicoes)) == antes
    assert time.time() - t0 < 10


def test_previa_nao_expoe_valor_de_segredo(cliente_adm, fabrica_fluxo, h, liberado, servidor, modelos):
    """MV2-23/SEG-09/21: header sensível digitado, refletido pelo servidor numa execução de teste, sai mascarado na prévia."""
    servidor.rotas["/reflete"] = lambda req: (200, {"auth": req["headers"].get("authorization"), "ok": 1}, None)
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/reflete", headers=[{"nome": "Authorization", "valor": f"Bearer {SEGREDO}"}]),
                        x=1, titulo="HTTP"))
    f = fabrica_fluxo(grafo=g, status="rascunho")
    _teste(cliente_adm, f, "h")
    for expr in ("{{ $('HTTP').first().json.auth }}", "{{ JSON.stringify($('HTTP').first().json) }}", "{{ $json }}"):
        r = _previa(cliente_adm, f, expr, no_id="h")
        assert SEGREDO not in r.content.decode(), expr


@pytest.mark.parametrize("expr", ["{{ " + "'a'" + "+'a'" * 900 + " }}", "{{ '" + "a" * 2001 + "' }}", "{{ $json.constructor }}", "{{ $json['con'+'structor'] }}",
                                   "{{ process.env }}", "{{ 'x'.padStart(3000000,'x') }}", "{{ " + "(" * 900 + "1" + ")" * 900 + " }}",
                                   "{{ __import__('os') }}", "{{ x = 1 }}", "{{ [1,2].map(x => x) }}", "{{ $('Nao existe').first() }}"])
def test_previa_com_expressao_hostil_responde_json_e_nao_vaza(expr, cliente_adm, fluxo):
    """MV2-23/MV2-10: expressão > 2.000 caracteres, proibida, gigante ou inválida → 200 {ok:false,erro} (ou valor inofensivo); nunca 500,
    nunca objeto do runtime."""
    _teste(cliente_adm, fluxo, "c")
    r = _previa(cliente_adm, fluxo, expr)
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] in (True, False)
    assert "Traceback" not in r.content.decode() and "[native code]" not in r.content.decode() and "<class" not in r.content.decode()
    if len(expr) > 2000 + 6:
        assert j["ok"] is False


@pytest.mark.parametrize("bruto", [b"", b"{", b"[]", b"null", b'"x"', b"{}", b'{"no_id": [], "campo": {}, "expressao": 5}',
                                    b'{"no_id": "zzz", "campo": "r", "expressao": "{{ 1 }}"}', b'{"no_id": "c", "campo": "r"}',
                                    b'{"no_id": "c", "campo": "r", "expressao": null}', b'{"no_id": "c", "campo": "r", "expressao": "\\ud800"}',
                                    b'{"no_id": "c\\u0000", "campo": "r", "expressao": "x"}', b"\xff\xfe\x00",
                                    b'{"no_id": "c", "campo": "r", "expressao": "' + b"a" * 5_000_000 + b'"}'])
def test_previa_com_payload_malformado_ou_enorme_nao_da_500(bruto, cliente_adm, fluxo):
    """MV2-23: JSON inválido, tipos errados, no_id inexistente, 5 MB → 4xx ou 200 {ok:false}; nunca 500."""
    _teste(cliente_adm, fluxo, "c")
    r = _previa(cliente_adm, fluxo, bruto=bruto)
    assert r.status_code < 500


# ---------------- rate limit ----------------

def test_previa_limite_de_30_por_minuto_por_usuario_com_429(cliente_adm, fluxo, fabrica_fluxo, logar):
    """MV2-23: 30 prévias por minuto POR USUÁRIO (somando fluxos): a 31ª → 429 com mensagem; outro usuário não é afetado."""
    outro_fluxo = fabrica_fluxo(status="rascunho")
    codigos = []
    for i in range(33):
        alvo = fluxo if i % 2 == 0 else outro_fluxo
        codigos.append(_previa(cliente_adm, alvo).status_code)
    assert all(c != 429 for c in codigos[:30]), codigos
    assert codigos[30] == 429 and codigos[-1] == 429, codigos
    r = _previa(cliente_adm, fluxo)
    assert r.status_code == 429 and r.content.decode().strip() and "Traceback" not in r.content.decode()
    outro_adm, _ = logar("Adm")
    assert _previa(outro_adm, fluxo).status_code != 429


def test_rate_limit_nao_pode_ser_burlado_por_cabecalhos_ou_corpo(cliente_adm, fluxo):
    """MV2-23: variar X-Forwarded-For, User-Agent, cookie extra ou o conteúdo da expressão não zera o contador do usuário."""
    for i in range(30):
        _previa(cliente_adm, fluxo, f"{{{{ {i} }}}}", HTTP_X_FORWARDED_FOR=f"10.0.0.{i}", HTTP_USER_AGENT=f"ua{i}")
    r = _previa(cliente_adm, fluxo, "{{ 1 }}", HTTP_X_FORWARDED_FOR="203.0.113.77", HTTP_USER_AGENT="outro")
    assert r.status_code == 429


# ---------------- executar_no ----------------

def test_executar_no_permissoes_metodo_e_csrf(cliente_adm, cliente_base, cliente_anonimo, usuario_adm, fluxo, modelos):
    """MV2-12 L7: só POST, só quem edita o fluxo: Base 403, anônimo login, GET 405, sem CSRF 403; nada criado."""
    url = reverse("fluxos:executar_no", kwargs={"pk": fluxo.pk})
    assert cliente_base.post(url, {"no_id": "c"}).status_code == 403
    r = cliente_anonimo.post(url, {"no_id": "c"})
    assert r.status_code == 302 and r["Location"].startswith(reverse("login"))
    assert cliente_adm.get(url).status_code == 405
    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_adm)
    assert c.post(url, {"no_id": "c"}).status_code == 403
    assert modelos.Execucao.objects.count() == 0


@pytest.mark.parametrize("no_id", ["", "zzz", "c' OR 1=1", "../../x", "c\x00", "__proto__", "c" * 5000, "c\nc"])
def test_executar_no_com_no_id_hostil_nao_da_500_nem_cria_execucao_de_lixo(no_id, cliente_adm, fluxo, modelos):
    """MV2-12 L7: no_id inexistente/hostil → 4xx (ou erro tratado); nunca 500; nenhuma execução sobre nó que não existe."""
    r = cliente_adm.post(reverse("fluxos:executar_no", kwargs={"pk": fluxo.pk}), {"no_id": no_id}, HTTP_ACCEPT="application/json")
    assert r.status_code < 500
    assert not modelos.Execucao.objects.filter(status="sucesso").exists()


def test_executar_no_sem_o_campo_ou_com_multivalorado(cliente_adm, fluxo):
    """MV2-12 L7: campo ausente ou repetido → 4xx; nunca 500."""
    url = reverse("fluxos:executar_no", kwargs={"pk": fluxo.pk})
    assert cliente_adm.post(url, {}, HTTP_ACCEPT="application/json").status_code < 500
    assert cliente_adm.post(url, {"no_id": ["c", "h"]}, HTTP_ACCEPT="application/json").status_code < 500


def test_execucao_de_teste_de_outro_usuario_e_404_para_todos_e_nao_vaza_em_lugar_nenhum(cliente_adm, cliente_coordenador, logar, fluxo, modelos):
    """MV2-14 (3)/L7 (IDOR): execução de teste de X → 404 para outro Adm, Coordenador e Base (detalhe) e anônimo → login; nunca na
    lista/Home; o nome do fluxo/dados do teste não aparecem."""
    assert _teste(cliente_adm, fluxo, "c").status_code == 200
    e = modelos.Execucao.objects.get(teste=True)
    url = reverse("execucoes:detalhe", kwargs={"pk": e.pk})
    outro_adm, _ = logar("Adm")
    assert cliente_adm.get(url).status_code == 200
    for c in (outro_adm, cliente_coordenador):
        assert c.get(url).status_code == 404
    for c in (outro_adm, cliente_coordenador, cliente_adm):
        for u in (reverse("execucoes:lista"), reverse("inicio")):
            assert fluxo.nome not in c.get(u).content.decode()


def test_executar_no_flood_nao_derruba_nem_vaza_threads(cliente_adm, fluxo, modelos):
    """MV2-06: 25 execuções de teste seguidas (nó com HTTP anterior ao alvo) terminam sem 500 e todas finalizadas."""
    for _ in range(25):
        assert _teste(cliente_adm, fluxo, "c").status_code in (200, 429)
    assert not modelos.Execucao.objects.filter(status="executando").exists()


def test_executar_no_nao_executa_nos_depois_do_alvo_nem_http_posterior(cliente_adm, fluxo, servidor, modelos, no):
    """MV2-06: rodar até o nó `c` nunca dispara o HTTP nem o Código que vêm depois (zero requisições)."""
    _teste(cliente_adm, fluxo, "c")
    e = modelos.Execucao.objects.get(teste=True)
    assert servidor.requisicoes == []
    assert not modelos.ExecucaoNo.objects.filter(execucao=e, no_id__in=["h", "cod"]).exclude(status="nao_executado").exists()
