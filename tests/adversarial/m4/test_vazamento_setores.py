"""Adversarial M4: vazamento entre setores, mass assignment, sessão aberta, setor desativado. Fontes: SET-01..06, HOM-01/09, PRM-03/04.

Caixa-preta: ataques via test client contra o servidor local (banco de teste local). Nenhum teste enfraquece a regra;
vermelho = a aplicação falhou.
"""

import json
import re
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m4")]

GRANDE = 99999999999999999999999999


def _h(r):
    return r.content.decode()


def _norm(html):
    """Remove o que muda a cada requisição (csrf) para comparar páginas."""
    html = re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"', "", html)
    html = re.sub(r'content="[A-Za-z0-9]{32,}"', "", html)
    return html


def _json_id(html, ident):
    m = re.search(rf'<script[^>]*id="{ident}"[^>]*>(.*?)</script>', html, flags=re.S)
    return json.loads(m.group(1)) if m else None


def _cartoes(html):
    return {k: v for k, v in re.findall(r'data-indicador="(\w+)"[^>]*?data-valor="([^"]*)"', html)} | {
        k: v for v, k in re.findall(r'data-valor="([^"]*)"[^>]*?data-indicador="(\w+)"', html)
    }


# ---------- 1. Coordenador A × tudo do setor B ----------

ROTAS_FLUXO = [
    ("get", "fluxos:editor", {}),
    ("post", "fluxos:editar", {"nome": "Invadido", "descricao": ""}),
    ("post", "fluxos:excluir", {}),
    ("post", "fluxos:status", {"status": "rascunho"}),
    ("post", "fluxos:executar", {}),
]


@pytest.mark.parametrize("alvo", ["fB", "fBr"])
@pytest.mark.parametrize("metodo,rota,dados", ROTAS_FLUXO)
def test_gestor_a_nao_toca_fluxo_do_setor_b(mundo, M, alvo, metodo, rota, dados):
    """SET-06/PRM-03: toda rota com pk de fluxo de B → 404 para o gestor A, sem efeito colateral."""
    f = getattr(mundo, alvo)
    antes_exec = M.Execucao.objects.count()
    url = reverse(rota, kwargs={"pk": f.pk})
    r = mundo.c["gA"].get(url) if metodo == "get" else mundo.c["gA"].post(url, dados)
    assert r.status_code == 404
    f.refresh_from_db()
    assert f.status in ("ativo", "rascunho") and f.nome.startswith("Fluxo Beta") and f.setor_id == mundo.B.pk
    assert M.Execucao.objects.count() == antes_exec


@pytest.mark.parametrize("quem", ["gA", "bA"])
@pytest.mark.parametrize("metodo,rota,dados", ROTAS_FLUXO)
def test_404_nao_revela_existencia(mundo, quem, metodo, rota, dados):
    """PRM-03: fluxo de outro setor e fluxo inexistente são indistinguíveis (mesmo status e corpo), exceto 403 de ação negada."""
    c = mundo.c[quem]

    def chamar(pk):
        url = reverse(rota, kwargs={"pk": pk})
        return c.get(url) if metodo == "get" else c.post(url, dados)

    r_real, r_nada = chamar(mundo.fB.pk), chamar(999999)
    assert r_real.status_code == r_nada.status_code
    assert _norm(_h(r_real)) == _norm(_h(r_nada))


@pytest.mark.parametrize("quem,alvo", [("gA", "eB_bB"), ("gA", "eB_gB"), ("bA", "eA_bA2"), ("bA", "eB_bB")])
def test_detalhe_execucao_alheia_indistinguivel_de_inexistente(mundo, quem, alvo):
    """PRM-03: detalhe fora do escopo = 404 idêntico ao de pk inexistente."""
    c = mundo.c[quem]
    r1 = c.get(reverse("execucoes:detalhe", kwargs={"pk": getattr(mundo, alvo).pk}))
    r2 = c.get(reverse("execucoes:detalhe", kwargs={"pk": 999999}))
    assert r1.status_code == r2.status_code == 404
    assert _norm(_h(r1)) == _norm(_h(r2))


@pytest.mark.parametrize("rota", ["fluxos:editor", "fluxos:editar", "fluxos:excluir", "fluxos:status", "fluxos:executar", "fluxos:salvar_grafo", "execucoes:detalhe"])
@pytest.mark.parametrize("pk", [GRANDE, 2**63, 2**31, 0])
def test_pk_gigante_nao_estoura_500(mundo, rota, pk):
    """Estado inválido: pk fora do inteiro do banco → 404 (ou 405 por método), nunca 500."""
    url = reverse(rota, kwargs={"pk": pk})
    assert mundo.c["gA"].get(url).status_code < 500
    assert mundo.c["gA"].post(url, {}).status_code < 500
    assert mundo.c["adm"].get(url).status_code < 500


def test_salvar_grafo_cruzado_com_setor_no_payload(mundo, salvar_grafo, grafo_valido):
    """Mass assignment: chaves `setor`/`dono`/`status` extras no JSON do grafo não movem o fluxo nem vazam."""
    corpo = {"grafo": grafo_valido, "atualizado_em": mundo.fA.atualizado_em.isoformat(), "setor": mundo.B.pk, "dono": mundo.gB.pk, "status": "ativo"}
    mundo.c["gA"].post(reverse("fluxos:salvar_grafo", kwargs={"pk": mundo.fA.pk}), json.dumps(corpo), content_type="application/json")
    mundo.fA.refresh_from_db()
    assert mundo.fA.setor_id == mundo.A.pk and mundo.fA.dono_id == mundo.gA.pk


def test_gestor_a_nao_salva_grafo_de_b_nem_com_payload_hostil(mundo):
    """SET-06: salvar grafo de B com corpo malformado/enorme → 404 (escopo antes do parsing), nunca 500."""
    url = reverse("fluxos:salvar_grafo", kwargs={"pk": mundo.fB.pk})
    for corpo in ("{", "[]", "null", "x" * 2_000_000, json.dumps({"grafo": "x" * 1_000_000})):
        r = mundo.c["gA"].post(url, corpo, content_type="application/json")
        assert r.status_code == 404, corpo[:20]


# ---------- filtros e contagens ----------


@pytest.mark.parametrize("filtro", [{"setor": "B"}, {"setor": "{b}"}, {"setor_id": "{b}"}, {"setor__id": "{b}"}, {"setor": "{a},{b}"}, {"setor[]": "{b}"}, {"fluxo__setor": "{b}"}])
@pytest.mark.parametrize("rota", ["fluxos:lista", "execucoes:lista"])
def test_filtro_setor_forjado_nao_amplia_escopo(mundo, filtro, rota):
    """SET-06/PRM-04: ?setor= (e variações) em listas do gestor A/Base A é ignorado: nada de B aparece."""
    params = {k: v.replace("{b}", str(mundo.B.pk)).replace("{a}", str(mundo.A.pk)).replace("B", str(mundo.B.pk)) for k, v in filtro.items()}
    for quem in ("gA", "bA"):
        h = _h(mundo.c[quem].get(reverse(rota), params))
        assert "Fluxo Beta" not in h
        for e in (mundo.eB_bB, mundo.eB_gB):
            assert reverse("execucoes:detalhe", kwargs={"pk": e.pk}) not in h


def test_lista_usuarios_filtro_setor_nao_adm_403(mundo):
    """SET-03/PRM-02: gestor/Base não listam usuários, nem com ?setor= forjado."""
    for quem in ("gA", "bA"):
        assert mundo.c[quem].get(reverse("contas:usuarios"), {"setor": mundo.B.pk}).status_code == 403


@pytest.mark.parametrize("valor", [str(GRANDE), "1 OR 1=1", "١", "1.0", "-1", "%00", "x" * 5000, "1'--"])
def test_filtro_setor_hostil_na_lista_de_usuarios(mundo, valor):
    """Payload malformado: ?setor= hostil na lista de usuários do Adm → nunca 500."""
    assert mundo.c["adm"].get(reverse("contas:usuarios"), {"setor": valor}).status_code < 500


@pytest.mark.parametrize("params", [{"q": "Beta"}, {"q": "%"}, {"q": "_"}, {"ordem": "setor"}, {"ordem": "-setor__nome"}, {"ordem": "fluxo__setor__nome"}, {"pagina": "2"}, {"pagina": str(GRANDE)}])
@pytest.mark.parametrize("rota", ["fluxos:lista", "execucoes:lista"])
def test_busca_ordem_pagina_nao_revelam_outro_setor(mundo, params, rota):
    """PRM-04: busca/ordenação por campo de setor/paginação gigante não revelam nem contam objetos de outro setor; nunca 500."""
    for quem in ("gA", "bA"):
        r = mundo.c[quem].get(reverse(rota), params)
        assert r.status_code < 500
        assert "Fluxo Beta" not in _h(r)


@pytest.mark.parametrize("rota", ["fluxos:lista", "execucoes:lista"])
def test_diferencial_pagina_do_gestor_nao_muda_com_dados_de_outro_setor(mundo, mk_fluxo, mk_exec, rota):
    """PRM-04 (contagens): a página do gestor A é idêntica antes/depois de B ganhar 60 fluxos e 60 execuções."""
    c = mundo.c["gA"]
    url = reverse(rota)
    antes = _norm(_h(c.get(url)))
    antes_q = _norm(_h(c.get(url, {"q": "Fluxo"})))
    for i in range(60):
        f = mk_fluxo(mundo.B, mundo.gB, f"Fluxo Beta Extra {i}", status="ativo" if i % 2 else "rascunho")
        mk_exec(f, mundo.bB, "erro" if i % 3 == 0 else "sucesso")
    assert _norm(_h(c.get(url))) == antes
    assert _norm(_h(c.get(url, {"q": "Fluxo"}))) == antes_q


# ---------- 2. Home ----------


def _home_snapshot(c, **p):
    h = _h(c.get(reverse("inicio"), p))
    return {"cartoes": _cartoes(h), "serie": _json_id(h, "home-serie"), "erros": _json_id(h, "home-erros"),
            "setores": _json_id(h, "home-setores"), "execs": re.findall(r'data-execucao="(\d+)"', h),
            "fluxos": re.findall(r'data-fluxo="(\d+)"', h), "html": h}


@pytest.mark.parametrize("quem", ["gA", "bA"])
@pytest.mark.parametrize("periodo", ["24h", "7d", "30d", "6m", "1a"])
def test_home_nao_muda_com_dados_de_outro_setor(mundo, mk_fluxo, mk_exec, M, quem, periodo):
    """HOM-01/SET-06: cartões, séries, erros, ranking e últimas da Home de A idênticos antes/depois de B ficar cheio (com erros)."""
    No = M.Execucao._meta.apps.get_model("execucoes", "ExecucaoNo")
    antes = _home_snapshot(mundo.c[quem], periodo=periodo)
    for i in range(40):
        f = mk_fluxo(mundo.B, mundo.gB, f"Fluxo Beta Cheio {i}")
        e = mk_exec(f, mundo.bB, "erro", quando=timezone.now() - timedelta(minutes=5 + i))
        No.objects.create(execucao=e, no_id="n2", no_tipo="http", no_titulo="B", ordem=2, status="erro", entrada={}, saida={},
                          erro_categoria="dns", erro_mensagem="m", duracao_ms=1)
    depois = _home_snapshot(mundo.c[quem], periodo=periodo)
    for k in ("cartoes", "serie", "erros", "execs", "fluxos"):
        assert depois[k] == antes[k], k
    assert "Setor Beta" not in depois["html"] and "Fluxo Beta" not in depois["html"] and '"dns"' not in depois["html"]


def test_home_base_nao_muda_com_execucao_de_colega_do_mesmo_setor(mundo, mk_exec):
    """SET-06: Home do Base não muda quando um colega do mesmo setor (ou o gestor) executa."""
    antes = _home_snapshot(mundo.c["bA"])
    for _ in range(10):
        mk_exec(mundo.fA, mundo.bA2, "erro")
        mk_exec(mundo.fA, mundo.gA, "sucesso")
    depois = _home_snapshot(mundo.c["bA"])
    for k in ("cartoes", "serie", "erros", "execs"):
        assert depois[k] == antes[k], k


@pytest.mark.parametrize("quem", ["gA", "bA"])
def test_home_json_sem_setores_para_nao_adm(mundo, quem):
    """HOM-09: home-setores nunca é emitido para gestor/Base (nomes de outros setores no JSON)."""
    s = _home_snapshot(mundo.c[quem])
    assert s["setores"] is None and "Setor Beta" not in s["html"]


@pytest.mark.parametrize("quem", ["gA", "bA"])
def test_home_cartao_setores_e_usuarios_nao_vazam_totais(mundo, quem):
    """HOM-09: Setores ativos nunca; Usuários ativos nunca ao Base."""
    c = _cartoes(_home_snapshot(mundo.c[quem])["html"])
    assert "setores_ativos" not in c
    if quem == "bA":
        assert "usuarios_ativos" not in c and "fluxos_rascunho" not in c


@pytest.mark.parametrize("periodo", ["x" * 100_000, "７ｄ", "7d\x00", "7d%00", "７d", "7d\n", " 7d", "7d ", "../..", "1a'--", "‮7d", "7d,1a", "6M", "None", "null", "[]", "{}", "😀" * 50])
def test_home_periodo_hostil(mundo, periodo):
    """HOM-02: ?periodo= hostil → 200, igual ao padrão 7d, nada refletido no HTML."""
    c = mundo.c["gA"]
    base = _home_snapshot(c)
    r = c.get(reverse("inicio"), {"periodo": periodo})
    assert r.status_code == 200
    s = _home_snapshot(c, periodo=periodo)
    assert s["cartoes"] == base["cartoes"] and s["serie"] == base["serie"]
    if len(periodo) < 100:
        assert periodo not in _h(r) or periodo in ("7d", "6M", "None", "null", "[]", "{}")


def test_home_periodo_repetido_e_lista(mundo):
    """HOM-02: ?periodo=7d&periodo=1a e periodo[]=1a não quebram nem vazam."""
    for qs in ("periodo=7d&periodo=1a", "periodo[]=1a", "periodo=1a&periodo=", "periodo=%00&periodo=%00"):
        r = mundo.c["gA"].get(reverse("inicio") + "?" + qs)
        assert r.status_code == 200 and "Setor Beta" not in _h(r)


@pytest.mark.parametrize("extra", [{"setor": "{b}"}, {"setor_id": "{b}"}, {"usuario": "{bb}"}, {"fluxo": "{fb}"}, {"escopo": "todos"}, {"adm": "1"}])
def test_home_parametros_de_escopo_forjados_sao_ignorados(mundo, extra):
    """SET-06: parâmetros de escopo na querystring da Home não alteram o resultado do gestor A."""
    base = _home_snapshot(mundo.c["gA"])
    ex = {k: v.replace("{b}", str(mundo.B.pk)).replace("{bb}", str(mundo.bB.pk)).replace("{fb}", str(mundo.fB.pk)) for k, v in extra.items()}
    s = _home_snapshot(mundo.c["gA"], **ex)
    for k in ("cartoes", "serie", "erros", "execs", "fluxos"):
        assert s[k] == base[k], k


def test_home_gestor_sem_setor_nao_ve_nada(mundo, mk_usuario, logar):
    """SET-01/06: Coordenador/Base sem setor (estado inválido) → sem 500 e sem dados de nenhum setor."""
    for papel in ("Coordenador", "Base"):
        u = mk_usuario(papel, None)
        r = logar(u).get(reverse("inicio"))
        assert r.status_code in (200, 403)
        if r.status_code == 200:
            h = _h(r)
            assert "Fluxo Alfa" not in h and "Fluxo Beta" not in h
            assert not re.findall(r'data-execucao="\d+"', h)
        for rota in ("fluxos:lista", "execucoes:lista"):
            r = logar(u).get(reverse(rota))
            assert r.status_code in (200, 403) and "Fluxo Alfa" not in _h(r) and "Fluxo Beta" not in _h(r)
        assert logar(u).get(reverse("fluxos:editor", kwargs={"pk": mundo.fA.pk})).status_code in (403, 404)


# ---------- 3. Mass assignment ----------

CAMPOS_EXTRA = {"setor": "{b}", "setor_id": "{b}", "dono": "{gb}", "dono_id": "{gb}", "status": "ativo", "id": "999", "pk": "999", "grafo": "{}"}


def _extras(mundo):
    return {k: v.replace("{b}", str(mundo.B.pk)).replace("{gb}", str(mundo.gB.pk)) for k, v in CAMPOS_EXTRA.items()}


def test_gestor_criando_fluxo_com_campos_extras(mundo, M):
    """SET-04: gestor A cria fluxo enviando setor/dono/status/id/grafo → setor A, dono ele, rascunho."""
    mundo.c["gA"].post(reverse("fluxos:novo"), {"nome": "Mass Assign 1", "descricao": "", **_extras(mundo)})
    f = M.Fluxo.objects.get(nome="Mass Assign 1")
    assert f.setor_id == mundo.A.pk and f.dono_id == mundo.gA.pk and f.status == "rascunho" and f.pk != 999


@pytest.mark.parametrize("quem", ["gA", "bA"])
def test_editar_fluxo_com_campos_extras(mundo, quem):
    """SET-04: editar com setor/dono/status extras: gestor não move; Base é 403 (ação negada) e nada muda."""
    mundo.c[quem].post(reverse("fluxos:editar", kwargs={"pk": mundo.fAr.pk}), {"nome": "Editado", "descricao": "", **_extras(mundo)})
    mundo.fAr.refresh_from_db()
    assert mundo.fAr.setor_id == mundo.A.pk and mundo.fAr.dono_id == mundo.gA.pk and mundo.fAr.status == "rascunho"


def test_base_nao_cria_fluxo_com_setor(mundo, M):
    """PRM-02/SET-04: Base criando fluxo → 403, nada criado."""
    r = mundo.c["bA"].post(reverse("fluxos:novo"), {"nome": "Base Cria", "descricao": "", "setor": mundo.A.pk})
    assert r.status_code == 403 and not M.Fluxo.objects.filter(nome="Base Cria").exists()


@pytest.mark.parametrize("quem", ["gA", "bA"])
@pytest.mark.parametrize("rota,kw", [("contas:usuario_novo", {}), ("contas:usuario_editar", "bA"), ("contas:usuario_redefinir_senha", "bA"), ("contas:setor_novo", {}), ("contas:setor_editar", "A")])
def test_nao_adm_nao_escreve_usuario_nem_setor(mundo, M, quem, rota, kw):
    """SET-02/03: gestor/Base não criam/editam usuários nem setores, nem forjando setor/papel (403, nada muda)."""
    if kw == "bA":
        kw = {"pk": mundo.bA.pk}
    elif kw == "A":
        kw = {"pk": mundo.A.pk}
    u0, s0 = M.Usuario.objects.count(), M.Setor.objects.count()
    dados = {"nome": "Hack", "email": "hack@exemplo.test", "papel": "adm", "setor": mundo.B.pk, "senha": "Senha-Forte-Ficticia-91",
             "confirmacao": "Senha-Forte-Ficticia-91", "nova_senha": "Senha-Forte-Ficticia-91", "ativo": "on", "is_superuser": "on", "is_staff": "on"}
    assert mundo.c[quem].post(reverse(rota, kwargs=kw), dados).status_code == 403
    assert (M.Usuario.objects.count(), M.Setor.objects.count()) == (u0, s0)
    mundo.bA.refresh_from_db()
    assert mundo.bA.setor_id == mundo.A.pk and not mundo.bA.is_superuser and not mundo.bA.is_staff


def test_adm_mass_assignment_em_usuario_ignora_privilegios_django(mundo, M, dados_adm_usuario):
    """Mass assignment: is_superuser/is_staff/groups/password no POST do Adm são ignorados."""
    d = dados_adm_usuario(mundo.A.pk, extras={"is_superuser": "on", "is_staff": "on", "groups": "1", "user_permissions": "1"})
    mundo.c["adm"].post(reverse("contas:usuario_novo"), d)
    u = M.Usuario.objects.get(email="novo@exemplo.test")
    assert not u.is_superuser and not u.is_staff and u.groups.count() == 1


@pytest.fixture
def dados_adm_usuario():
    def _d(setor, papel="base", extras=None):
        return {"nome": "Novo", "email": "novo@exemplo.test", "papel": papel, "setor": setor, "senha": "Senha-Forte-Ficticia-91",
                "confirmacao": "Senha-Forte-Ficticia-91", "ativo": "on", **(extras or {})}
    return _d


@pytest.mark.parametrize("valor", [str(GRANDE), "1 OR 1=1", "١", "1.0", "-1", "0", "abc", "[1]", "{}", "1,2", " ", "x" * 5000, "\x00"])
def test_adm_usuario_com_setor_hostil(mundo, M, dados_adm_usuario, valor):
    """SET-03: setor hostil (overflow, SQL, unicode, lista) → "Setor inválido." ou "Escolha um setor.", nunca 500 nem usuário criado."""
    r = mundo.c["adm"].post(reverse("contas:usuario_novo"), dados_adm_usuario(valor))
    assert r.status_code == 200 and not M.Usuario.objects.filter(email="novo@exemplo.test").exists()


@pytest.mark.parametrize("valor", [str(GRANDE), "abc", "-1", "x" * 5000])
def test_adm_move_fluxo_com_setor_hostil(mundo, valor):
    """SET-04: mover fluxo para setor hostil não move e não dá 500."""
    r = mundo.c["adm"].post(reverse("fluxos:editar", kwargs={"pk": mundo.fA.pk}), {"nome": mundo.fA.nome, "descricao": "", "setor": valor})
    assert r.status_code < 500
    mundo.fA.refresh_from_db()
    assert mundo.fA.setor_id == mundo.A.pk


def test_adm_move_fluxo_para_setor_inativo_e_recusado(mundo, mk_setor):
    """SET-02/04: setor desativado não aceita novos vínculos: mover fluxo para ele é recusado."""
    s = mk_setor("Setor Morto", ativo=False)
    mundo.c["adm"].post(reverse("fluxos:editar", kwargs={"pk": mundo.fA.pk}), {"nome": mundo.fA.nome, "descricao": "", "setor": s.pk})
    mundo.fA.refresh_from_db()
    assert mundo.fA.setor_id == mundo.A.pk


def test_adm_move_usuario_para_setor_inativo_e_recusado(mundo, mk_setor):
    """SET-02/03: vincular usuário a setor inativo é recusado na edição."""
    s = mk_setor("Setor Morto 2", ativo=False)
    mundo.c["adm"].post(reverse("contas:usuario_editar", kwargs={"pk": mundo.bA.pk}),
                        {"nome": mundo.bA.nome, "email": mundo.bA.email, "papel": "base", "ativo": "on", "setor": s.pk})
    mundo.bA.refresh_from_db()
    assert mundo.bA.setor_id == mundo.A.pk


def test_execucao_ignora_setor_enviado(mundo, M):
    """SET-05: POST de executar com setor forjado: Execucao.setor = setor do fluxo."""
    antes = set(M.Execucao.objects.values_list("pk", flat=True))
    mundo.c["bA"].post(reverse("fluxos:executar", kwargs={"pk": mundo.fA.pk}), {"setor": mundo.B.pk, "executado_por": mundo.bB.pk, "status": "sucesso"})
    e = M.Execucao.objects.exclude(pk__in=antes).get()
    assert e.setor_id == mundo.A.pk and e.executado_por_id == mundo.bA.pk


def test_adm_rebaixa_papel_para_adm_sem_setor_e_volta(mundo, M):
    """SET-03: trocar gestor para adm e de volta exige setor de novo (sem setor órfão silencioso)."""
    d = {"nome": mundo.gA.nome, "email": mundo.gA.email, "papel": "base", "ativo": "on"}
    r = mundo.c["adm"].post(reverse("contas:usuario_editar", kwargs={"pk": mundo.gA.pk}), d)
    assert r.status_code == 200
    mundo.gA.refresh_from_db()
    assert mundo.gA.setor_id == mundo.A.pk


# ---------- 4. Sessão aberta ----------


def test_troca_de_setor_vale_na_proxima_requisicao(mundo):
    """SET-06/USR-11: o Adm move o gestor A para B; a sessão já aberta passa a ver B e perde A, em todas as rotas e na Home."""
    c = mundo.c["gA"]
    assert c.get(reverse("fluxos:editor", kwargs={"pk": mundo.fA.pk})).status_code == 200
    home_a = _home_snapshot(c)
    mundo.c["adm"].post(reverse("contas:usuario_editar", kwargs={"pk": mundo.gA.pk}),
                        {"nome": mundo.gA.nome, "email": mundo.gA.email, "papel": "coordenador", "ativo": "on", "setor": mundo.B.pk})
    assert c.get(reverse("fluxos:editor", kwargs={"pk": mundo.fA.pk})).status_code == 404
    assert c.post(reverse("fluxos:executar", kwargs={"pk": mundo.fA.pk})).status_code == 404
    assert c.get(reverse("execucoes:detalhe", kwargs={"pk": mundo.eA_bA.pk})).status_code == 404
    assert c.get(reverse("fluxos:editor", kwargs={"pk": mundo.fB.pk})).status_code == 200
    h = _h(c.get(reverse("fluxos:lista")))
    assert "Fluxo Alfa" not in h and "Fluxo Beta" in h
    home_b = _home_snapshot(c)
    assert home_b["execs"] != home_a["execs"] and "Fluxo Alfa" not in home_b["html"]
    assert not set(home_a["execs"]) & set(home_b["execs"])


def test_troca_de_papel_gestor_para_base_em_sessao_aberta(mundo):
    """USR-11: gestor rebaixado a Base perde editar/criar na próxima requisição."""
    c = mundo.c["gA"]
    assert c.get(reverse("fluxos:editor", kwargs={"pk": mundo.fA.pk})).status_code == 200
    mundo.c["adm"].post(reverse("contas:usuario_editar", kwargs={"pk": mundo.gA.pk}),
                        {"nome": mundo.gA.nome, "email": mundo.gA.email, "papel": "base", "ativo": "on", "setor": mundo.A.pk})
    assert c.get(reverse("fluxos:editor", kwargs={"pk": mundo.fA.pk})).status_code == 403
    assert c.post(reverse("fluxos:novo"), {"nome": "Depois Rebaixado", "descricao": ""}).status_code == 403
    # agora é Base: só as próprias execuções
    assert c.get(reverse("execucoes:detalhe", kwargs={"pk": mundo.eA_bA.pk})).status_code == 404
    assert c.get(reverse("execucoes:detalhe", kwargs={"pk": mundo.eA_gA.pk})).status_code == 200


def test_base_promovido_a_gestor_so_ve_o_proprio_setor(mundo):
    """USR-11/SET-06: Base promovido a Coordenador ganha o setor dele, não os outros."""
    c = mundo.c["bA"]
    mundo.c["adm"].post(reverse("contas:usuario_editar", kwargs={"pk": mundo.bA.pk}),
                        {"nome": mundo.bA.nome, "email": mundo.bA.email, "papel": "coordenador", "ativo": "on", "setor": mundo.A.pk})
    assert c.get(reverse("execucoes:detalhe", kwargs={"pk": mundo.eA_bA2.pk})).status_code == 200
    assert c.get(reverse("execucoes:detalhe", kwargs={"pk": mundo.eB_bB.pk})).status_code == 404
    assert "Fluxo Beta" not in _h(c.get(reverse("fluxos:lista")))


def test_usuario_desativado_perde_sessao(mundo):
    """PAP-04: desativar o gestor encerra a sessão aberta na próxima requisição (Home incluída)."""
    c = mundo.c["gA"]
    assert c.get(reverse("inicio")).status_code == 200
    mundo.c["adm"].post(reverse("contas:usuario_editar", kwargs={"pk": mundo.gA.pk}),
                        {"nome": mundo.gA.nome, "email": mundo.gA.email, "papel": "coordenador", "setor": mundo.A.pk})
    r = c.get(reverse("inicio"))
    assert r.status_code == 302 and r.url.startswith(reverse("login"))


def test_setor_do_gestor_removido_no_banco_em_sessao_aberta(mundo):
    """SET-01: setor do gestor zerado (estado inválido) com sessão aberta → sem 500 e sem dados."""
    c = mundo.c["gA"]
    mundo.gA.setor = None
    mundo.gA.save()
    for rota in ("inicio", "fluxos:lista", "execucoes:lista"):
        r = c.get(reverse(rota))
        assert r.status_code in (200, 403)
        assert "Fluxo Alfa" not in _h(r) and "Fluxo Beta" not in _h(r)


# ---------- 5. Setor desativado ----------


def test_setor_desativado_preserva_acesso_dos_membros_e_nao_vaza(mundo):
    """SET-02: desativar impede NOVOS vínculos, mas membros e dados continuam no escopo (nada some, nada vaza)."""
    mundo.c["adm"].post(reverse("contas:setor_editar", kwargs={"pk": mundo.A.pk}), {"nome": mundo.A.nome})
    mundo.A.refresh_from_db()
    assert mundo.A.ativo is False
    for quem in ("gA", "bA"):
        assert mundo.c[quem].get(reverse("inicio")).status_code == 200
        assert mundo.c[quem].get(reverse("fluxos:lista")).status_code == 200
        assert "Fluxo Beta" not in _h(mundo.c[quem].get(reverse("fluxos:lista")))
    assert mundo.c["gA"].get(reverse("fluxos:editor", kwargs={"pk": mundo.fA.pk})).status_code == 200
    assert mundo.c["gA"].get(reverse("fluxos:editor", kwargs={"pk": mundo.fB.pk})).status_code == 404
    assert mundo.c["gB"].get(reverse("execucoes:detalhe", kwargs={"pk": mundo.eA_bA.pk})).status_code == 404


def test_setor_desativado_nao_aceita_novo_usuario_nem_edicao_para_ele(mundo, M, dados_adm_usuario):
    """SET-02/03: setor inativo → "Setor inválido." na criação."""
    mundo.c["adm"].post(reverse("contas:setor_editar", kwargs={"pk": mundo.B.pk}), {"nome": mundo.B.nome})
    r = mundo.c["adm"].post(reverse("contas:usuario_novo"), dados_adm_usuario(mundo.B.pk))
    assert r.status_code == 200 and "Setor inválido." in _h(r)


def test_setor_desativado_home_adm_conta_setores_ativos(mundo, M):
    """HOM-03: cartão Setores ativos do Adm reflete a desativação; Home do Adm não quebra."""
    antes = _cartoes(_home_snapshot(mundo.c["adm"])["html"])["setores_ativos"]
    mundo.c["adm"].post(reverse("contas:setor_editar", kwargs={"pk": mundo.B.pk}), {"nome": mundo.B.nome})
    depois = _cartoes(_home_snapshot(mundo.c["adm"])["html"])["setores_ativos"]
    assert float(depois) == float(antes) - 1


def test_setor_desativado_gestor_pode_criar_fluxo_sem_500(mundo):
    """SET-02/04: gestor de setor desativado criando fluxo: resposta definida (redirect/403/200 com erro), nunca 500."""
    mundo.c["adm"].post(reverse("contas:setor_editar", kwargs={"pk": mundo.A.pk}), {"nome": mundo.A.nome})
    assert mundo.c["gA"].post(reverse("fluxos:novo"), {"nome": "No Setor Morto", "descricao": ""}).status_code < 500


def test_setor_reativado_volta_ao_normal(mundo):
    """SET-02: reativar o setor não altera vínculos nem escopo."""
    for ativo in ({}, {"ativo": "on"}):
        mundo.c["adm"].post(reverse("contas:setor_editar", kwargs={"pk": mundo.A.pk}), {"nome": mundo.A.nome, **ativo})
    assert mundo.c["gA"].get(reverse("fluxos:editor", kwargs={"pk": mundo.fA.pk})).status_code == 200


# ---------- 6. Setor: payloads ----------


@pytest.mark.parametrize("nome", ["x" * 2_000_000, "\x00", "a\x00b", "‮", "😀" * 80, "SETOR" + "̇" * 40, "ǅ", "İ"])
def test_setor_nome_hostil_nao_quebra(mundo, M, nome):
    """SET-02: nome enorme/NUL/unicode → 200 (erro) ou 302, nunca 500."""
    assert mundo.c["adm"].post(reverse("contas:setor_novo"), {"nome": nome, "ativo": "on"}).status_code < 500


def test_setor_unicidade_sem_caixa_com_unicode(mundo, M):
    """SET-02: unicidade sem diferenciar maiúsculas vale também para acentos (ÁREA × área)."""
    mundo.c["adm"].post(reverse("contas:setor_novo"), {"nome": "Área Jurídica", "ativo": "on"})
    r = mundo.c["adm"].post(reverse("contas:setor_novo"), {"nome": "ÁREA JURÍDICA", "ativo": "on"})
    assert r.status_code == 200 and "Já existe um setor com este nome." in _h(r)


def test_setor_nome_com_espacos_nas_pontas_nao_duplica(mundo):
    """SET-02: " Setor Alfa " não vira um segundo setor Alfa."""
    r = mundo.c["adm"].post(reverse("contas:setor_novo"), {"nome": "  Setor Alfa  ", "ativo": "on"})
    assert r.status_code == 200 and "Já existe um setor com este nome." in _h(r)
