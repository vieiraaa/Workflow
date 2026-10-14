"""Adversarial M7a · injeção via parâmetros, tipos trocados, payload grande e credencial nunca no resultado (FUN-07/08/11, SEG-18)."""
import json

import pytest
from django.urls import reverse

from tests.acceptance.m7a.conftest import entrada, grafo_func, html, texto

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m7a")]


def _url(fn):
    return reverse("funcoes:executar", kwargs={"pk": fn.pk})


@pytest.fixture
def fn_tipos(mundo7, criar_funcao, mk_fluxo7):
    return criar_funcao(mk_fluxo7(mundo7.A, grafo=grafo_func("{{ $parametros.nome }}")), nome="F Tipos", entradas=[
        entrada("nome", rotulo="Nome"), entrada("qtd", "numero", rotulo="Qtd"), entrada("dia", "data", rotulo="Dia"),
        entrada("cor", "lista", rotulo="Cor", opcoes=["azul", "verde"]), entrada("ok", "booleano", rotulo="Ok")])


INJECOES = ["{{ $env }}", "{{ $env.CREDENCIAIS_CHAVE }}", "{{ $parametros }}", "{{ $execution }}", "${7*7}", "{{7*7}}",
            "{% debug %}", "{{ constructor.constructor('return process')() }}", "');require('fs')//", "\\u0000", "`${process.env}`",
            "{{ $('Calc').all() }}", "{{ $workflow }}", "$parametros.nome", "=1+1", "' OR '1'='1", "../../etc/passwd",
            "{{ __proto__ }}", "{{ $parametros.__proto__ }}"]


@pytest.mark.parametrize("valor", INJECOES)
def test_valor_hostil_e_so_dado_na_expressao(mundo7, fn_tipos, exec_funcao, no, jsons, valor):
    """FUN-08: nada do valor é avaliado; sai exatamente como digitado; execução termina com sucesso."""
    r, e = exec_funcao(mundo7.c["bA"], fn_tipos, {"nome": valor})
    assert r.status_code == 302 and e.status == "sucesso", getattr(e, "erro_resumo", None)
    assert jsons(no(e, "calc")) == [{"r": valor}] and e.parametros["nome"] == valor


def test_valor_hostil_no_codigo_e_em_http_nao_escapa(mundo7, criar_funcao, mk_fluxo7, exec_funcao, h, liberado, jsons, no):
    """FUN-08: valor em Código, URL, header e corpo do HTTP é dado; o servidor local recebe o texto literal, sem avaliação."""
    codigo = {"modo": "uma_vez_para_todos", "codigo": "return [{json: {v: $parametros.nome, t: typeof $parametros.nome}}];"}
    g = h.cadeia2(h.no2("c", "codigo", codigo, x=1, titulo="Cod"),
                  h.no2("h", "http", h.cfg_http2(f"{liberado.base}/eco", "POST", headers=[{"nome": "X-P", "valor": "{{ $parametros.nome }}"}],
                                                 corpo={"tipo": "json", "conteudo": '{"p": "{{ $parametros.nome }}"}'}),
                        x=2, titulo="H"))
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F Hostil", entradas=[entrada("nome")])
    valor = '"}, "admin": true, "x": {"a": "{{ $env }}'
    _, e = exec_funcao(mundo7.c["bA"], fn, {"nome": valor})
    assert e.status == "sucesso", e.erro_resumo
    assert jsons(no(e, "c"))[0]["v"] == valor
    req = liberado.hits("/eco")[0]
    assert req["headers"]["x-p"] == valor
    assert json.loads(req["corpo"]) == {"p": valor}  # o valor não quebrou o JSON do corpo


@pytest.mark.parametrize("dados,msg", [
    ({"nome": "a", "qtd": "1e999"}, None), ({"nome": "a", "qtd": "NaN"}, None), ({"nome": "a", "qtd": "Infinity"}, None),
    ({"nome": "a", "qtd": "0x10"}, "Qtd: informe um número."), ({"nome": "a", "qtd": "1,5,5"}, "Qtd: informe um número."),
    ({"nome": "a", "qtd": "9" * 400}, None), ({"nome": "a", "qtd": "٣"}, None),
    ({"nome": "a", "dia": "0000-00-00"}, "Dia: data inválida."), ({"nome": "a", "dia": "2026-13-01"}, "Dia: data inválida."),
    ({"nome": "a", "dia": "2026-1-1"}, None), ({"nome": "a", "dia": "99999-01-01"}, "Dia: data inválida."),
    ({"nome": "a", "cor": "AZUL"}, "Cor: opção inválida."), ({"nome": "a", "cor": "azul "}, None),
    ({"nome": "a", "cor": "azul\x00"}, None), ({"nome": "a", "ok": "talvez"}, "Ok: valor inválido."),
])
def test_tipos_trocados_e_limites_nunca_dao_500(mundo7, fn_tipos, exec_funcao, modelos, dados, msg):
    """FUN-07: entradas bizarras → erro de validação (200) ou execução limpa; NUNCA 500; mensagem exata quando a spec define."""
    r, e = exec_funcao(mundo7.c["bA"], fn_tipos, dados)
    assert r.status_code in (200, 302, 400), r.status_code
    if msg:
        assert r.status_code == 200 and msg in texto(r) and e is None
    if r.status_code == 302 and e is not None and e.parametros.get("qtd") is not None:
        assert json.dumps(e.parametros)  # serializável
        assert str(e.parametros["qtd"]).lower() not in ("nan", "inf", "infinity")


def test_valor_nao_numerico_infinito_e_recusado(mundo7, fn_tipos, exec_funcao):
    """FUN-07: numero precisa ser um número finito: 1e999/NaN/Infinity → "Qtd: informe um número." (nunca vira Infinity no JSON)."""
    for v in ("1e999", "NaN", "Infinity", "-Infinity"):
        r, e = exec_funcao(mundo7.c["bA"], fn_tipos, {"nome": "a", "qtd": v})
        assert r.status_code == 200 and e is None and "Qtd: informe um número." in texto(r), v


def test_campos_extras_valores_repetidos_e_tipos_de_formulario(mundo7, fn_tipos, exec_funcao):
    """FUN-07: campos extras ignorados; nome repetido/listas (nome=a&nome=b, nome[]=) não geram 500 nem parâmetros extras."""
    c = mundo7.c["bA"]
    for corpo in (b"nome=a&nome=b", b"nome[]=a&nome[]=b", b"nome=a&__proto__=x&constructor=y&parametros=z&modo=fluxo",
                  b"nome=a&" + b"x=1&" * 3000, b"nome"):
        r = c.post(_url(fn_tipos), data=corpo, content_type="application/x-www-form-urlencoded")
        assert r.status_code in (200, 302, 400), corpo[:30]
    r = c.post(_url(fn_tipos), data=json.dumps({"nome": "a"}), content_type="application/json")
    assert r.status_code in (200, 302, 400, 415)


def test_payload_enorme(mundo7, fn_tipos, exec_funcao, modelos):
    """FUN-07: texto de 3 MB / 501 caracteres → recusado (200 com mensagem ou 400/413), nada executado e sem 500."""
    for tam in (501, 3_000_000):
        r, e = exec_funcao(mundo7.c["bA"], fn_tipos, {"nome": "a" * tam})
        assert r.status_code in (200, 400, 413) and e is None, tam
    assert modelos.Execucao.objects.count() == 0


def test_usuario_no_formulario_de_execucao_nao_injeta_html_nem_muda_campos(mundo7, fn_tipos):
    """FUN-06: query string em GET ?nome=... não pré-preenche com dado arbitrário a ponto de alterar campos/opções do formulário."""
    r = mundo7.c["bA"].get(_url(fn_tipos), {"cor": "roxo", "qtd": "<b>x</b>"})
    assert r.status_code == 200 and "<b>x</b>" not in html(r)


# ---------------- credencial ----------------

SEGREDO = "SEGREDO-ADV-CRED-9f8e7d6c5b4a"


@pytest.fixture
def fn_cred(mundo7, criar_funcao, mk_fluxo7, h, liberado):
    mundo7.c["adm"].post(reverse("credenciais:nova"), {"nome": "CredAdv", "tipo": "bearer", "valor": SEGREDO, "setor": mundo7.A.pk})
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/eco", credencial="CredAdv"), x=1, titulo="Chamada"),
                  h.no2("calc", "editar_campos", h.cfg_editar([("auth", "{{ $json.headers.authorization }}", "texto")],
                                                              incluir_outros=True), x=2, titulo="Calc"))
    return criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F CredAdv", entradas=[entrada("nome")])


def test_credencial_ecoada_pelo_servidor_nao_aparece_no_resultado_nem_em_telas(mundo7, fn_tipos, fn_cred, exec_funcao, modelos):
    """FUN-11/SEG-18: o servidor devolve o header Authorization; o valor não aparece no resultado (tabela), nas telas do Adm,
    do executor, na lista, no catálogo, nem em nenhum campo gravado."""
    r, e = exec_funcao(mundo7.c["bB"], fn_cred, {"nome": "x"})
    assert e.status == "sucesso", e.erro_resumo
    telas = [reverse("funcoes:resultado", kwargs={"pk": e.pk}), reverse("funcoes:catalogo"), reverse("execucoes:lista"),
             reverse("inicio"), reverse("funcoes:executar", kwargs={"pk": fn_cred.pk})]
    for k in ("bB", "adm"):
        for url in telas:
            assert SEGREDO not in html(mundo7.c[k].get(url)), (k, url)
    assert SEGREDO not in html(mundo7.c["adm"].get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})))
    assert SEGREDO not in html(mundo7.c["adm"].get(reverse("funcoes:editar", kwargs={"pk": fn_cred.pk})))
    gravado = json.dumps([e.parametros, e.grafo_snapshot, [(n.entrada, n.saida, n.logs, n.erro_mensagem)
                                                          for n in modelos.ExecucaoNo.objects.filter(execucao=e)]], default=str)
    assert SEGREDO not in gravado


def test_executor_digitando_o_segredo_nao_o_ve_de_volta_no_resultado(mundo7, fn_tipos, fn_cred, exec_funcao):
    """FUN-11/MV2-25 a: valor de credencial digitado como parâmetro é mascarado no gravado e no resultado."""
    _, e = exec_funcao(mundo7.c["bB"], fn_cred, {"nome": f"teste {SEGREDO}"})
    assert e is not None
    for k in ("bB", "adm"):
        assert SEGREDO not in html(mundo7.c[k].get(reverse("funcoes:resultado", kwargs={"pk": e.pk})))
    assert SEGREDO not in json.dumps(e.parametros)


def test_parametro_nao_escolhe_credencial_de_outro_setor(mundo7, criar_funcao, mk_fluxo7, h, liberado, exec_funcao, no):
    """FUN-11: parâmetro com o nome de uma credencial restrita não troca a credencial usada nem a injeta."""
    mundo7.c["adm"].post(reverse("credenciais:nova"), {"nome": "CredSoB", "tipo": "bearer", "valor": "VALOR-SO-B", "setor": mundo7.B.pk})
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/eco", credencial="{{ $parametros.cred }}"), x=1, titulo="H"))
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F CredParam", entradas=[entrada("cred")])
    _, e = exec_funcao(mundo7.c["bB"], fn, {"cred": "CredSoB"})
    assert "VALOR-SO-B" not in json.dumps([liberado.requisicoes]) and e.status == "erro"
