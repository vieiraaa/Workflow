"""Simular usuário (D-047): só Adm, só leitura, encerra sozinha se o Adm perder o papel."""

import pytest
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.urls import reverse

from apps.contas import presenca
from apps.contas.models import Usuario
from apps.contas.simulacao import CHAVE_SESSAO, MENSAGEM_SO_LEITURA
from apps.execucoes.models import Execucao
from tests.conftest import criar_usuario

pytestmark = [pytest.mark.modulo("m1"), pytest.mark.django_db]

LISTA = reverse("contas:simular")
ENCERRAR = reverse("contas:simulacao_encerrar")


def _iniciar(pk):
    return reverse("contas:simular_iniciar", kwargs={"pk": pk})


@pytest.fixture
def simulando_base(cliente_adm, usuario_base):
    resposta = cliente_adm.post(_iniciar(usuario_base.pk))
    assert resposta.status_code == 302 and resposta.url == reverse("inicio")
    return cliente_adm


def test_tela_so_do_adm(cliente_adm, cliente_coordenador, cliente_base, cliente_anonimo):
    resposta = cliente_adm.get(LISTA)
    assert resposta.status_code == 200
    assert "contas/simular.html" in [t.name for t in resposta.templates]
    assert cliente_coordenador.get(LISTA).status_code == 403
    assert cliente_base.get(LISTA).status_code == 403
    assert cliente_anonimo.get(LISTA).status_code == 302


@pytest.mark.parametrize("cliente", ["cliente_coordenador", "cliente_base"])
def test_quem_nao_e_adm_nao_inicia(request, cliente, usuario_adm):
    c = request.getfixturevalue(cliente)
    assert c.post(_iniciar(usuario_adm.pk)).status_code == 403
    assert CHAVE_SESSAO not in c.session


def test_anonimo_nao_inicia(cliente_anonimo, usuario_base):
    assert cliente_anonimo.post(_iniciar(usuario_base.pk)).status_code == 302
    assert CHAVE_SESSAO not in cliente_anonimo.session


def test_linhas_trazem_url_de_simular_menos_para_si_e_inativos(cliente_adm, usuario_adm):
    base = criar_usuario("b2@exemplo.test", "Bruno Base", "Base")
    inativo = criar_usuario("i@exemplo.test", "Ivo Inativo", "Base", is_active=False)
    linhas = {u["pk"]: u for u in cliente_adm.get(LISTA).context["usuarios"]}
    assert linhas[base.pk]["url_simular"] == _iniciar(base.pk)
    assert linhas[usuario_adm.pk]["url_simular"] == ""
    assert linhas[inativo.pk]["url_simular"] == ""


def test_nao_simula_a_si_mesmo_nem_inativo(cliente_adm, usuario_adm):
    inativo = criar_usuario("i@exemplo.test", "Ivo Inativo", "Base", is_active=False)
    for pk in (usuario_adm.pk, inativo.pk):
        assert cliente_adm.post(_iniciar(pk)).url == LISTA
        assert CHAVE_SESSAO not in cliente_adm.session
    assert cliente_adm.post(_iniciar(999999)).status_code == 404


def test_iniciar_so_por_post(cliente_adm, usuario_base):
    assert cliente_adm.get(_iniciar(usuario_base.pk)).status_code == 405


def test_ve_o_menu_os_dados_e_as_permissoes_do_simulado(simulando_base, usuario_adm, usuario_base):
    Execucao.objects.create(fluxo_nome="Da Bia", executado_por=usuario_base)
    Execucao.objects.create(fluxo_nome="Da Ana", executado_por=usuario_adm)
    resposta = simulando_base.get(reverse("execucoes:lista"))
    assert resposta.status_code == 200
    assert [e.fluxo_nome for e in resposta.context["page_obj"]] == ["Da Bia"]
    assert resposta.context["simulacao"]["nome"] == "Bia Base"
    assert resposta.context["usuario_nome"] == "Bia Base"
    assert "usuarios" not in {i["chave"] for i in resposta.context["menu"]}
    corpo = resposta.content.decode()
    assert "Simulando <strong>Bia Base</strong>" in corpo and ENCERRAR in corpo
    # telas de Adm ficam fechadas enquanto simula um Base
    assert simulando_base.get(reverse("contas:usuarios")).status_code == 403


def test_simulacao_e_so_leitura(simulando_base):
    total = Usuario.objects.count()
    dados = {"nome": "Novo", "email": "novo@exemplo.test", "papel": "base"}
    resposta = simulando_base.post(reverse("contas:usuario_novo"), dados, HTTP_REFERER="/fluxos/")
    assert resposta.status_code == 302 and resposta.url == "/fluxos/"
    assert Usuario.objects.count() == total
    mensagens = [str(m) for m in resposta.wsgi_request._messages]
    assert MENSAGEM_SO_LEITURA in mensagens


def test_mutacao_por_fetch_recebe_json_403(simulando_base):
    resposta = simulando_base.post(
        reverse("contas:usuario_novo"), "{}", content_type="application/json"
    )
    assert resposta.status_code == 403
    assert resposta.json()["ok"] is False


def test_referer_de_outro_site_volta_para_a_home(simulando_base):
    resposta = simulando_base.post(
        reverse("contas:usuario_novo"), {}, HTTP_REFERER="https://outro.exemplo.test/"
    )
    assert resposta.url == reverse("inicio")


def test_encerrar_volta_a_ser_o_adm(simulando_base):
    resposta = simulando_base.post(ENCERRAR)
    assert resposta.status_code == 302 and resposta.url == LISTA
    assert CHAVE_SESSAO not in simulando_base.session
    resposta = simulando_base.get(reverse("contas:usuarios"))
    assert resposta.status_code == 200 and resposta.context["simulacao"] is None


def test_sair_durante_a_simulacao_encerra_a_sessao(simulando_base):
    simulando_base.post(reverse("logout"))
    assert CHAVE_SESSAO not in simulando_base.session
    assert simulando_base.get(LISTA).status_code == 302


def test_adm_que_perde_o_papel_perde_a_simulacao(simulando_base, usuario_adm):
    usuario_adm.groups.set([Group.objects.get(name="Base")])
    resposta = simulando_base.get(reverse("inicio"))
    assert resposta.context["simulacao"] is None
    assert resposta.context["usuario_nome"] == "Ana Admin"
    assert CHAVE_SESSAO not in simulando_base.session


def test_alvo_desativado_encerra_a_simulacao(simulando_base, usuario_base):
    Usuario.objects.filter(pk=usuario_base.pk).update(is_active=False)
    resposta = simulando_base.get(reverse("inicio"))
    assert resposta.context["simulacao"] is None
    assert CHAVE_SESSAO not in simulando_base.session


def test_presenca_fica_com_o_adm(simulando_base, usuario_adm, usuario_base):
    cache.clear()
    simulando_base.get(reverse("inicio"))
    assert presenca.online(usuario_adm)
    assert not presenca.online(usuario_base)


def test_item_do_menu_marca_ativo_so_na_tela_de_simular(cliente_adm):
    ativos = {i["chave"] for i in cliente_adm.get(LISTA).context["menu"] if i["ativo"]}
    assert ativos == {"simular"}
    ativos = {
        i["chave"]
        for i in cliente_adm.get(reverse("contas:usuarios")).context["menu"]
        if i["ativo"]
    }
    assert ativos == {"usuarios"}
