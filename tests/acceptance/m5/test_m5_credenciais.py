"""Aceite M5 parte C: cofre de credenciais (CRD-01/02, SEG-18). Contrato: MV2-13, MV2-18 C1–C4. Só dados fictícios."""

import base64
import json

import pytest
from django.db import connection
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]

SEGREDO = "SEGREDO-CRED-VALOR-123"


def _html(r):
    return r.content.decode()


# ---------------- permissões e rotas ----------------

@pytest.mark.parametrize("rota,kw", [("credenciais:lista", {}), ("credenciais:nova", {})])
def test_telas_so_para_adm(rota, kw, cliente_adm, cliente_coordenador, cliente_base, cliente_anonimo):
    """CRD-01/MV2-18 C3: Adm 200; Coordenador/Base 403; anônimo → login."""
    url = reverse(rota, kwargs=kw)
    assert cliente_adm.get(url).status_code == 200
    assert cliente_coordenador.get(url).status_code == 403
    assert cliente_base.get(url).status_code == 403
    r = cliente_anonimo.get(url)
    assert r.status_code == 302 and r["Location"].startswith(reverse("login"))


def test_mutacoes_negadas_para_nao_adm_e_nada_muda(cliente_adm, cliente_coordenador, cliente_base, cliente_anonimo, criar_cred, Credencial):
    """CRD-01: criar/editar/excluir por Coordenador, Base e anônimo não alteram nada."""
    criar_cred()
    c = Credencial.objects.get()
    dados = {"nome": "Invasor", "tipo": "bearer", "valor": "x", "setor": ""}
    for cli in (cliente_coordenador, cliente_base, cliente_anonimo):
        assert cli.post(reverse("credenciais:nova"), dados).status_code in (302, 403)
        cli.post(reverse("credenciais:editar", kwargs={"pk": c.pk}), {**dados, "nome": "Mudado"})
        cli.post(reverse("credenciais:excluir", kwargs={"pk": c.pk}))
    assert Credencial.objects.count() == 1 and Credencial.objects.get().nome == "Digisac"


def test_editar_e_excluir_inexistente_404_e_excluir_so_post(cliente_adm, criar_cred, Credencial):
    """CRD-01/C3: pk inexistente → 404; excluir por GET → 405 e nada some."""
    assert cliente_adm.get(reverse("credenciais:editar", kwargs={"pk": 999999})).status_code == 404
    assert cliente_adm.post(reverse("credenciais:excluir", kwargs={"pk": 999999})).status_code == 404
    criar_cred()
    c = Credencial.objects.get()
    assert cliente_adm.get(reverse("credenciais:excluir", kwargs={"pk": c.pk})).status_code == 405
    assert Credencial.objects.count() == 1


# ---------------- criar / validar / editar / excluir ----------------

def test_criar_bearer_redireciona_com_toast_e_nao_mostra_o_valor(cliente_adm, criar_cred, Credencial, usuario_adm):
    """CRD-01/C3: sucesso → redirect credenciais:lista + 'Credencial <nome> salva.'; valor nunca exibido."""
    r = criar_cred()
    assert r.status_code == 302 and r["Location"] == reverse("credenciais:lista")
    c = Credencial.objects.get()
    assert (c.nome, c.tipo, c.setor, c.criado_por) == ("Digisac", "bearer", None, usuario_adm)
    lista = cliente_adm.get(r["Location"])
    assert "Credencial Digisac salva." in _html(lista) and "Digisac" in _html(lista) and SEGREDO not in _html(lista)


def test_valor_cifrado_em_repouso(criar_cred, Credencial):
    """SEG-18/CRD-01/C1: o valor em claro não aparece em nenhuma coluna da tabela."""
    criar_cred(valor=SEGREDO)
    tabela = Credencial._meta.db_table
    with connection.cursor() as cur:
        cur.execute(f'SELECT * FROM "{tabela}"')
        linhas = cur.fetchall()
    def _texto(o):
        return bytes(o).decode("latin-1") if isinstance(o, memoryview | bytes) else str(o)

    assert linhas and SEGREDO not in json.dumps(linhas, default=_texto)
    assert SEGREDO not in str(Credencial.objects.values())


def test_tela_de_edicao_nunca_devolve_o_valor(cliente_adm, criar_cred, Credencial):
    """CRD-01: editar exibe o campo vazio ('manter atual'), sem o valor salvo."""
    criar_cred()
    c = Credencial.objects.get()
    html = _html(cliente_adm.get(reverse("credenciais:editar", kwargs={"pk": c.pk})))
    assert SEGREDO not in html and "Digisac" in html


@pytest.mark.parametrize("dados,msg", [
    ({"nome": ""}, "Este campo é obrigatório."), ({"nome": "n" * 81}, "Use no máximo 80 caracteres."),
    ({"valor": ""}, "Este campo é obrigatório."), ({"tipo": "oauth"}, "Valor inválido."),
    ({"setor": "999999"}, "Valor inválido."),
    ({"tipo": "header", "header_nome": ""}, "Este campo é obrigatório."),
    ({"tipo": "basic", "usuario": ""}, "Este campo é obrigatório."),
])
def test_validacao_do_formulario(dados, msg, cliente_adm, Credencial):
    """CRD-01/MV2-18 C3: erros por campo, 200, nada salvo."""
    base = {"nome": "Cred", "tipo": "bearer", "valor": "v", "setor": ""}
    base.update(dados)
    r = cliente_adm.post(reverse("credenciais:nova"), base)
    assert r.status_code == 200 and msg in _html(r) and Credencial.objects.count() == 0


def test_nome_duplicado_sem_diferenciar_maiusculas(criar_cred, Credencial):
    """CRD-01/C3: nome único, sem diferenciar maiúsculas."""
    criar_cred(nome="Digisac")
    r = criar_cred(nome="DIGISAC", valor="outro")
    assert r.status_code == 200 and "Já existe uma credencial com este nome." in _html(r) and Credencial.objects.count() == 1


@pytest.mark.parametrize("tipo,extra", [("bearer", {}), ("header", {"header_nome": "X-Api-Key"}), ("basic", {"usuario": "maria"}),
                                        ("smtp", {"usuario": "u", "host": "smtp.exemplo.test", "porta": "587", "tls": "on"})])
def test_cria_os_quatro_tipos(tipo, extra, criar_cred, Credencial):
    """CRD-01: bearer|header|basic|smtp."""
    r = criar_cred(nome=f"C-{tipo}", tipo=tipo, **extra)
    assert r.status_code == 302 and Credencial.objects.get().tipo == tipo


def test_editar_vazio_mantem_e_novo_valor_troca_sem_revelar(cliente_adm, criar_cred, Credencial, fabrica_fluxo, liberado, h, usuario_adm):
    """CRD-01/CRD-02: valor vazio na edição mantém; valor novo substitui; a resposta nunca traz o antigo."""
    criar_cred(valor="VALOR-ANTIGO-AAA")
    c = Credencial.objects.get()
    url = reverse("credenciais:editar", kwargs={"pk": c.pk})
    r = cliente_adm.post(url, {"nome": "Digisac", "tipo": "bearer", "valor": "", "setor": ""}, follow=True)
    assert "Credencial Digisac salva." in _html(r) and "VALOR-ANTIGO-AAA" not in _html(r)
    executar_com_cred(cliente_adm, fabrica_fluxo, liberado, h)
    assert liberado.hits("/eco")[-1]["headers"]["authorization"] == "Bearer VALOR-ANTIGO-AAA"
    r = cliente_adm.post(url, {"nome": "Digisac", "tipo": "bearer", "valor": "VALOR-NOVO-BBB", "setor": ""}, follow=True)
    assert "VALOR-ANTIGO-AAA" not in _html(r) and "VALOR-NOVO-BBB" not in _html(r)
    executar_com_cred(cliente_adm, fabrica_fluxo, liberado, h)
    assert liberado.hits("/eco")[-1]["headers"]["authorization"] == "Bearer VALOR-NOVO-BBB"


def test_excluir_por_post(cliente_adm, criar_cred, Credencial):
    """CRD-01/C3: POST exclui, redirect para a lista com toast."""
    criar_cred()
    c = Credencial.objects.get()
    r = cliente_adm.post(reverse("credenciais:excluir", kwargs={"pk": c.pk}), follow=True)
    assert "Credencial Digisac excluída." in _html(r) and Credencial.objects.count() == 0


# ---------------- uso no nó HTTP (CRD-02) ----------------

def executar_com_cred(cliente, fabrica_fluxo, liberado, h, nome="Digisac", rota="/eco", fluxo=None, **cfg):
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}{rota}", credencial=nome, **cfg), x=1, titulo="Chamada"))
    f = fluxo or fabrica_fluxo(grafo=g, status="ativo")
    cliente.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    from django.apps import apps
    return apps.get_model("execucoes", "Execucao").objects.order_by("pk").last(), f


def test_bearer_injeta_authorization(cliente_adm, criar_cred, fabrica_fluxo, liberado, h):
    """CRD-02: bearer → Authorization: Bearer <valor>."""
    criar_cred()
    e, _ = executar_com_cred(cliente_adm, fabrica_fluxo, liberado, h)
    assert e.status == "sucesso" and liberado.hits("/eco")[0]["headers"]["authorization"] == f"Bearer {SEGREDO}"


def test_header_injeta_o_header_configurado(cliente_adm, criar_cred, fabrica_fluxo, liberado, h):
    """CRD-02: tipo header → o header_nome configurado."""
    criar_cred(tipo="header", header_nome="X-Chave-Ficticia")
    e, _ = executar_com_cred(cliente_adm, fabrica_fluxo, liberado, h)
    assert e.status == "sucesso" and liberado.hits("/eco")[0]["headers"]["x-chave-ficticia"] == SEGREDO


def test_basic_injeta_authorization_basic(cliente_adm, criar_cred, fabrica_fluxo, liberado, h):
    """CRD-02: basic → Authorization: Basic base64(usuario:valor)."""
    criar_cred(tipo="basic", usuario="maria", valor="senha-ficticia")
    e, _ = executar_com_cred(cliente_adm, fabrica_fluxo, liberado, h)
    esperado = "Basic " + base64.b64encode(b"maria:senha-ficticia").decode()
    assert e.status == "sucesso" and liberado.hits("/eco")[0]["headers"]["authorization"] == esperado


def test_credencial_inexistente_e_erro_credencial(cliente_adm, fabrica_fluxo, liberado, h, no):
    """CRD-02: credencial que não existe → erro do nó categoria 'credencial', nada enviado."""
    e, _ = executar_com_cred(cliente_adm, fabrica_fluxo, liberado, h, nome="Fantasma")
    assert e.status == "erro" and no(e, "h").erro_categoria == "credencial" and liberado.requisicoes == []


def test_credencial_smtp_no_http_e_erro(cliente_adm, criar_cred, fabrica_fluxo, liberado, h, no):
    """MV2-18 C4: tipo smtp não serve ao nó HTTP → erro 'credencial'."""
    criar_cred(nome="Correio", tipo="smtp", usuario="u", host="smtp.exemplo.test", porta="587")
    e, _ = executar_com_cred(cliente_adm, fabrica_fluxo, liberado, h, nome="Correio")
    assert e.status == "erro" and no(e, "h").erro_categoria == "credencial" and liberado.requisicoes == []


def test_credencial_de_outro_setor_e_erro_e_do_mesmo_setor_ou_global_funciona(
        cliente_adm, criar_cred, fluxo_no_setor, setor_a, setor_b, liberado, h, no):
    """CRD-02: credencial fora do setor do dono do fluxo → erro 'credencial'; global e do próprio setor → ok."""
    criar_cred(nome="DoB", setor=setor_b.pk)
    criar_cred(nome="DoA", setor=setor_a.pk)
    criar_cred(nome="Global", setor="")
    def rodar(nome):
        g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/eco", credencial=nome), x=1))
        f = fluxo_no_setor(setor_a, grafo=g, status="ativo")
        cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
        from django.apps import apps
        return apps.get_model("execucoes", "Execucao").objects.order_by("pk").last()
    e = rodar("DoB")
    assert e.status == "erro" and no(e, "h").erro_categoria == "credencial"
    assert rodar("DoA").status == "sucesso" and rodar("Global").status == "sucesso"


# ---------------- chave ausente / errada ----------------

def test_sem_chave_recusa_salvar_com_erro_claro(cliente_adm, settings, Credencial):
    """CRD-01/C2: sem CREDENCIAIS_CHAVE o POST dá 200 com erro que menciona 'chave'; nada salvo."""
    settings.CREDENCIAIS_CHAVE = ""
    r = cliente_adm.post(reverse("credenciais:nova"), {"nome": "X", "tipo": "bearer", "valor": "v", "setor": ""})
    assert r.status_code == 200 and "chave" in _html(r).lower() and Credencial.objects.count() == 0


def test_sem_chave_ou_chave_trocada_o_no_erra_com_categoria_credencial(
        cliente_adm, criar_cred, fabrica_fluxo, liberado, h, no, settings):
    """CRD-01/C2: chave ausente ou diferente da que cifrou → erro 'credencial' mencionando 'chave', sem 500."""
    from cryptography.fernet import Fernet
    criar_cred()
    for chave in ("", Fernet.generate_key().decode()):
        settings.CREDENCIAIS_CHAVE = chave
        e, _ = executar_com_cred(cliente_adm, fabrica_fluxo, liberado, h)
        n = no(e, "h")
        assert e.status == "erro" and n.erro_categoria == "credencial" and "chave" in n.erro_mensagem.lower()
        assert liberado.requisicoes == []


# ---------------- o valor nunca vaza (SEG-18) ----------------

def _tudo_gravado(e):
    from django.apps import apps
    partes = [json.dumps(e.grafo_snapshot, default=str), e.erro_resumo or "", e.fluxo_nome]
    for n in apps.get_model("execucoes", "ExecucaoNo").objects.filter(execucao=e):
        partes += [json.dumps([n.entrada, n.saida, n.requisicoes, getattr(n, "logs", None)], default=str), n.erro_mensagem or ""]
    return "\n".join(partes)


def test_valor_mascarado_em_requisicoes_entrada_saida_snapshot_e_tela(
        cliente_adm, criar_cred, fabrica_fluxo, liberado, h, no, caplog):
    """SEG-18/CRD-02/C4: valor nem no histórico, nem no snapshot, nem refletido na saída, nem na tela, nem em log."""
    caplog.set_level("DEBUG")
    criar_cred()
    e, f = executar_com_cred(cliente_adm, fabrica_fluxo, liberado, h, rota="/eco")
    assert e.status == "sucesso" and liberado.hits("/eco")[0]["headers"]["authorization"] == f"Bearer {SEGREDO}"
    n = no(e, "h")
    hs = {x["nome"].lower(): x["valor"] for x in n.requisicoes[0]["headers"]}
    assert hs["authorization"] == "••••"
    assert SEGREDO not in _tudo_gravado(e) and "••••" in json.dumps(n.saida, ensure_ascii=False)  # /eco reflete o header no corpo
    assert SEGREDO not in json.dumps(f.grafo) and "Digisac" in json.dumps(f.grafo)
    assert SEGREDO not in _html(cliente_adm.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})))
    assert SEGREDO not in _html(cliente_adm.get(reverse("fluxos:editor", kwargs={"pk": f.pk})))
    assert SEGREDO not in caplog.text


def test_valor_mascarado_em_mensagem_de_erro(cliente_adm, criar_cred, fabrica_fluxo, liberado, h, no):
    """SEG-18: erro do nó (http 401 cujo corpo reflete o token) não carrega o valor."""
    liberado.rotas["/nega"] = lambda req: (401, {"erro": "token invalido", "recebido": req["headers"].get("authorization")}, None)
    criar_cred()
    e, _ = executar_com_cred(cliente_adm, fabrica_fluxo, liberado, h, rota="/nega")
    assert e.status == "erro" and no(e, "h").erro_categoria == "http_4xx" and SEGREDO not in _tudo_gravado(e)
    assert SEGREDO not in _html(cliente_adm.get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})))


def test_export_nativo_lista_nomes_e_nunca_o_valor(cliente_adm, criar_cred, fabrica_fluxo, liberado, h):
    """IMP-01/SEG-18: credenciais_usadas = nomes; valor nunca no arquivo."""
    criar_cred()
    _, f = executar_com_cred(cliente_adm, fabrica_fluxo, liberado, h)
    r = cliente_adm.get(reverse("fluxos:exportar", kwargs={"pk": f.pk}))
    assert r.status_code == 200 and SEGREDO not in r.content.decode()
    assert json.loads(r.content)["credenciais_usadas"] == ["Digisac"]
    r2 = cliente_adm.get(reverse("fluxos:exportar_n8n", kwargs={"pk": f.pk}))
    assert r2.status_code == 200 and SEGREDO not in r2.content.decode()


def test_valor_mascarado_tambem_em_execucao_de_teste(cliente_adm, criar_cred, fabrica_fluxo, liberado, h, modelos):
    """SEG-18: Executar este nó (MV2-06) também mascara o valor da credencial."""
    criar_cred()
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/eco", credencial="Digisac"), x=1))
    f = fabrica_fluxo(grafo=g, status="rascunho")
    cliente_adm.post(reverse("fluxos:executar_no", kwargs={"pk": f.pk}), {"no_id": "h"})
    e = modelos.Execucao.objects.get(teste=True)
    assert SEGREDO not in _tudo_gravado(e)
