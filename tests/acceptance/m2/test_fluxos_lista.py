"""Aceite M2: lista de fluxos. Fontes: FLX-01, FLX-05, PRM-03, PRM-04 (TEL-04, TEL-12)."""
import re
from datetime import timedelta

import pytest
from django.apps import apps
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _h(r):
    return r.content.decode()


def _Fluxo():
    return apps.get_model("fluxos", "Fluxo")


def _carga(fabrica_fluxo, n, status="rascunho", prefixo="Carga"):
    return [fabrica_fluxo(nome=f"{prefixo} {i:02d}", status=status) for i in range(n)]


def _presentes(html, prefixo="Carga"):
    return len(set(re.findall(rf"{prefixo} \d\d", html)))


@pytest.mark.modulo("m2")
def test_anonimo_redireciona_para_login(cliente_anonimo):
    """PRM-01: lista de fluxos exige login."""
    r = cliente_anonimo.get(reverse("fluxos:lista"))
    assert r.status_code == 302 and r.url.startswith(reverse("login")) and "next=" in r.url


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("cliente", ["cliente_adm", "cliente_coordenador", "cliente_base"])
def test_todos_os_papeis_abrem_a_lista(request, cliente):
    """FLX-01: lista acessível a Adm, Coordenador e Base (lista vazia incluída)."""
    assert request.getfixturevalue(cliente).get(reverse("fluxos:lista")).status_code == 200


@pytest.mark.modulo("m2")
def test_lista_mostra_colunas(cliente_coordenador, fabrica_fluxo, usuario_adm):
    """FLX-01: nome, descrição, dono, status e link por linha."""
    fabrica_fluxo(nome="Fluxo Visível", descricao="Descrição única xyz", status="ativo")
    h = _h(cliente_coordenador.get(reverse("fluxos:lista")))
    assert "Fluxo Visível" in h and "Descrição única xyz" in h
    assert usuario_adm.nome in h
    assert "ativo" in h.lower()


@pytest.mark.modulo("m2")
def test_coordenador_e_adm_veem_rascunhos_e_ativos(cliente_coordenador, cliente_adm, fabrica_fluxo):
    """PRM-04/FLX-01: escopo 'todos' para Adm e Coordenador."""
    fabrica_fluxo(nome="Em Rascunho", status="rascunho")
    fabrica_fluxo(nome="Em Uso", status="ativo")
    for c in (cliente_coordenador, cliente_adm):
        h = _h(c.get(reverse("fluxos:lista")))
        assert "Em Rascunho" in h and "Em Uso" in h


@pytest.mark.modulo("m2")
def test_base_ve_so_ativos(cliente_base, fabrica_fluxo):
    """FLX-05/PRM-04: Base só vê fluxos ativos."""
    fabrica_fluxo(nome="Secreto Rascunho", status="rascunho")
    fabrica_fluxo(nome="Publico Ativo", status="ativo")
    h = _h(cliente_base.get(reverse("fluxos:lista")))
    assert "Publico Ativo" in h and "Secreto Rascunho" not in h


@pytest.mark.modulo("m2")
def test_base_nao_ve_rascunho_nem_por_busca_filtro_ou_paginacao(cliente_base, fabrica_fluxo):
    """PRM-04: fora do escopo nunca aparece, nem via ?q=, ?status=rascunho ou páginas."""
    _carga(fabrica_fluxo, 30, status="rascunho", prefixo="Oculto")
    fabrica_fluxo(nome="Visivel 00", status="ativo")
    url = reverse("fluxos:lista")
    for params in ({"q": "Oculto"}, {"status": "rascunho"}, {"pagina": 2}, {"q": "Oculto", "pagina": 2}):
        assert "Oculto" not in _h(cliente_base.get(url, params)), params
    assert "Visivel 00" in _h(cliente_base.get(url))


@pytest.mark.modulo("m2")
def test_base_sem_botoes_de_editar_excluir_com_executar(cliente_base, fabrica_fluxo):
    """FLX-05: Base sem editar/excluir/novo e com Executar."""
    f = fabrica_fluxo(nome="Executavel", status="ativo")
    h = _h(cliente_base.get(reverse("fluxos:lista")))
    assert reverse("fluxos:editor", kwargs={"pk": f.pk}) not in h
    assert reverse("fluxos:excluir", kwargs={"pk": f.pk}) not in h
    assert reverse("fluxos:editar", kwargs={"pk": f.pk}) not in h
    assert reverse("fluxos:novo") not in h
    assert reverse("fluxos:executar", kwargs={"pk": f.pk}) in h


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("cliente", ["cliente_coordenador", "cliente_adm"])
def test_coordenador_e_adm_veem_acoes_de_edicao(request, cliente, fabrica_fluxo):
    """PRM-05: quem pode editar vê Novo, Editar/Editor e Excluir."""
    f = fabrica_fluxo(nome="Editavel", status="ativo")
    h = _h(request.getfixturevalue(cliente).get(reverse("fluxos:lista")))
    assert reverse("fluxos:novo") in h
    assert reverse("fluxos:editor", kwargs={"pk": f.pk}) in h
    assert reverse("fluxos:excluir", kwargs={"pk": f.pk}) in h


@pytest.mark.modulo("m2")
def test_base_executar_rascunho_404(cliente_base, fabrica_fluxo):
    """PRM-03/FLX-05: Base executando fluxo em rascunho → 404 (objeto fora do escopo)."""
    f = fabrica_fluxo(status="rascunho")
    r = cliente_base.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    assert r.status_code == 404


@pytest.mark.modulo("m2")
def test_base_no_editor_403(cliente_base, fabrica_fluxo):
    """FLX-05/PRM-02: Base no editor recebe 403 (ação fluxos.editar = nenhum), mesmo de fluxo ativo."""
    f = fabrica_fluxo(status="ativo")
    assert cliente_base.get(reverse("fluxos:editor", kwargs={"pk": f.pk})).status_code == 403


@pytest.mark.modulo("m2")
def test_busca_por_nome_sem_caixa(cliente_adm, fabrica_fluxo):
    """FLX-01: ?q= no nome, contém, sem diferenciar maiúsculas."""
    fabrica_fluxo(nome="Pedidos Quimera")
    fabrica_fluxo(nome="Outro Fluxo")
    h = _h(cliente_adm.get(reverse("fluxos:lista"), {"q": "QUIMERA"}))
    assert "Pedidos Quimera" in h and "Outro Fluxo" not in h


@pytest.mark.modulo("m2")
def test_filtro_status(cliente_adm, fabrica_fluxo):
    """FLX-01: ?status=rascunho|ativo."""
    fabrica_fluxo(nome="So Rascunho", status="rascunho")
    fabrica_fluxo(nome="So Ativo", status="ativo")
    url = reverse("fluxos:lista")
    h = _h(cliente_adm.get(url, {"status": "ativo"}))
    assert "So Ativo" in h and "So Rascunho" not in h
    h = _h(cliente_adm.get(url, {"status": "rascunho"}))
    assert "So Rascunho" in h and "So Ativo" not in h


@pytest.mark.modulo("m2")
def test_ordenacao_padrao_e_por_atualizado_em_desc(cliente_adm, fabrica_fluxo):
    """FLX-01: padrão -atualizado_em (o mais recente primeiro)."""
    antigo = fabrica_fluxo(nome="Zebra Antigo")
    fabrica_fluxo(nome="Abelha Novo")
    _Fluxo().objects.filter(pk=antigo.pk).update(atualizado_em=timezone.now() - timedelta(days=5))
    h = _h(cliente_adm.get(reverse("fluxos:lista")))
    assert h.index("Abelha Novo") < h.index("Zebra Antigo")
    h = _h(cliente_adm.get(reverse("fluxos:lista"), {"ordem": "atualizado_em"}))
    assert h.index("Zebra Antigo") < h.index("Abelha Novo")


@pytest.mark.modulo("m2")
def test_ordenacao_por_nome(cliente_adm, fabrica_fluxo):
    """FLX-01: ?ordem=nome e -nome."""
    fabrica_fluxo(nome="Aaa Primeiro")
    fabrica_fluxo(nome="Zzz Ultimo")
    url = reverse("fluxos:lista")
    h = _h(cliente_adm.get(url, {"ordem": "nome"}))
    assert h.index("Aaa Primeiro") < h.index("Zzz Ultimo")
    h = _h(cliente_adm.get(url, {"ordem": "-nome"}))
    assert h.index("Zzz Ultimo") < h.index("Aaa Primeiro")


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("params", [{"ordem": "grafo"}, {"ordem": "dono__password"}, {"status": "arquivado"},
                                    {"pagina": "abc"}, {"pagina": "-2"}, {"q": "%" * 300}])
def test_valores_invalidos_sao_ignorados(cliente_adm, params):
    """FLX-01: valor inválido de filtro/ordem/página nunca dá 500."""
    assert cliente_adm.get(reverse("fluxos:lista"), params).status_code == 200


@pytest.mark.modulo("m2")
def test_paginacao_25_por_pagina(cliente_adm, fabrica_fluxo):
    """FLX-01: 30 fluxos → 25 na página 1 e 5 na página 2."""
    _carga(fabrica_fluxo, 30)
    url = reverse("fluxos:lista")
    assert _presentes(_h(cliente_adm.get(url, {"ordem": "nome", "q": "Carga"}))) == 25
    assert _presentes(_h(cliente_adm.get(url, {"ordem": "nome", "q": "Carga", "pagina": 2}))) == 5


@pytest.mark.modulo("m2")
def test_pagina_fora_do_intervalo_mostra_a_ultima(cliente_adm, fabrica_fluxo):
    """FLX-01: página fora do intervalo cai na última válida."""
    _carga(fabrica_fluxo, 30)
    h = _h(cliente_adm.get(reverse("fluxos:lista"), {"ordem": "nome", "q": "Carga", "pagina": 99}))
    assert _presentes(h) == 5


@pytest.mark.modulo("m2")
@pytest.mark.parametrize("cliente", ["cliente_adm", "cliente_coordenador", "cliente_base"])
def test_queries_da_lista_constantes(request, cliente, fabrica_fluxo, django_assert_max_num_queries):
    """FLX-01: nº de queries com 30 fluxos ≤ nº com 1 fluxo (sem N+1 no dono)."""
    c = request.getfixturevalue(cliente)
    fabrica_fluxo(nome="Primeiro", status="ativo")
    url = reverse("fluxos:lista")
    c.get(url)
    with CaptureQueriesContext(connection) as base:
        c.get(url)
    _carga(fabrica_fluxo, 29, status="ativo")
    with django_assert_max_num_queries(len(base.captured_queries)):
        assert c.get(url).status_code == 200


@pytest.mark.modulo("m2")
def test_xss_no_nome_e_descricao(cliente_adm, fabrica_fluxo):
    """SEG-13: nome e descrição de fluxo escapados na lista."""
    p = "<script>alert(1)</script>"
    fabrica_fluxo(nome=p, descricao=p)
    h = _h(cliente_adm.get(reverse("fluxos:lista")))
    assert p not in h and "&lt;script&gt;" in h
