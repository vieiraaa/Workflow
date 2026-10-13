"""Render das telas das Funções (M7a, TEL-23..26)."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.execucoes.models import Execucao, ExecucaoNo
from apps.fluxos.models import Fluxo, grafo_inicial
from apps.funcoes.models import Funcao

pytestmark = pytest.mark.modulo("m7a")


def nomes(resposta):
    return [t.name for t in resposta.templates]


@pytest.fixture
def funcao(usuario_adm):
    fluxo = Fluxo.objects.create(nome="Base", dono=usuario_adm, grafo=grafo_inicial())
    return Funcao.objects.create(
        nome="Relatório <i>x</i>", fluxo=fluxo, versao=1, criada_por=usuario_adm, icone="bar-chart-3",
        entradas=[{"nome": "dia", "rotulo": "Dia", "tipo": "data", "obrigatoria": True, "padrao": None, "opcoes": []}],
    )


def test_catalogo_vazio_por_papel(cliente_adm, cliente_base):
    r = cliente_adm.get(reverse("funcoes:catalogo"))
    assert "funcoes/catalogo.html" in nomes(r) and b"Nenhuma fun\xc3\xa7\xc3\xa3o ainda" in r.content
    assert reverse("funcoes:nova").encode() in r.content
    r = cliente_base.get(reverse("funcoes:catalogo"))
    assert b"liberada para voc" in r.content and reverse("funcoes:nova").encode() not in r.content


def test_catalogo_cartao_escapa_e_so_adm_tem_menu(cliente_adm, cliente_base, funcao):
    r = cliente_adm.get(reverse("funcoes:catalogo"))
    assert "componentes/cartao_funcao.html" in nomes(r)
    assert b"<i>x</i>" not in r.content and b"&lt;i&gt;x" in r.content
    assert b"chart-bar" in r.content and b"Publicar nova vers" in r.content
    assert b"Publicar nova vers" not in cliente_base.get(reverse("funcoes:catalogo")).content


def test_form_nova_e_editar(cliente_adm, funcao):
    r = cliente_adm.get(reverse("funcoes:nova"))
    assert "funcoes/form.html" in nomes(r)
    for marca in (b"data-entradas-json", b'name="liberar_para"', b'name="setores"', b'name="papeis"', b'name="icone"'):
        assert marca in r.content
    r = cliente_adm.get(reverse("funcoes:editar", kwargs={"pk": funcao.pk}))
    assert "funcoes/form.html" in nomes(r) and b"&quot;dia&quot;" in r.content


def test_form_so_adm(cliente_coordenador):
    assert cliente_coordenador.get(reverse("funcoes:nova")).status_code == 403


def test_executar_mostra_campos_e_erro(cliente_adm, funcao):
    url = reverse("funcoes:executar", kwargs={"pk": funcao.pk})
    r = cliente_adm.get(url)
    assert "funcoes/executar.html" in nomes(r) and b'type="date"' in r.content
    r = cliente_adm.post(url, {})
    assert r.status_code == 200 and "Preencha Dia." in r.content.decode()


def test_resultado_tabela_e_executar_de_novo(cliente_adm, usuario_adm, funcao):
    e = Execucao.objects.create(
        fluxo=funcao.fluxo, fluxo_nome="Base", grafo_snapshot={}, executado_por=usuario_adm, status="sucesso",
        finalizada_em=timezone.now(), funcao=funcao, funcao_nome=funcao.nome, funcao_versao=1, modo="para_mim",
        parametros={"dia": "2026-10-13"},
    )
    ExecucaoNo.objects.create(execucao=e, no_id="n1", no_tipo="saida", ordem=1, status="sucesso", saida=[{"json": {"id": 1, "nome": "<b>a</b>"}}], itens_saida=1)
    r = cliente_adm.get(reverse("funcoes:resultado", kwargs={"pk": e.pk}))
    assert "funcoes/resultado.html" in nomes(r)
    assert b"<b>a</b>" not in r.content and b"&lt;b&gt;a" in r.content
    assert b"Executar de novo" in r.content and b"Detalhe t" in r.content
