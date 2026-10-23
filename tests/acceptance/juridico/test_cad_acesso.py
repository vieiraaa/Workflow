"""Aceite M8 · acesso e permissões (CAD-01, CAD-02, permissoes.yaml cadastro.*). Só pela spec."""
import pytest
from django.urls import reverse

from .conftest import cnj, criar_processo, pdf_processo

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

ROTAS_SEM_PK = ["juridico:painel", "juridico:enviar_pdfs", "juridico:enviar_cnj", "juridico:envios", "juridico:erros",
                "juridico:audiencias", "juridico:processo_novo", "juridico:status"]
ROTAS_ADM = ["juridico:config", "juridico:excluidos"]


def _url(nome, pk=None):
    return reverse(nome, kwargs={"pk": pk}) if pk is not None else reverse(nome)


@pytest.mark.parametrize("rota", ROTAS_SEM_PK)
def test_com_acesso_entram_adm_coordenador_e_base(cad, rota):
    """CAD-01/02: Adm, Coordenador e Base do setor com acesso abrem todas as telas do Jurídico (200)."""
    for c in (cad.adm, cad.bruno, cad.ana):
        assert c.get(_url(rota)).status_code == 200, rota


@pytest.mark.parametrize("rota", ROTAS_SEM_PK + ROTAS_ADM)
def test_setor_fora_da_lista_recebe_403(cad, rota):
    """CAD-02: setor fora da lista → 403 em todas as rotas do Jurídico."""
    assert cad.carla.get(_url(rota)).status_code == 403, rota


@pytest.mark.parametrize("rota", ROTAS_SEM_PK + ROTAS_ADM)
def test_anonimo_vai_para_o_login(cad, rota):
    """CAD-02: anônimo → redireciona para o login (nunca vê dados)."""
    r = cad.anonimo.get(_url(rota))
    assert r.status_code == 302 and reverse("login") in r["Location"]


@pytest.mark.parametrize("rota", ROTAS_ADM)
def test_config_e_excluidos_so_para_adm(cad, rota):
    """cadastro.configurar: só Adm; Coordenador e Base com acesso → 403."""
    assert cad.adm.get(_url(rota)).status_code == 200
    assert cad.bruno.get(_url(rota)).status_code == 403
    assert cad.ana.get(_url(rota)).status_code == 403


def test_sem_setor_e_nao_adm_recebe_403(cad, fabrica_usuario):
    """CAD-02: usuário sem setor (e não Adm) → 403."""
    from django.test import Client
    u = fabrica_usuario(papel="Coordenador")
    u.setor = None
    u.save()
    c = Client()
    c.force_login(u)
    assert c.get(reverse("juridico:painel")).status_code == 403


def test_lista_vazia_de_setores_so_o_adm_usa(cad):
    """CAD-02: ConfigCadastro.setores_com_acesso vazio → só o Adm usa."""
    cad.config.setores_com_acesso.set([])
    assert cad.adm.get(reverse("juridico:painel")).status_code == 200
    assert cad.bruno.get(reverse("juridico:painel")).status_code == 403
    assert cad.ana.get(reverse("juridico:painel")).status_code == 403


def test_acesso_acompanha_a_config_em_tempo_real(cad):
    """CAD-02: incluir o setor B na lista libera a Carla; tirar o setor A bloqueia a Ana."""
    cad.config.setores_com_acesso.set([cad.setor_a, cad.setor_b])
    assert cad.carla.get(reverse("juridico:painel")).status_code == 200
    cad.config.setores_com_acesso.set([cad.setor_b])
    assert cad.ana.get(reverse("juridico:painel")).status_code == 403


def test_menu_tem_grupo_juridico_para_quem_tem_acesso(cad, ver):
    """CAD-01: grupo 'Jurídico' com 'Cadastro de processos' no menu para quem tem cadastro.ver; ausente sem acesso."""
    for c in (cad.adm, cad.bruno, cad.ana):
        t = ver.texto(c.get(reverse("inicio")))
        assert "Jurídico" in t and "Cadastro de processos" in t
    t = ver.texto(cad.carla.get(reverse("inicio")))
    assert "Cadastro de processos" not in t and "Jurídico" not in t
    assert reverse("juridico:painel") in ver.html(cad.ana.get(reverse("inicio")))
    assert reverse("juridico:painel") not in ver.html(cad.carla.get(reverse("inicio")))


def test_painel_mostra_todos_os_processos_do_escritorio(cad, ver):
    """permissoes.yaml escopo_setor_com_acesso: com acesso, vê TODOS os processos (de qualquer autor)."""
    p1 = criar_processo(cad, usuario=cad.adm_u, adverso_nome="Adverso Do Adm")
    p2 = criar_processo(cad, usuario=cad.bruno_u, adverso_nome="Adverso Do Bruno")
    for c in (cad.adm, cad.bruno, cad.ana):
        t = ver.texto(c.get(reverse("juridico:painel")))
        assert "Adverso Do Adm" in t or p1.numero in t
        assert "Adverso Do Bruno" in t or p2.numero in t


def test_processo_detalhe_403_sem_acesso_e_200_com_acesso(cad):
    """CAD-02: detalhe do processo respeita o acesso."""
    p = criar_processo(cad)
    assert cad.ana.get(_url("juridico:processo", p.pk)).status_code == 200
    assert cad.carla.get(_url("juridico:processo", p.pk)).status_code == 403
    r = cad.anonimo.get(_url("juridico:processo", p.pk))
    assert r.status_code == 302 and reverse("login") in r["Location"]


@pytest.mark.parametrize("acao", ["marcar_cadastrado", "consultar_cnj", "excluir"])
def test_acoes_de_edicao_exigem_acesso(cad, acao):
    """cadastro.editar: sem acesso → 403 e nada muda; anônimo → login."""
    p = criar_processo(cad)
    assert cad.carla.post(_url(f"juridico:{acao}", p.pk)).status_code == 403
    r = cad.anonimo.post(_url(f"juridico:{acao}", p.pk))
    assert r.status_code == 302 and reverse("login") in r["Location"]
    p.refresh_from_db()
    assert p.excluido_em is None and p.status == "CONFERIR"


@pytest.mark.parametrize("acao", ["desfazer_cadastrado", "restaurar"])
def test_desfazer_e_restaurar_so_adm(cad, acao):
    """CAD-15/21: 'Desfazer cadastrado' e restaurar excluído são do Adm; Coordenador e Base → 403."""
    p = criar_processo(cad, status="CADASTRADO")
    assert cad.bruno.post(_url(f"juridico:{acao}", p.pk)).status_code == 403
    assert cad.ana.post(_url(f"juridico:{acao}", p.pk)).status_code == 403
    p.refresh_from_db()
    assert p.status == "CADASTRADO"


def test_testar_conexao_so_adm(cad):
    """CAD-14: 'Testar conexão' só Adm."""
    assert cad.ana.post(reverse("juridico:testar_conexao")).status_code == 403
    assert cad.bruno.post(reverse("juridico:testar_conexao")).status_code == 403
    assert cad.adm.post(reverse("juridico:testar_conexao")).status_code in (200, 302)


def test_config_post_so_adm(cad):
    """CAD-14/permissoes: salvar configuração só Adm (Coordenador e Base 403, nada muda)."""
    url_antes = cad.config.dify_url
    for c in (cad.bruno, cad.ana):
        r = c.post(reverse("juridico:config"), {"dify_url": "http://127.0.0.1:1/x", "dify_usuario": "x", "datajud_url": "http://127.0.0.1:1/y"})
        assert r.status_code == 403
    cad.config.refresh_from_db()
    assert cad.config.dify_url == url_antes


def test_mutacao_so_por_post(cad):
    """CLAUDE.md/CAD-15: ações de mutação respondem 405 a GET."""
    p = criar_processo(cad)
    for acao in ("marcar_cadastrado", "consultar_cnj", "excluir"):
        assert cad.adm.get(_url(f"juridico:{acao}", p.pk)).status_code == 405
    assert cad.adm.get(reverse("juridico:testar_conexao")).status_code == 405


def test_post_sem_csrf_e_recusado(cad):
    """SEG-12: POST sem token CSRF → 403 (cliente com enforce_csrf_checks)."""
    from django.test import Client
    c = Client(enforce_csrf_checks=True)
    c.force_login(cad.ana_u)
    p = criar_processo(cad)
    assert c.post(_url("juridico:excluir", p.pk)).status_code == 403
    p.refresh_from_db()
    assert p.excluido_em is None


def test_detalhe_do_envio_so_para_quem_enviou_e_adm(cad, enviar):
    """permissoes.yaml: o detalhe de um Envio só para quem enviou e o Adm (outro usuário COM acesso não vê)."""
    enviar(cad.ana, pdf_processo(cnj(1)[0]))
    envio = cad.Envio.objects.get()
    assert cad.ana.get(_url("juridico:envio", envio.pk)).status_code == 200
    assert cad.adm.get(_url("juridico:envio", envio.pk)).status_code == 200
    assert cad.bruno.get(_url("juridico:envio", envio.pk)).status_code in (403, 404)
    assert cad.carla.get(_url("juridico:envio", envio.pk)).status_code in (403, 404)


def test_status_json_do_envio_so_para_quem_enviou_e_adm(cad, enviar):
    """CAD-23 (8b): ?envio=<pk> só quem enviou ou Adm."""
    enviar(cad.ana, pdf_processo(cnj(1)[0]))
    envio = cad.Envio.objects.get()
    url = reverse("juridico:status") + f"?envio={envio.pk}"
    assert cad.ana.get(url).status_code == 200 and cad.adm.get(url).status_code == 200
    assert cad.bruno.get(url).status_code in (403, 404)
