"""Aceite M2: criar/editar/excluir/ativar fluxo. Fontes: FLX-02, FLX-03, FLX-04, FLX-06, EST-01, PRM-01/02/08."""
import json

import pytest
from django.apps import apps
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _h(r):
    return r.content.decode()


def _Fluxo():
    return apps.get_model("fluxos", "Fluxo")


def _gatilhos(f):
    return [n for n in f.grafo["nos"] if n["tipo"] == "gatilho"]


# ---------- FLX-02 criar ----------

@pytest.mark.modulo("m2")
@pytest.mark.parametrize("cliente,quem", [("cliente_adm", "usuario_adm"), ("cliente_coordenador", "usuario_coordenador")])
def test_criar_fluxo_sucesso(request, cliente, quem):
    """FLX-02/FLX-06: nasce rascunho, dono = logado, grafo só com gatilho; redirect editor + toast."""
    c = request.getfixturevalue(cliente)
    dono = request.getfixturevalue(quem)
    r = c.post(reverse("fluxos:novo"), {"nome": "Meu Fluxo", "descricao": "Para testar"}, follow=True)
    f = _Fluxo().objects.get(nome="Meu Fluxo")
    assert r.redirect_chain[-1][0] == reverse("fluxos:editor", kwargs={"pk": f.pk})
    assert "Fluxo Meu Fluxo criado." in _h(r)
    assert f.status == "rascunho" and f.dono_id == dono.pk and f.descricao == "Para testar"
    assert f.grafo["versao"] == 1 and f.grafo["arestas"] == []
    assert [n["tipo"] for n in f.grafo["nos"]] == ["gatilho"]


@pytest.mark.modulo("m2")
def test_criar_base_403_e_anonimo_login(cliente_base, cliente_anonimo):
    """PRM-01/02: Base 403; anônimo → login; nada criado."""
    d = {"nome": "Invasor", "descricao": ""}
    assert cliente_base.post(reverse("fluxos:novo"), d).status_code == 403
    r = cliente_anonimo.post(reverse("fluxos:novo"), d)
    assert r.status_code == 302 and r.url.startswith(reverse("login"))
    assert not _Fluxo().objects.filter(nome="Invasor").exists()


@pytest.mark.modulo("m2")
def test_criar_get_nao_cria(cliente_adm):
    """PRM-08: GET em rota de mutação → 405 e nada criado."""
    n = _Fluxo().objects.count()
    assert cliente_adm.get(reverse("fluxos:novo")).status_code == 405
    assert _Fluxo().objects.count() == n


@pytest.mark.modulo("m2")
def test_criar_nome_vazio(cliente_adm):
    """FLX-06: nome vazio → 200 (lista com modal) e 'Este campo é obrigatório.'"""
    n = _Fluxo().objects.count()
    r = cliente_adm.post(reverse("fluxos:novo"), {"nome": "", "descricao": "x"})
    assert r.status_code == 200
    assert "Este campo é obrigatório." in _h(r)
    assert _Fluxo().objects.count() == n


@pytest.mark.modulo("m2")
def test_criar_nome_121_recusado_e_120_aceito(cliente_adm):
    """FLX-06/modelo: nome até 120; 121 → 'Use no máximo 120 caracteres.'"""
    r = cliente_adm.post(reverse("fluxos:novo"), {"nome": "n" * 121, "descricao": ""})
    assert r.status_code == 200 and "Use no máximo 120 caracteres." in _h(r)
    assert not _Fluxo().objects.filter(nome="n" * 121).exists()
    cliente_adm.post(reverse("fluxos:novo"), {"nome": "m" * 120, "descricao": ""})
    assert _Fluxo().objects.filter(nome="m" * 120).exists()


@pytest.mark.modulo("m2")
def test_criar_descricao_acima_de_1000_recusada(cliente_adm):
    """Modelo: descricao max 1000; 1001 recusada sem 500 e nada criado."""
    r = cliente_adm.post(reverse("fluxos:novo"), {"nome": "Desc Longa", "descricao": "d" * 1001})
    assert r.status_code == 200
    assert not _Fluxo().objects.filter(nome="Desc Longa").exists()
    cliente_adm.post(reverse("fluxos:novo"), {"nome": "Desc Limite", "descricao": "d" * 1000})
    assert _Fluxo().objects.filter(nome="Desc Limite").exists()


@pytest.mark.modulo("m2")
def test_criar_descricao_opcional(cliente_adm):
    """Modelo: descricao não é obrigatória."""
    cliente_adm.post(reverse("fluxos:novo"), {"nome": "Sem Descricao"})
    assert _Fluxo().objects.filter(nome="Sem Descricao").exists()


@pytest.mark.modulo("m2")
def test_criar_xss_no_toast(cliente_adm):
    """SEG-13: nome malicioso escapado no toast e no editor."""
    p = "<script>alert(1)</script>"
    r = cliente_adm.post(reverse("fluxos:novo"), {"nome": p, "descricao": p}, follow=True)
    assert p not in _h(r)


@pytest.mark.modulo("m2")
def test_criar_sem_csrf(usuario_adm):
    """PRM-08/SEG-12: POST sem CSRF → 403."""
    from django.test import Client
    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_adm)
    assert c.post(reverse("fluxos:novo"), {"nome": "SemToken"}).status_code == 403
    assert not _Fluxo().objects.filter(nome="SemToken").exists()


# ---------- FLX-03 editar ----------

@pytest.mark.modulo("m2")
def test_editar_nome_e_descricao(cliente_coordenador, fabrica_fluxo):
    """FLX-03/FLX-06: sucesso → redirect editor + toast 'Fluxo atualizado.'"""
    f = fabrica_fluxo(nome="Antigo")
    r = cliente_coordenador.post(reverse("fluxos:editar", kwargs={"pk": f.pk}),
                                 {"nome": "Novo Nome", "descricao": "Nova"}, follow=True)
    assert r.redirect_chain[-1][0] == reverse("fluxos:editor", kwargs={"pk": f.pk})
    assert "Fluxo atualizado." in _h(r)
    f.refresh_from_db()
    assert (f.nome, f.descricao) == ("Novo Nome", "Nova")


@pytest.mark.modulo("m2")
def test_editar_nao_altera_dono_status_nem_grafo(cliente_coordenador, fabrica_fluxo, usuario_adm, usuario_coordenador):
    """Modelo: dono não editável; editar não muda status nem grafo, mesmo com campos extras."""
    f = fabrica_fluxo(nome="Intacto")
    grafo = json.loads(json.dumps(f.grafo))
    cliente_coordenador.post(reverse("fluxos:editar", kwargs={"pk": f.pk}),
                             {"nome": "Intacto", "descricao": "", "dono": usuario_coordenador.pk,
                              "status": "ativo", "grafo": "{}"})
    f.refresh_from_db()
    assert f.dono_id == usuario_adm.pk and f.status == "rascunho" and f.grafo == grafo


@pytest.mark.modulo("m2")
def test_editar_validacao_e_pk_inexistente(cliente_adm, fabrica_fluxo):
    """FLX-06: nome vazio → 'Este campo é obrigatório.'; pk inexistente → 404."""
    f = fabrica_fluxo(nome="Valido")
    r = cliente_adm.post(reverse("fluxos:editar", kwargs={"pk": f.pk}), {"nome": "", "descricao": ""})
    assert r.status_code == 200 and "Este campo é obrigatório." in _h(r)
    f.refresh_from_db()
    assert f.nome == "Valido"
    assert cliente_adm.post(reverse("fluxos:editar", kwargs={"pk": 999999}), {"nome": "x"}).status_code == 404


@pytest.mark.modulo("m2")
def test_editar_base_403_anonimo_login(cliente_base, cliente_anonimo, fabrica_fluxo):
    """PRM-01/02: Base 403 (mesmo em fluxo ativo); anônimo → login; nada muda."""
    f = fabrica_fluxo(nome="Protegido", status="ativo")
    url = reverse("fluxos:editar", kwargs={"pk": f.pk})
    assert cliente_base.post(url, {"nome": "Hack"}).status_code == 403
    r = cliente_anonimo.post(url, {"nome": "Hack"})
    assert r.status_code == 302 and r.url.startswith(reverse("login"))
    f.refresh_from_db()
    assert f.nome == "Protegido"


@pytest.mark.modulo("m2")
def test_editar_get_405(cliente_adm, fabrica_fluxo):
    """PRM-08: GET em fluxos:editar → 405."""
    f = fabrica_fluxo()
    assert cliente_adm.get(reverse("fluxos:editar", kwargs={"pk": f.pk})).status_code == 405


# ---------- FLX-03 excluir ----------

@pytest.mark.modulo("m2")
@pytest.mark.parametrize("cliente", ["cliente_adm", "cliente_coordenador"])
def test_excluir_fluxo(request, cliente, fabrica_fluxo):
    """FLX-03/FLX-06: POST → redirect lista + toast 'Fluxo <nome> excluído.'"""
    f = fabrica_fluxo(nome="Para Excluir", status="ativo")
    r = request.getfixturevalue(cliente).post(reverse("fluxos:excluir", kwargs={"pk": f.pk}), follow=True)
    assert r.redirect_chain[-1][0] == reverse("fluxos:lista")
    assert "Fluxo Para Excluir excluído." in _h(r)
    assert not _Fluxo().objects.filter(pk=f.pk).exists()


@pytest.mark.modulo("m2")
def test_excluir_get_405_e_nao_apaga(cliente_adm, fabrica_fluxo):
    """FLX-03/PRM-08: excluir só por POST."""
    f = fabrica_fluxo()
    assert cliente_adm.get(reverse("fluxos:excluir", kwargs={"pk": f.pk})).status_code == 405
    assert _Fluxo().objects.filter(pk=f.pk).exists()


@pytest.mark.modulo("m2")
def test_excluir_base_403_anonimo_login_e_inexistente_404(cliente_base, cliente_anonimo, cliente_adm, fabrica_fluxo):
    """PRM-01/02/03: Base 403, anônimo login, pk inexistente 404; nada apagado."""
    f = fabrica_fluxo(status="ativo")
    url = reverse("fluxos:excluir", kwargs={"pk": f.pk})
    assert cliente_base.post(url).status_code == 403
    r = cliente_anonimo.post(url)
    assert r.status_code == 302 and r.url.startswith(reverse("login"))
    assert _Fluxo().objects.filter(pk=f.pk).exists()
    assert cliente_adm.post(reverse("fluxos:excluir", kwargs={"pk": 999999})).status_code == 404


@pytest.mark.modulo("m2")
def test_excluir_sem_csrf(usuario_adm, fabrica_fluxo):
    """PRM-08: excluir exige CSRF."""
    from django.test import Client
    f = fabrica_fluxo()
    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_adm)
    assert c.post(reverse("fluxos:excluir", kwargs={"pk": f.pk})).status_code == 403
    assert _Fluxo().objects.filter(pk=f.pk).exists()


# ---------- FLX-04 / EST-01: status ----------

@pytest.mark.modulo("m2")
@pytest.mark.parametrize("cliente", ["cliente_adm", "cliente_coordenador"])
def test_ativar_grafo_sem_pendencias(request, cliente, fabrica_fluxo):
    """FLX-04: grafo válido → ativa."""
    f = fabrica_fluxo(status="rascunho")
    r = request.getfixturevalue(cliente).post(reverse("fluxos:status", kwargs={"pk": f.pk}), {"status": "ativo"})
    assert r.status_code in (200, 302)
    f.refresh_from_db()
    assert f.status == "ativo"


@pytest.mark.modulo("m2")
def test_ativar_com_pendencias_json_400(cliente_adm, fabrica_fluxo):
    """FLX-04/FLX-06: com pendências → 400 JSON {ok:false, pendencias:[...]} e segue rascunho."""
    f = fabrica_fluxo(grafo={"versao": 1, "nos": [
        {"id": "n1", "tipo": "gatilho", "titulo": "Início", "posicao": {"x": 0, "y": 0}, "config": {}}],
        "arestas": []})
    r = cliente_adm.post(reverse("fluxos:status", kwargs={"pk": f.pk}), {"status": "ativo"},
                         HTTP_ACCEPT="application/json")
    assert r.status_code == 400
    corpo = r.json()
    assert corpo["ok"] is False and len(corpo["pendencias"]) >= 1
    f.refresh_from_db()
    assert f.status == "rascunho"


@pytest.mark.modulo("m2")
def test_ativar_com_pendencias_html_redireciona_ao_editor(cliente_adm, fabrica_fluxo):
    """FLX-06: sem Accept JSON → redirect para o editor com erro; continua rascunho."""
    f = fabrica_fluxo(grafo={"versao": 1, "nos": [], "arestas": []})
    r = cliente_adm.post(reverse("fluxos:status", kwargs={"pk": f.pk}), {"status": "ativo"})
    assert r.status_code == 302 and r.url == reverse("fluxos:editor", kwargs={"pk": f.pk})
    f.refresh_from_db()
    assert f.status == "rascunho"


@pytest.mark.modulo("m2")
def test_voltar_para_rascunho_sempre_permitido(cliente_adm, fabrica_fluxo):
    """FLX-04/estados: ativo → rascunho sempre, mesmo com grafo inválido."""
    f = fabrica_fluxo(status="ativo", grafo={"versao": 1, "nos": [], "arestas": []})
    r = cliente_adm.post(reverse("fluxos:status", kwargs={"pk": f.pk}), {"status": "rascunho"})
    assert r.status_code in (200, 302)
    f.refresh_from_db()
    assert f.status == "rascunho"


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("valor", ["arquivado", "", "ATIVO", "1"])
def test_status_invalido_nao_altera(cliente_adm, fabrica_fluxo, valor):
    """FLX-06: status fora de rascunho|ativo é recusado (nunca 500) e não altera."""
    f = fabrica_fluxo(status="rascunho")
    r = cliente_adm.post(reverse("fluxos:status", kwargs={"pk": f.pk}), {"status": valor})
    assert r.status_code < 500
    f.refresh_from_db()
    assert f.status == "rascunho"


@pytest.mark.modulo("m2")
def test_status_permissoes_e_metodo(cliente_base, cliente_anonimo, cliente_adm, fabrica_fluxo):
    """PRM-01/02/08: Base 403, anônimo login, GET 405, pk inexistente 404."""
    f = fabrica_fluxo(status="rascunho")
    url = reverse("fluxos:status", kwargs={"pk": f.pk})
    assert cliente_base.post(url, {"status": "ativo"}).status_code == 403
    r = cliente_anonimo.post(url, {"status": "ativo"})
    assert r.status_code == 302 and r.url.startswith(reverse("login"))
    assert cliente_adm.get(url).status_code == 405
    assert cliente_adm.post(reverse("fluxos:status", kwargs={"pk": 999999}), {"status": "ativo"}).status_code == 404
    f.refresh_from_db()
    assert f.status == "rascunho"


@pytest.mark.modulo("m2")
def test_status_sem_csrf(usuario_adm, fabrica_fluxo):
    """PRM-08: mudança de status exige CSRF."""
    from django.test import Client
    f = fabrica_fluxo()
    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_adm)
    assert c.post(reverse("fluxos:status", kwargs={"pk": f.pk}), {"status": "ativo"}).status_code == 403
    f.refresh_from_db()
    assert f.status == "rascunho"


@pytest.mark.modulo("m2")
def test_est01_salvar_grafo_com_pendencia_derruba_ativo_para_rascunho(cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """EST-01: fluxo ativo salvo com pendências volta para rascunho."""
    f = fabrica_fluxo(status="ativo")
    grafo_valido["nos"] = [n for n in grafo_valido["nos"] if n["tipo"] != "saida"]
    grafo_valido["arestas"] = [{"de": "n1", "para": "n2"}]
    r = salvar_grafo(cliente_coordenador, f, grafo_valido)
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["pendencias"]
    f.refresh_from_db()
    assert f.status == "rascunho"


@pytest.mark.modulo("m2")
def test_est01_salvar_grafo_valido_mantem_ativo(cliente_coordenador, fabrica_fluxo, grafo_valido, salvar_grafo):
    """EST-01: editar o grafo de fluxo ativo sem gerar pendências mantém ativo."""
    f = fabrica_fluxo(status="ativo")
    grafo_valido["nos"][1]["titulo"] = "Título novo"
    r = salvar_grafo(cliente_coordenador, f, grafo_valido)
    assert r.status_code == 200 and r.json()["pendencias"] == []
    f.refresh_from_db()
    assert f.status == "ativo" and f.grafo["nos"][1]["titulo"] == "Título novo"
