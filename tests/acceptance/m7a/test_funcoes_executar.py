"""Aceite M7a · execução, validação, $parametros, concorrência, credenciais (FUN-06, 07, 08, 11, 12)."""
import copy
import json

import pytest
from django.urls import reverse
from django.utils import timezone

from .conftest import entrada, grafo_func, html, texto

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m7a")]


def _url(fn):
    return reverse("funcoes:executar", kwargs={"pk": fn.pk})


def _saida(no, e, id_="calc"):
    return [i["json"] for i in no(e, id_).saida]


# ---------------- FUN-06 ----------------

def test_sem_entradas_post_direto_executa_e_redireciona_ao_resultado(mundo7, criar_funcao, mk_fluxo7, exec_funcao):
    """FUN-06: sem entradas, POST executa síncrono e redireciona (302) para funcoes:resultado; campos gravados."""
    f = mk_fluxo7(mundo7.A, grafo=grafo_func("ola"))
    fn = criar_funcao(f, nome="F Direta")
    r, e = exec_funcao(mundo7.c["bA"], fn)
    assert r.status_code == 302 and r["Location"] == reverse("funcoes:resultado", kwargs={"pk": e.pk})
    assert e.status == "sucesso" and e.modo == "para_mim" and e.executado_por_id == mundo7.bA.pk
    assert e.setor_id == f.setor_id and e.funcao_id == fn.pk and e.funcao_nome == "F Direta" and e.funcao_versao == 1
    assert e.parametros == {}


def test_get_com_entradas_mostra_formulario_com_padroes(mundo7, criar_funcao, mk_fluxo7):
    """FUN-06/FUN-13: GET mostra formulário (campos com rótulo, valor padrão); data 'hoje' resolvida na hora."""
    fn = criar_funcao(mk_fluxo7(mundo7.A), nome="F Form", entradas=[
        entrada("nome", "texto", rotulo="Seu nome", padrao="Ana"), entrada("dia", "data", rotulo="Dia", padrao="hoje"),
        entrada("cor", "lista", rotulo="Cor", opcoes=["azul", "verde"], obrigatoria=True)])
    r = mundo7.c["bA"].get(_url(fn))
    assert r.status_code == 200
    campos = {c["nome"]: c for c in r.context["campos"]}
    assert r.context["funcao"].pk == fn.pk and "erros_gerais" in r.context
    assert campos["nome"]["valor"] == "Ana" and campos["cor"]["opcoes"] == ["azul", "verde"] and campos["cor"]["obrigatoria"]
    hoje = timezone.localdate()  # fuso America/Sao_Paulo (settings)
    assert campos["dia"]["valor"] == hoje.isoformat()
    assert "Seu nome" in texto(r)


def test_nao_executa_fora_do_escopo_inativa_ou_rascunho(mundo7, criar_funcao, mk_fluxo7, exec_funcao, modelos):
    """FUN-06: fora do escopo/inativa/versao 0 → 404 (Adm também, se inativa ou versao 0); nada executa."""
    f = mk_fluxo7(mundo7.A)
    de_b = criar_funcao(f, nome="F SoBeta", liberar_para="setores", setores=[mundo7.B.pk])
    inativa = criar_funcao(f, nome="F Inativa", ativa=False)
    rascunho = criar_funcao(f, nome="F Rascunho", publicar=False)
    casos = [("bA", de_b), ("cA", de_b), ("bA", inativa), ("adm", inativa), ("bA", rascunho), ("adm", rascunho)]
    for k, fn in casos:
        assert mundo7.c[k].get(_url(fn)).status_code == 404, (k, fn.nome)
        r, e = exec_funcao(mundo7.c[k], fn)
        assert r.status_code == 404 and e is None, (k, fn.nome)
    assert modelos.Execucao.objects.count() == 0
    assert mundo7.c["adm"].post(_url(de_b)).status_code == 302  # Adm executa qualquer função ativa e publicada


def test_anonimo_nao_executa(mundo7, criar_funcao, mk_fluxo7, modelos):
    """PRM-01: anônimo → 302 login; nada executa."""
    fn = criar_funcao(mk_fluxo7(mundo7.A), nome="F Anon")
    r = mundo7.anon.post(_url(fn))
    assert r.status_code == 302 and r["Location"].startswith(reverse("login")) and modelos.Execucao.objects.count() == 0


def test_executa_o_grafo_publicado_e_nao_o_atual(mundo7, criar_funcao, mk_fluxo7, exec_funcao, modelos, no, jsons):
    """FUN-04/FUN-06: editar o fluxo depois de publicar não muda a execução da função; republicar muda."""
    f = mk_fluxo7(mundo7.A, grafo=grafo_func("versao-um"))
    fn = criar_funcao(f, nome="F Congelada")
    modelos.Fluxo.objects.filter(pk=f.pk).update(grafo=grafo_func("versao-dois"))
    _, e = exec_funcao(mundo7.c["bA"], fn)
    assert jsons(no(e, "calc")) == [{"r": "versao-um"}]
    assert e.grafo_snapshot == fn.grafo_publicado
    mundo7.c["adm"].post(reverse("funcoes:publicar", kwargs={"pk": fn.pk}))
    _, e2 = exec_funcao(mundo7.c["bA"], fn)
    assert jsons(no(e2, "calc")) == [{"r": "versao-dois"}] and e2.funcao_versao == 2


def test_erro_do_fluxo_tambem_redireciona_ao_resultado(mundo7, criar_funcao, mk_fluxo7, exec_funcao, h, liberado):
    """FUN-06: sucesso ou erro → 302 para funcoes:resultado."""
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/status/500"), x=1, titulo="Falha"))
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F Erro")
    r, e = exec_funcao(mundo7.c["bA"], fn)
    assert e.status == "erro" and r.status_code == 302 and r["Location"] == reverse("funcoes:resultado", kwargs={"pk": e.pk})


# ---------------- FUN-07 ----------------

ENTRADAS = [entrada("nome", "texto", rotulo="Nome", obrigatoria=True), entrada("qtd", "numero", rotulo="Quantidade"),
            entrada("dia", "data", rotulo="Dia"), entrada("cor", "lista", rotulo="Cor", opcoes=["azul", "verde"]),
            entrada("ok", "booleano", rotulo="Confirmado")]


@pytest.fixture
def fn_entradas(mundo7, criar_funcao, mk_fluxo7):
    return criar_funcao(mk_fluxo7(mundo7.A, grafo=grafo_func("{{ $parametros.nome }}")), nome="F Entradas",
                        entradas=ENTRADAS)


@pytest.mark.parametrize("dados,msg", [
    ({"nome": ""}, "Preencha Nome."),
    ({"nome": "   "}, "Preencha Nome."),
    ({"nome": "a", "qtd": "abc"}, "Quantidade: informe um número."),
    ({"nome": "a", "dia": "31/12/2026"}, "Dia: data inválida."),
    ({"nome": "a", "dia": "2026-02-30"}, "Dia: data inválida."),
    ({"nome": "a", "cor": "roxo"}, "Cor: opção inválida."),
    ({"nome": "a" * 501}, "Nome: máximo de 500 caracteres."),
])
def test_validacao_de_parametros(mundo7, fn_entradas, exec_funcao, dados, msg):
    """FUN-07: mensagens exatas, 200 com o formulário (sem execução)."""
    r, e = exec_funcao(mundo7.c["bA"], fn_entradas, dados)
    assert r.status_code == 200 and e is None and msg in texto(r), texto(r)[:400]
    assert any(c.get("erro") for c in r.context["campos"]) or r.context["erros_gerais"]


def test_validacao_mantem_o_que_foi_digitado(mundo7, fn_entradas, exec_funcao):
    """FUN-07/FUN-13: ao errar, o formulário volta com os valores digitados."""
    r, _ = exec_funcao(mundo7.c["bA"], fn_entradas, {"nome": "", "qtd": "abc", "cor": "azul"})
    campos = {c["nome"]: c for c in r.context["campos"]}
    assert campos["qtd"]["valor"] == "abc" and campos["cor"]["valor"] == "azul"


def test_limites_validos_e_tipos_gravados(mundo7, fn_entradas, exec_funcao):
    """FUN-07: 500 caracteres ok; numero aceita inteiro/decimal/negativo; data ISO; lista válida; booleano; desconhecido ignorado."""
    r, e = exec_funcao(mundo7.c["bA"], fn_entradas, {"nome": "a" * 500, "qtd": "-3.5", "dia": "2026-02-28",
                                                      "cor": "verde", "ok": "on", "intruso": "x", "funcao": "99"})
    assert r.status_code == 302 and e.status == "sucesso"
    p = e.parametros
    assert p["nome"] == "a" * 500 and float(p["qtd"]) == -3.5 and p["dia"] == "2026-02-28" and p["cor"] == "verde"
    assert p["ok"] is True and "intruso" not in p and "funcao" not in p


def test_opcionais_vazios_e_booleano_ausente(mundo7, fn_entradas, exec_funcao):
    """FUN-07: só a obrigatória basta; booleano desmarcado → false."""
    r, e = exec_funcao(mundo7.c["bA"], fn_entradas, {"nome": "x"})
    assert r.status_code == 302 and e.parametros["nome"] == "x" and e.parametros.get("ok") in (False, None)


def test_padrao_de_data_ontem_resolvido_na_execucao(mundo7, criar_funcao, mk_fluxo7, exec_funcao):
    """FUN-05/FUN-06: padrão 'ontem' resolvido na hora de executar (America/Sao_Paulo)."""
    from datetime import timedelta
    fn = criar_funcao(mk_fluxo7(mundo7.A), nome="F Ontem", entradas=[entrada("dia", "data", padrao="ontem")])
    _, e = exec_funcao(mundo7.c["bA"], fn, {"dia": ""})
    assert e is not None and e.parametros["dia"] == (timezone.localdate() - timedelta(days=1)).isoformat()


@pytest.mark.parametrize("valor", ["a\x00b", "a\ud800b"])
def test_nul_e_surrogate_dao_400(mundo7, fn_entradas, exec_funcao, valor, modelos):
    """FUN-07/MV2-25 c: NUL/surrogate → 400, nada executa."""
    r, e = exec_funcao(mundo7.c["bA"], fn_entradas, {"nome": valor})
    assert r.status_code == 400 and e is None and modelos.Execucao.objects.count() == 0


# ---------------- FUN-08 ----------------

def test_parametro_nas_expressoes_e_por_colchetes(mundo7, criar_funcao, mk_fluxo7, exec_funcao, no, jsons, h):
    """FUN-08: $parametros.<nome> e $parametros["nome"]; nome inexistente → null."""
    g = h.cadeia2(h.no2("calc", "editar_campos", h.cfg_editar([
        ("a", "{{ $parametros.nome }}", "texto"), ("b", '{{ $parametros["nome"] }}', "texto"),
        ("c", "{{ $parametros.nada }}", "texto")]), x=1))
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F Param", entradas=[entrada("nome")])
    _, e = exec_funcao(mundo7.c["bA"], fn, {"nome": "Maria"})
    j = jsons(no(e, "calc"))[0]
    assert j["a"] == "Maria" and j["b"] == "Maria" and j["c"] in (None, "")


@pytest.mark.parametrize("valor", ["{{ $env }}", "{{ 1+1 }}", "{{ $json }}", "{{ $parametros.nome }}", "={{ 2*3 }}"])
def test_valor_do_parametro_e_dado_literal_na_expressao(mundo7, criar_funcao, mk_fluxo7, exec_funcao, no, jsons, valor):
    """FUN-08: valor digitado nunca é avaliado como expressão (aparece como texto literal)."""
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=grafo_func("{{ $parametros.nome }}")), nome="F Literal",
                      entradas=[entrada("nome")])
    _, e = exec_funcao(mundo7.c["bA"], fn, {"nome": valor})
    assert e.status == "sucesso" and jsons(no(e, "calc")) == [{"r": valor}]


def test_parametro_no_codigo_e_dado_nunca_codigo(mundo7, criar_funcao, mk_fluxo7, exec_funcao, no, jsons, h, modelos):
    """FUN-08: $parametros no Código é objeto congelado; valor com JS/aspas é só dado."""
    codigo = {"modo": "uma_vez_para_todos", "codigo": (
        "const congelado = Object.isFrozen($parametros); "
        "try { $parametros.nome = 'x'; } catch (e) {} "
        "return [{json: {v: $parametros.nome, tipo: typeof $parametros.nome, congelado}}];")}
    g = h.cadeia2(h.no2("c", "codigo", codigo, x=1, titulo="Cod"))
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F Cod", entradas=[entrada("nome")])
    malicioso = "'); process.exit(1); //\" `${1+1}` \\"
    _, e = exec_funcao(mundo7.c["bA"], fn, {"nome": malicioso})
    assert e.status == "sucesso", e.erro_resumo
    j = jsons(no(e, "c"))[0]
    assert j["v"] == malicioso and j["tipo"] == "string" and j["congelado"] is True


def test_fora_de_funcao_parametros_e_vazio(cliente_adm, executar, h, no, jsons):
    """FUN-08: fluxo executado direto: $parametros = {} (no Código e nas expressões)."""
    cod = {"modo": "uma_vez_para_todos",
           "codigo": "return [{json: {n: Object.keys($parametros).length, s: JSON.stringify($parametros)}}];"}
    g = h.cadeia2(h.no2("c", "codigo", cod, x=1, titulo="Cod"),
                  h.no2("calc", "editar_campos", h.cfg_editar([("r", "{{ $parametros.nome }}", "texto")]), x=2))
    _, e, _ = executar(cliente_adm, g)
    assert e.status == "sucesso" and e.modo == "fluxo" and e.funcao_id is None
    assert jsons(no(e, "c")) == [{"n": 0, "s": "{}"}]
    assert jsons(no(e, "calc"))[0]["r"] in (None, "")


# ---------------- FUN-11 ----------------

def test_credencial_pelo_setor_do_fluxo_e_nunca_vista(mundo7, criar_funcao, mk_fluxo7, exec_funcao, h, liberado, cliente_adm,
                                                       no, modelos):
    """FUN-11/CRD-02: Base do setor B executa função cujo fluxo é do setor A, com credencial do setor A; o valor
    nunca aparece na resposta nem nos dados gravados."""
    segredo = "SEGREDO-FUNCAO-XYZ-123"
    r = mundo7.c["adm"].post(reverse("credenciais:nova"), {"nome": "Cred A", "tipo": "bearer", "valor": segredo,
                                                           "setor": mundo7.A.pk})
    assert r.status_code == 302
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/eco", credencial="Cred A"), x=1, titulo="Chamada"))
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F Cred")
    r, e = exec_funcao(mundo7.c["bB"], fn, follow=True)
    assert e.status == "sucesso", e.erro_resumo
    assert liberado.hits("/eco")[0]["headers"]["authorization"] == f"Bearer {segredo}"
    assert segredo not in html(r) and segredo not in json.dumps(no(e, "h").saida) and segredo not in json.dumps(e.parametros)


def test_credencial_de_outro_setor_do_fluxo_e_erro_mesmo_para_o_setor_de_quem_executa(
        mundo7, criar_funcao, mk_fluxo7, exec_funcao, h, liberado, no):
    """FUN-11: vale o setor do FLUXO, não o de quem executa → erro 'credencial'."""
    mundo7.c["adm"].post(reverse("credenciais:nova"), {"nome": "Cred B", "tipo": "bearer", "valor": "v-b", "setor": mundo7.B.pk})
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/eco", credencial="Cred B"), x=1, titulo="Chamada"))
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F CredErrada")
    _, e = exec_funcao(mundo7.c["bB"], fn)
    assert e.status == "erro" and no(e, "h").erro_categoria == "credencial" and liberado.requisicoes == []


def test_parametro_nao_vira_credencial_nem_header_automatico(mundo7, criar_funcao, mk_fluxo7, exec_funcao, h, liberado):
    """FUN-11: parâmetro chamado 'credencial'/'authorization' não injeta credencial nem header."""
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/eco"), x=1, titulo="Chamada"))
    fn = criar_funcao(mk_fluxo7(mundo7.A, grafo=g), nome="F NaoCred",
                      entradas=[entrada("credencial"), entrada("authorization")])
    _, e = exec_funcao(mundo7.c["bA"], fn, {"credencial": "Cred A", "authorization": "Bearer X"})
    assert e.status == "sucesso" and "authorization" not in liberado.hits("/eco")[0]["headers"]


def test_parametros_gravados_sao_mascarados_por_valor_de_credencial(mundo7, criar_funcao, mk_fluxo7, exec_funcao):
    """MV2-25 a/FUN-06: se o usuário digitar o valor de uma credencial, o gravado em `parametros` sai mascarado."""
    segredo = "SEGREDO-DIGITADO-QWERTY-77"
    mundo7.c["adm"].post(reverse("credenciais:nova"), {"nome": "Cred M", "tipo": "bearer", "valor": segredo, "setor": ""})
    fn = criar_funcao(mk_fluxo7(mundo7.A), nome="F Mask", entradas=[entrada("nome")])
    _, e = exec_funcao(mundo7.c["bA"], fn, {"nome": f"x {segredo} y"})
    assert segredo not in json.dumps(e.parametros)


# ---------------- FUN-12 ----------------

def test_concorrencia_mesma_funcao_mesmo_usuario(mundo7, criar_funcao, mk_fluxo7, exec_funcao, modelos):
    """FUN-12: com execução em andamento da mesma função para o mesmo usuário, o POST volta ao catálogo com a
    mensagem e não cria execução; outro usuário não é afetado; terminada, libera."""
    fn = criar_funcao(mk_fluxo7(mundo7.A), nome="F Conc")
    em_curso = modelos.Execucao.objects.create(
        fluxo=fn.fluxo, fluxo_nome=fn.fluxo.nome, grafo_snapshot=copy.deepcopy(fn.grafo_publicado), status="executando",
        iniciada_em=timezone.now(), executado_por=mundo7.bA, setor=fn.fluxo.setor, funcao=fn, funcao_nome=fn.nome,
        funcao_versao=1, modo="para_mim")
    antes = modelos.Execucao.objects.count()
    r, e = exec_funcao(mundo7.c["bA"], fn, follow=True)
    assert r.redirect_chain[-1][0] == reverse("funcoes:catalogo") and e is None
    assert "Esta função já está em execução para você. Aguarde terminar." in texto(r)
    assert modelos.Execucao.objects.count() == antes
    _, e2 = exec_funcao(mundo7.c["bA2"], fn)
    assert e2 is not None and e2.status == "sucesso"
    modelos.Execucao.objects.filter(pk=em_curso.pk).update(status="sucesso", finalizada_em=timezone.now())
    _, e3 = exec_funcao(mundo7.c["bA"], fn)
    assert e3 is not None


def test_execucao_so_por_post_e_csrf(mundo7, criar_funcao, mk_fluxo7, modelos):
    """FUN-06/SEG: sem entradas, GET não executa; POST sem CSRF → 403."""
    from django.test import Client
    fn = criar_funcao(mk_fluxo7(mundo7.A), nome="F Csrf")
    mundo7.c["bA"].get(_url(fn))
    assert modelos.Execucao.objects.count() == 0
    c = Client(enforce_csrf_checks=True)
    c.force_login(mundo7.bA)
    assert c.post(_url(fn)).status_code == 403 and modelos.Execucao.objects.count() == 0
