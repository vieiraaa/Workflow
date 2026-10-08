"""Aceite M4: escopo por setor no sistema inteiro e gestão de setores. Fontes: SET-01..06, PRM-02/03/04, USR-01/04/06."""
import re
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m4")]


def _h(r):
    return r.content.decode()


# ---------- SET-01 ----------

def test_set01_setor_geral_existe_pela_migration(M):
    """SET-01: a migration de dados cria o setor "Geral"."""
    assert M.Setor.objects.filter(nome="Geral").exists()


def test_set01_adm_pode_ficar_sem_setor(mk_usuario):
    """SET-01: usuário sem setor só pode ser Adm; Adm sem setor é válido."""
    assert mk_usuario("Adm").setor is None


# ---------- SET-02 gestão de setores ----------

@pytest.mark.parametrize("rota,kw", [("contas:setores", {}), ("contas:setor_novo", {}), ("contas:setor_editar", {"pk": 1})])
def test_set02_anonimo_login(cliente_anonimo, rota, kw):
    """SET-02/PRM-01: rotas de setores exigem login."""
    r = cliente_anonimo.get(reverse(rota, kwargs=kw))
    assert r.status_code == 302 and r.url.startswith(reverse("login"))


@pytest.mark.parametrize("papel", ["gA", "bA"])
@pytest.mark.parametrize("rota", ["contas:setores", "contas:setor_novo"])
def test_set02_nao_adm_403(mundo, papel, rota):
    """SET-02/PRM-02: só Adm gerencia setores; Coordenador e Base recebem 403."""
    assert mundo.c[papel].get(reverse(rota)).status_code == 403


@pytest.mark.parametrize("papel", ["gA", "bA"])
def test_set02_nao_adm_nao_cria_nem_edita(mundo, M, papel):
    """SET-02: POST de não-Adm não altera nada (403)."""
    r = mundo.c[papel].post(reverse("contas:setor_novo"), {"nome": "Invasor", "ativo": "on"})
    assert r.status_code == 403 and not M.Setor.objects.filter(nome="Invasor").exists()
    r = mundo.c[papel].post(reverse("contas:setor_editar", kwargs={"pk": mundo.A.pk}), {"nome": "Hackeado", "ativo": "on"})
    assert r.status_code == 403
    mundo.A.refresh_from_db()
    assert mundo.A.nome == "Setor Alfa"


def test_set02_lista_mostra_setores(mundo):
    """SET-02/TEL-14: Adm vê a lista com os setores."""
    h = _h(mundo.c["adm"].get(reverse("contas:setores")))
    assert "Setor Alfa" in h and "Setor Beta" in h


def test_set02_criar_setor(mundo, M):
    """SET-02: Adm cria setor (campos nome, ativo)."""
    r = mundo.c["adm"].post(reverse("contas:setor_novo"), {"nome": "Financeiro Ficticio", "ativo": "on"})
    assert r.status_code == 302
    s = M.Setor.objects.get(nome="Financeiro Ficticio")
    assert s.ativo is True


def test_set02_criar_inativo(mundo, M):
    """SET-02: checkbox ativo ausente cria setor inativo."""
    mundo.c["adm"].post(reverse("contas:setor_novo"), {"nome": "Setor Dormente"})
    assert M.Setor.objects.get(nome="Setor Dormente").ativo is False


@pytest.mark.parametrize("nome", ["Setor Alfa", "setor alfa", "SETOR ALFA"])
def test_set02_nome_duplicado_sem_diferenciar_maiusculas(mundo, M, nome):
    """SET-02: nome único sem diferenciar maiúsculas; mensagem exata."""
    antes = M.Setor.objects.count()
    r = mundo.c["adm"].post(reverse("contas:setor_novo"), {"nome": nome, "ativo": "on"})
    assert r.status_code == 200 and "Já existe um setor com este nome." in _h(r)
    assert M.Setor.objects.count() == antes


@pytest.mark.parametrize("nome", ["", "   "])
def test_set02_nome_obrigatorio(mundo, M, nome):
    """SET-02: nome obrigatório."""
    antes = M.Setor.objects.count()
    r = mundo.c["adm"].post(reverse("contas:setor_novo"), {"nome": nome, "ativo": "on"})
    assert r.status_code == 200 and "Este campo é obrigatório." in _h(r)
    assert M.Setor.objects.count() == antes


def test_set02_nome_limite_80(mundo, M):
    """SET-02: máx. 80 caracteres (80 aceita, 81 recusa)."""
    assert mundo.c["adm"].post(reverse("contas:setor_novo"), {"nome": "a" * 80, "ativo": "on"}).status_code == 302
    r = mundo.c["adm"].post(reverse("contas:setor_novo"), {"nome": "b" * 81, "ativo": "on"})
    assert r.status_code == 200 and not M.Setor.objects.filter(nome="b" * 81).exists()


def test_set02_renomear_e_desativar(mundo, M):
    """SET-02: Adm renomeia e desativa."""
    r = mundo.c["adm"].post(reverse("contas:setor_editar", kwargs={"pk": mundo.B.pk}), {"nome": "Beta Renomeado"})
    assert r.status_code == 302
    mundo.B.refresh_from_db()
    assert mundo.B.nome == "Beta Renomeado" and mundo.B.ativo is False


def test_set02_renomear_para_nome_de_outro_recusa(mundo):
    """SET-02: renomear para nome existente → erro."""
    r = mundo.c["adm"].post(reverse("contas:setor_editar", kwargs={"pk": mundo.B.pk}), {"nome": "setor alfa", "ativo": "on"})
    assert r.status_code == 200 and "Já existe um setor com este nome." in _h(r)


def test_set02_editar_mantendo_proprio_nome_ok(mundo):
    """SET-02: salvar mantendo o próprio nome não é duplicidade."""
    r = mundo.c["adm"].post(reverse("contas:setor_editar", kwargs={"pk": mundo.A.pk}), {"nome": "Setor Alfa", "ativo": "on"})
    assert r.status_code == 302


def test_set02_editar_inexistente_404(mundo):
    """SET-02/PRM-03: setor inexistente → 404."""
    assert mundo.c["adm"].get(reverse("contas:setor_editar", kwargs={"pk": 999999})).status_code == 404


def test_set02_nao_existe_exclusao(mundo, M):
    """SET-02: setor não é excluído; DELETE/POST de exclusão não existem e o setor permanece."""
    from django.urls import NoReverseMatch
    with pytest.raises(NoReverseMatch):
        reverse("contas:setor_excluir", kwargs={"pk": mundo.A.pk})
    assert M.Setor.objects.filter(pk=mundo.A.pk).exists()


def test_set02_nome_escapado(mundo):
    """SET-02/SEG-13: nome de setor com <script> é escapado."""
    mundo.c["adm"].post(reverse("contas:setor_novo"), {"nome": "<script>alert(1)</script>", "ativo": "on"})
    h = _h(mundo.c["adm"].get(reverse("contas:setores")))
    assert "<script>alert(1)</script>" not in h and "&lt;script&gt;" in h


def test_set02_get_nao_muda_estado(mundo, M):
    """PRM-08: GET no formulário não cria nada."""
    antes = M.Setor.objects.count()
    mundo.c["adm"].get(reverse("contas:setor_novo"))
    assert M.Setor.objects.count() == antes


def test_set02_post_sem_csrf_403(mundo, M):
    """PRM-08: POST sem CSRF é recusado."""
    from django.test import Client
    c = Client(enforce_csrf_checks=True)
    c.force_login(mundo.adm)
    r = c.post(reverse("contas:setor_novo"), {"nome": "SemCsrf", "ativo": "on"})
    assert r.status_code == 403 and not M.Setor.objects.filter(nome="SemCsrf").exists()


# ---------- SET-03 usuários ----------

def _dados(setor=None, papel="base", email="novo@exemplo.test", **extra):
    d = {"nome": "Novo Usuario", "email": email, "papel": papel, "senha": "Senha-Forte-Ficticia-91",
         "confirmacao": "Senha-Forte-Ficticia-91", "ativo": "on"}
    if setor is not None:
        d["setor"] = setor
    d.update(extra)
    return d


@pytest.mark.parametrize("papel", ["base", "coordenador"])
def test_set03_setor_obrigatorio_fora_do_adm(mundo, M, papel):
    """SET-03: papel ≠ adm exige setor → "Escolha um setor.\""""
    r = mundo.c["adm"].post(reverse("contas:usuario_novo"), _dados(papel=papel))
    assert r.status_code == 200 and "Escolha um setor." in _h(r)
    assert not M.Usuario.objects.filter(email="novo@exemplo.test").exists()


@pytest.mark.parametrize("papel", ["base", "coordenador"])
def test_set03_cria_com_setor(mundo, M, papel):
    """SET-03: criar Base/Coordenador com setor válido."""
    r = mundo.c["adm"].post(reverse("contas:usuario_novo"), _dados(setor=mundo.A.pk, papel=papel))
    assert r.status_code == 302
    assert M.Usuario.objects.get(email="novo@exemplo.test").setor_id == mundo.A.pk


def test_set03_adm_sem_setor_ok(mundo, M):
    """SET-03: Adm pode ser criado sem setor."""
    assert mundo.c["adm"].post(reverse("contas:usuario_novo"), _dados(papel="adm")).status_code == 302
    assert M.Usuario.objects.get(email="novo@exemplo.test").setor is None


def test_set03_adm_com_setor_opcional(mundo, M):
    """SET-03: setor é opcional (não proibido) para Adm."""
    assert mundo.c["adm"].post(reverse("contas:usuario_novo"), _dados(setor=mundo.A.pk, papel="adm")).status_code == 302


@pytest.mark.parametrize("valor", ["999999", "abc", "-1", "0"])
def test_set03_setor_inexistente_ou_invalido(mundo, M, valor):
    """SET-03: setor inexistente/malformado → "Setor inválido." (nunca 500)."""
    r = mundo.c["adm"].post(reverse("contas:usuario_novo"), _dados(setor=valor))
    assert r.status_code == 200 and "Setor inválido." in _h(r)
    assert not M.Usuario.objects.filter(email="novo@exemplo.test").exists()


def test_set03_setor_inativo_recusado(mundo, mk_setor, M):
    """SET-03/SET-02: setor inativo não aceita novos vínculos → "Setor inválido.\""""
    s = mk_setor("Setor Inativo", ativo=False)
    r = mundo.c["adm"].post(reverse("contas:usuario_novo"), _dados(setor=s.pk))
    assert r.status_code == 200 and "Setor inválido." in _h(r)


def test_set03_editar_muda_setor(mundo):
    """SET-03: edição altera o setor do usuário."""
    r = mundo.c["adm"].post(reverse("contas:usuario_editar", kwargs={"pk": mundo.bA.pk}),
                            {"nome": mundo.bA.nome, "email": mundo.bA.email, "papel": "base", "ativo": "on", "setor": mundo.B.pk})
    assert r.status_code == 302
    mundo.bA.refresh_from_db()
    assert mundo.bA.setor_id == mundo.B.pk


def test_set03_editar_para_papel_nao_adm_exige_setor(mundo):
    """SET-03: editar sem setor com papel base → "Escolha um setor.\""""
    r = mundo.c["adm"].post(reverse("contas:usuario_editar", kwargs={"pk": mundo.bA.pk}),
                            {"nome": mundo.bA.nome, "email": mundo.bA.email, "papel": "base", "ativo": "on"})
    assert r.status_code == 200 and "Escolha um setor." in _h(r)


def test_set03_lista_usuarios_coluna_e_filtro(mundo):
    """SET-03/USR-01: lista ganha coluna Setor e filtro ?setor=<id>."""
    h = _h(mundo.c["adm"].get(reverse("contas:usuarios")))
    assert "Setor" in h and "Setor Alfa" in h and "Setor Beta" in h
    h = _h(mundo.c["adm"].get(reverse("contas:usuarios"), {"setor": mundo.A.pk}))
    assert mundo.bA.email in h and mundo.gA.email in h
    assert mundo.bB.email not in h and mundo.gB.email not in h


@pytest.mark.parametrize("valor", ["abc", "999999", "", "1;drop"])
def test_set03_filtro_setor_invalido_nao_quebra(mundo, valor):
    """SET-03/USR-02: filtro inválido é ignorado ou vazio, nunca 500."""
    assert mundo.c["adm"].get(reverse("contas:usuarios"), {"setor": valor}).status_code == 200


# ---------- SET-04 ----------

def test_set04_fluxo_criado_herda_setor_do_dono(mundo, M):
    """SET-04: Fluxo.setor = setor do dono na criação (Coordenador A cria → A)."""
    r = mundo.c["gA"].post(reverse("fluxos:novo"), {"nome": "Criado Pelo Gestor", "descricao": ""})
    assert r.status_code == 302
    assert M.Fluxo.objects.get(nome="Criado Pelo Gestor").setor_id == mundo.A.pk


def test_set04_gestor_nao_escolhe_setor_na_criacao(mundo, M):
    """SET-04: campo `setor` enviado por Coordenador é ignorado (só Adm muda o setor)."""
    mundo.c["gA"].post(reverse("fluxos:novo"), {"nome": "Tenta Outro Setor", "descricao": "", "setor": mundo.B.pk})
    assert M.Fluxo.objects.get(nome="Tenta Outro Setor").setor_id == mundo.A.pk


def test_set04_gestor_nao_move_fluxo_ao_editar(mundo):
    """SET-04: Coordenador não altera o setor ao editar (campo ignorado)."""
    mundo.c["gA"].post(reverse("fluxos:editar", kwargs={"pk": mundo.fA.pk}), {"nome": "Novo Nome A", "descricao": "", "setor": mundo.B.pk})
    mundo.fA.refresh_from_db()
    assert mundo.fA.setor_id == mundo.A.pk


def test_set04_adm_move_fluxo(mundo):
    """SET-04: Adm muda o setor do fluxo pelo formulário de edição."""
    r = mundo.c["adm"].post(reverse("fluxos:editar", kwargs={"pk": mundo.fA.pk}),
                            {"nome": mundo.fA.nome, "descricao": "", "setor": mundo.B.pk})
    assert r.status_code == 302
    mundo.fA.refresh_from_db()
    assert mundo.fA.setor_id == mundo.B.pk


def test_set04_adm_setor_invalido_recusado(mundo):
    """SET-04/SET-03: setor inexistente ao mover fluxo não altera nada."""
    mundo.c["adm"].post(reverse("fluxos:editar", kwargs={"pk": mundo.fA.pk}), {"nome": mundo.fA.nome, "descricao": "", "setor": "999999"})
    mundo.fA.refresh_from_db()
    assert mundo.fA.setor_id == mundo.A.pk


def test_set04_campo_setor_so_para_adm_na_ui(mundo):
    """SET-04: o campo `setor` do formulário de edição é visível só ao Adm (lista de fluxos traz o modal de edição)."""
    h_adm = _h(mundo.c["adm"].get(reverse("fluxos:lista")))
    h_g = _h(mundo.c["gA"].get(reverse("fluxos:lista")))
    assert 'name="setor"' in h_adm
    assert 'name="setor"' not in h_g


def test_set04_mudar_setor_do_usuario_nao_move_fluxos(mundo):
    """SET-04: mudar o setor do dono depois NÃO move os fluxos dele."""
    mundo.c["adm"].post(reverse("contas:usuario_editar", kwargs={"pk": mundo.gA.pk}),
                        {"nome": mundo.gA.nome, "email": mundo.gA.email, "papel": "coordenador", "ativo": "on", "setor": mundo.B.pk})
    mundo.fA.refresh_from_db()
    assert mundo.fA.setor_id == mundo.A.pk


# ---------- SET-05 ----------

def test_set05_execucao_herda_setor_do_fluxo(mundo, M):
    """SET-05: Execucao.setor = setor do fluxo no momento da execução."""
    antes = set(M.Execucao.objects.values_list("pk", flat=True))
    r = mundo.c["bA"].post(reverse("fluxos:executar", kwargs={"pk": mundo.fA.pk}))
    assert r.status_code == 302
    nova = M.Execucao.objects.exclude(pk__in=antes).get()
    assert nova.setor_id == mundo.A.pk


def test_set05_mover_fluxo_nao_move_execucoes_antigas(mundo):
    """SET-05: snapshot do setor; mover o fluxo depois não altera execuções antigas."""
    mundo.c["adm"].post(reverse("fluxos:editar", kwargs={"pk": mundo.fA.pk}),
                        {"nome": mundo.fA.nome, "descricao": "", "setor": mundo.B.pk})
    mundo.eA_bA.refresh_from_db()
    assert mundo.eA_bA.setor_id == mundo.A.pk
    # a execução antiga continua no escopo do gestor A, e não do gestor B
    assert mundo.c["gA"].get(reverse("execucoes:detalhe", kwargs={"pk": mundo.eA_bA.pk})).status_code == 200
    assert mundo.c["gB"].get(reverse("execucoes:detalhe", kwargs={"pk": mundo.eA_bA.pk})).status_code == 404


def test_set05_execucao_nova_apos_mover_usa_setor_novo(mundo, M):
    """SET-05: execução feita depois de mover usa o setor novo do fluxo."""
    mundo.c["adm"].post(reverse("fluxos:editar", kwargs={"pk": mundo.fA.pk}),
                        {"nome": mundo.fA.nome, "descricao": "", "setor": mundo.B.pk})
    antes = set(M.Execucao.objects.values_list("pk", flat=True))
    mundo.c["adm"].post(reverse("fluxos:executar", kwargs={"pk": mundo.fA.pk}))
    assert M.Execucao.objects.exclude(pk__in=antes).get().setor_id == mundo.B.pk


# ---------- SET-06 escopo em TODAS as rotas ----------

def test_set06_lista_fluxos_adm_ve_tudo(mundo):
    """SET-06: Adm vê fluxos de todos os setores."""
    h = _h(mundo.c["adm"].get(reverse("fluxos:lista")))
    for f in (mundo.fA, mundo.fAr, mundo.fB, mundo.fBr):
        assert f.nome in h


def test_set06_lista_fluxos_gestor_so_do_setor(mundo):
    """SET-06/PRM-04: Coordenador vê fluxos (ativos e rascunho) só do próprio setor."""
    h = _h(mundo.c["gA"].get(reverse("fluxos:lista")))
    assert mundo.fA.nome in h and mundo.fAr.nome in h
    assert mundo.fB.nome not in h and mundo.fBr.nome not in h


def test_set06_lista_fluxos_base_so_ativos_do_setor(mundo):
    """SET-06: Base vê só fluxos ATIVOS do setor dele."""
    h = _h(mundo.c["bA"].get(reverse("fluxos:lista")))
    assert mundo.fA.nome in h
    assert mundo.fAr.nome not in h and mundo.fB.nome not in h and mundo.fBr.nome not in h


@pytest.mark.parametrize("params", [{"q": "Beta"}, {"status": "rascunho"}, {"ordem": "nome"}, {"pagina": "2"}])
def test_set06_lista_fluxos_filtros_nao_vazam(mundo, params):
    """PRM-04: busca, filtro, ordem e paginação não revelam fluxos de outro setor."""
    for k in ("gA", "bA"):
        h = _h(mundo.c[k].get(reverse("fluxos:lista"), params))
        assert "Fluxo Beta" not in h


@pytest.mark.parametrize("rota", ["fluxos:editor"])
def test_set06_editor_outro_setor_404_gestor(mundo, rota):
    """SET-06/PRM-03: Coordenador abrindo editor de fluxo de outro setor → 404 (não 403)."""
    assert mundo.c["gA"].get(reverse(rota, kwargs={"pk": mundo.fB.pk})).status_code == 404
    assert mundo.c["gA"].get(reverse(rota, kwargs={"pk": mundo.fBr.pk})).status_code == 404


def test_set06_editor_proprio_setor_e_adm_ok(mundo):
    """SET-06: gestor abre editor do próprio setor; Adm abre qualquer um."""
    assert mundo.c["gA"].get(reverse("fluxos:editor", kwargs={"pk": mundo.fA.pk})).status_code == 200
    assert mundo.c["adm"].get(reverse("fluxos:editor", kwargs={"pk": mundo.fB.pk})).status_code == 200


def test_set06_editor_base_403_mesmo_setor(mundo):
    """PRM-02: Base sem permissão de editar recebe 403 no editor do próprio setor (ação negada, não objeto)."""
    assert mundo.c["bA"].get(reverse("fluxos:editor", kwargs={"pk": mundo.fA.pk})).status_code == 403


def test_set06_salvar_grafo_outro_setor_404_e_nao_altera(mundo, salvar_grafo):
    """SET-06/PRM-03: salvar grafo de fluxo de outro setor → 404 e grafo intacto."""
    antes = mundo.fB.grafo
    r = salvar_grafo(mundo.c["gA"], mundo.fB, {"versao": 1, "nos": [], "arestas": []})
    assert r.status_code == 404
    mundo.fB.refresh_from_db()
    assert mundo.fB.grafo == antes


def test_set06_salvar_grafo_proprio_setor_ok(mundo, salvar_grafo, grafo_valido):
    """SET-06: gestor salva no próprio setor."""
    assert salvar_grafo(mundo.c["gA"], mundo.fA, grafo_valido).status_code == 200


@pytest.mark.parametrize("quem", ["gA", "bA"])
@pytest.mark.parametrize("alvo", ["fB", "fBr"])
def test_set06_executar_outro_setor_404(mundo, M, quem, alvo):
    """SET-06/PRM-03: executar fluxo de outro setor → 404 e nenhuma execução criada (gestor e Base)."""
    antes = M.Execucao.objects.count()
    r = mundo.c[quem].post(reverse("fluxos:executar", kwargs={"pk": getattr(mundo, alvo).pk}))
    assert r.status_code == 404 and M.Execucao.objects.count() == antes


def test_set06_base_executa_ativo_do_setor(mundo, M):
    """SET-06: Base executa fluxo ATIVO do próprio setor."""
    antes = M.Execucao.objects.count()
    assert mundo.c["bA"].post(reverse("fluxos:executar", kwargs={"pk": mundo.fA.pk})).status_code == 302
    assert M.Execucao.objects.count() == antes + 1


def test_set06_base_rascunho_do_setor_404(mundo):
    """PRM-03: Base executando rascunho do próprio setor → 404."""
    assert mundo.c["bA"].post(reverse("fluxos:executar", kwargs={"pk": mundo.fAr.pk})).status_code == 404


@pytest.mark.parametrize("rota,dados", [
    ("fluxos:editar", {"nome": "Invadido", "descricao": ""}),
    ("fluxos:excluir", {}),
    ("fluxos:status", {"status": "rascunho"}),
])
def test_set06_mutacoes_outro_setor_404(mundo, M, rota, dados):
    """SET-06/PRM-03: editar, excluir, mudar status de fluxo de outro setor → 404 e nada muda."""
    r = mundo.c["gA"].post(reverse(rota, kwargs={"pk": mundo.fB.pk}), dados)
    assert r.status_code == 404
    mundo.fB.refresh_from_db()
    assert mundo.fB.nome == "Fluxo Beta Ativo" and mundo.fB.status == "ativo"
    assert M.Fluxo.objects.filter(pk=mundo.fB.pk).exists()


def test_set06_historico_adm_ve_tudo(mundo):
    """SET-06: Adm vê execuções de todos os setores."""
    h = _h(mundo.c["adm"].get(reverse("execucoes:lista")))
    for e in (mundo.eA_bA, mundo.eB_bB, mundo.eB_gB):
        assert reverse("execucoes:detalhe", kwargs={"pk": e.pk}) in h


def test_set06_historico_gestor_so_do_setor(mundo):
    """SET-06: Coordenador vê execuções de todos do setor dele, nenhuma de outro."""
    h = _h(mundo.c["gA"].get(reverse("execucoes:lista")))
    for e in (mundo.eA_bA, mundo.eA_bA2, mundo.eA_gA):
        assert reverse("execucoes:detalhe", kwargs={"pk": e.pk}) in h
    for e in (mundo.eB_bB, mundo.eB_gB):
        assert reverse("execucoes:detalhe", kwargs={"pk": e.pk}) not in h


def test_set06_historico_base_so_as_proprias(mundo):
    """SET-06: Base só as que ELE executou (nem as de colega do mesmo setor)."""
    h = _h(mundo.c["bA"].get(reverse("execucoes:lista")))
    assert reverse("execucoes:detalhe", kwargs={"pk": mundo.eA_bA.pk}) in h
    for e in (mundo.eA_bA2, mundo.eA_gA, mundo.eB_bB):
        assert reverse("execucoes:detalhe", kwargs={"pk": e.pk}) not in h


@pytest.mark.parametrize("quem,alvos", [
    ("gA", ["eB_bB", "eB_gB"]),
    ("gB", ["eA_bA", "eA_bA2", "eA_gA"]),
    ("bA", ["eA_bA2", "eA_gA", "eB_bB", "eB_gB"]),
    ("bB", ["eA_bA", "eB_gB"]),
])
def test_set06_detalhe_fora_do_escopo_404(mundo, quem, alvos):
    """SET-06/PRM-03: detalhe fora do escopo → 404 (gestor de outro setor; Base: alheias, mesmo do setor)."""
    for a in alvos:
        assert mundo.c[quem].get(reverse("execucoes:detalhe", kwargs={"pk": getattr(mundo, a).pk})).status_code == 404, (quem, a)


@pytest.mark.parametrize("quem,alvos", [
    ("adm", ["eA_bA", "eB_bB"]),
    ("gA", ["eA_bA", "eA_bA2", "eA_gA"]),
    ("bA", ["eA_bA"]),
])
def test_set06_detalhe_no_escopo_200(mundo, quem, alvos):
    """SET-06: detalhe dentro do escopo abre."""
    for a in alvos:
        assert mundo.c[quem].get(reverse("execucoes:detalhe", kwargs={"pk": getattr(mundo, a).pk})).status_code == 200, (quem, a)


@pytest.mark.parametrize("params", [{"q": "Beta"}, {"status": "erro"}, {"ordem": "-iniciada_em"}, {"pagina": "9"}])
def test_set06_historico_filtros_nao_vazam(mundo, mk_exec, params):
    """PRM-04: filtros do histórico não vazam execuções de outro setor."""
    mk_exec(mundo.fB, mundo.bB, status="erro")
    h = _h(mundo.c["gA"].get(reverse("execucoes:lista"), params))
    assert "Fluxo Beta" not in h


def test_set06_execucao_de_fluxo_excluido_mantem_setor(mundo, mk_exec):
    """SET-05/06: execução cujo fluxo foi excluído continua no escopo do setor (snapshot) e some para outro setor."""
    e = mk_exec(mundo.fA, mundo.bA)
    mundo.c["gA"].post(reverse("fluxos:excluir", kwargs={"pk": mundo.fA.pk}))
    assert mundo.c["gA"].get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).status_code == 200
    assert mundo.c["gB"].get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).status_code == 404


def test_set06_execucao_de_setor_a_nao_e_do_gestor_b_mesmo_com_dono_sem_setor(mundo, mk_fluxo, mk_exec):
    """SET-01/06: execução feita pelo Adm (sem setor) num fluxo do setor A: gestor A vê, gestor B não."""
    f = mk_fluxo(mundo.A, mundo.adm, "Fluxo do Adm No Setor A")
    e = mk_exec(f, mundo.adm)
    assert mundo.c["gA"].get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).status_code == 200
    assert mundo.c["gB"].get(reverse("execucoes:detalhe", kwargs={"pk": e.pk})).status_code == 404


def test_set06_escopo_e_do_setor_nao_do_dono(mundo):
    """SET-06: fluxo do setor A criado pelo Adm continua visível ao gestor A (escopo = setor, não dono)."""
    mundo.fA.dono = mundo.adm
    mundo.fA.save()
    assert mundo.fA.nome in _h(mundo.c["gA"].get(reverse("fluxos:lista")))


def test_set06_mudar_setor_do_gestor_muda_escopo_na_proxima_requisicao(mundo):
    """SET-06/USR-11: ao mudar o setor do gestor, o escopo muda imediatamente (sem cache)."""
    assert mundo.c["gA"].get(reverse("fluxos:editor", kwargs={"pk": mundo.fB.pk})).status_code == 404
    mundo.gA.setor = mundo.B
    mundo.gA.save()
    assert mundo.c["gA"].get(reverse("fluxos:editor", kwargs={"pk": mundo.fB.pk})).status_code == 200
    assert mundo.c["gA"].get(reverse("fluxos:editor", kwargs={"pk": mundo.fA.pk})).status_code == 404


def test_set06_queries_constantes_listas(mundo, mk_fluxo, mk_exec):
    """PRM-04/FLX-01/EXE-08: número de queries das listas não cresce com o volume (gestor A)."""
    def conta(rota):
        with CaptureQueriesContext(connection) as q:
            mundo.c["gA"].get(reverse(rota))
        return len(q)
    base_f, base_e = conta("fluxos:lista"), conta("execucoes:lista")
    for _ in range(15):
        f = mk_fluxo(mundo.A, mundo.gA)
        mk_exec(f, mundo.bA)
    assert conta("fluxos:lista") == base_f
    assert conta("execucoes:lista") == base_e
