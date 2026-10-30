"""Usuários e setores ativos: fora da Home, no subtítulo das telas do Adm (D-043)."""

import pytest
from django.urls import reverse

from apps.contas.models import Setor
from apps.execucoes import painel
from tests.conftest import criar_usuario

pytestmark = [pytest.mark.modulo("m4"), pytest.mark.django_db]


@pytest.mark.parametrize("papel", ["usuario_adm", "usuario_coordenador", "usuario_base"])
def test_home_sem_cartoes_de_usuarios_e_setores(request, papel):
    chaves = {
        i["chave"]
        for i in painel.montar_painel(request.getfixturevalue(papel), "7d")["indicadores"]
    }
    assert not chaves & {"usuarios_ativos", "setores_ativos"}


def test_subtitulo_de_usuarios_conta_so_ativos(cliente_adm, usuario_base):
    criar_usuario("inativo@exemplo.test", "Inativo", "Base", is_active=False)
    r = cliente_adm.get(reverse("contas:usuarios"))
    assert r.context["total_ativos"] == 2  # adm + base
    assert '<p class="topbar__sub">2 ativos</p>' in r.content.decode()


def test_subtitulo_de_setores_mostra_ativos_de_total(cliente_adm, setor_geral):
    Setor.objects.create(nome="Arquivo morto", ativo=False)
    r = cliente_adm.get(reverse("contas:setores"))
    ativos, total = Setor.objects.filter(ativo=True).count(), Setor.objects.count()
    assert r.context["total_ativos"] == ativos
    assert (
        f'<p class="topbar__sub">{ativos} ativo{"s" if ativos != 1 else ""} de {total}</p>'
        in r.content.decode()
    )
