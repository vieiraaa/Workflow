"""Aceite M1: tela de usuários. Fontes: USR-01..12, SEG-13 (TEL-02, TEL-03, TEL-09, TEL-08)."""
import re

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _html(r):
    return r.content.decode()


def _criar_carga(fabrica_usuario, n, prefixo="Carga"):
    return [fabrica_usuario(nome=f"{prefixo} {i:02d}", email=f"{prefixo.lower()}{i:02d}@exemplo.test")
            for i in range(n)]


def _presentes(html, prefixo="carga"):
    return len(set(re.findall(rf"{prefixo}\d\d@exemplo\.test", html)))


# ---------- USR-01 / USR-02 / USR-03: lista ----------

@pytest.mark.modulo("m1")
def test_lista_mostra_colunas_e_acao_editar(cliente_adm, usuario_base):
    """USR-01: nome, e-mail, papel, status e link Editar por linha."""
    html = _html(cliente_adm.get(reverse("contas:usuarios")))
    assert usuario_base.email in html
    assert reverse("contas:usuario_editar", kwargs={"pk": usuario_base.pk}) in html
    assert "Base" in html


@pytest.mark.modulo("m1")
def test_busca_por_nome_ou_email_sem_caixa(cliente_adm, fabrica_usuario):
    """USR-02: ?q= contém, case-insensitive, em nome OU e-mail."""
    fabrica_usuario(nome="Zuleica Quimera", email="zq1@exemplo.test")
    fabrica_usuario(nome="Outro Nome", email="quimera.mail@exemplo.test")
    fabrica_usuario(nome="Nada Ver", email="nada@exemplo.test")
    html = _html(cliente_adm.get(reverse("contas:usuarios"), {"q": "QUIMERA"}))
    assert "zq1@exemplo.test" in html
    assert "quimera.mail@exemplo.test" in html
    assert "nada@exemplo.test" not in html


@pytest.mark.modulo("m1")
def test_filtro_papel_e_ativo(cliente_adm, fabrica_usuario):
    """USR-02: ?papel= e ?ativo= filtram."""
    fabrica_usuario(papel="Coordenador", email="coord-f@exemplo.test")
    fabrica_usuario(papel="Base", email="base-f@exemplo.test")
    fabrica_usuario(papel="Base", email="inativo-f@exemplo.test", ativo=False)
    url = reverse("contas:usuarios")
    h = _html(cliente_adm.get(url, {"papel": "coordenador"}))
    assert "coord-f@exemplo.test" in h and "base-f@exemplo.test" not in h
    h = _html(cliente_adm.get(url, {"ativo": "0"}))
    assert "inativo-f@exemplo.test" in h and "base-f@exemplo.test" not in h
    h = _html(cliente_adm.get(url, {"ativo": "1"}))
    assert "base-f@exemplo.test" in h and "inativo-f@exemplo.test" not in h


@pytest.mark.modulo("m1")
def test_ordenacao_nome_e_desc(cliente_adm, fabrica_usuario):
    """USR-02: ?ordem=nome e -nome."""
    fabrica_usuario(nome="Aaa Primeiro", email="ord-a@exemplo.test")
    fabrica_usuario(nome="Zzz Ultimo", email="ord-z@exemplo.test")
    url = reverse("contas:usuarios")
    h = _html(cliente_adm.get(url, {"ordem": "nome", "q": "ord-"}))
    assert h.index("ord-a@") < h.index("ord-z@")
    h = _html(cliente_adm.get(url, {"ordem": "-nome", "q": "ord-"}))
    assert h.index("ord-z@") < h.index("ord-a@")


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("ordem", ["email", "-email", "criado_em", "-criado_em"])
def test_ordenacoes_validas_respondem_200(cliente_adm, ordem):
    """USR-02: demais ordenações válidas."""
    assert cliente_adm.get(reverse("contas:usuarios"), {"ordem": ordem}).status_code == 200


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("params", [
    {"ordem": "senha"}, {"ordem": "-password"}, {"ordem": "nome;drop"}, {"papel": "root"},
    {"ativo": "talvez"}, {"pagina": "abc"}, {"pagina": "-3"}, {"pagina": "0"}, {"q": "%" * 500},
])
def test_valor_invalido_e_ignorado_sem_500(cliente_adm, params):
    """USR-02/USR-03: valor inválido de filtro/ordem/página nunca dá 500."""
    assert cliente_adm.get(reverse("contas:usuarios"), params).status_code == 200


@pytest.mark.modulo("m1")
def test_paginacao_25_por_pagina_com_30_usuarios(cliente_adm, fabrica_usuario):
    """USR-03: 30 usuários → 25 na pág. 1 e 5 na pág. 2."""
    _criar_carga(fabrica_usuario, 30)
    url = reverse("contas:usuarios")
    assert _presentes(_html(cliente_adm.get(url, {"q": "carga", "ordem": "nome"}))) == 25
    assert _presentes(_html(cliente_adm.get(url, {"q": "carga", "ordem": "nome", "pagina": 2}))) == 5


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("pagina", ["99", "3"])
def test_pagina_fora_do_intervalo_mostra_a_ultima(cliente_adm, fabrica_usuario, pagina):
    """USR-03: página fora do intervalo mostra a última página válida."""
    _criar_carga(fabrica_usuario, 30)
    r = cliente_adm.get(reverse("contas:usuarios"), {"q": "carga", "ordem": "nome", "pagina": pagina})
    assert r.status_code == 200
    assert _presentes(_html(r)) == 5


@pytest.mark.modulo("m1")
def test_queries_da_lista_constantes(cliente_adm, fabrica_usuario, django_assert_max_num_queries):
    """USR-03: nº de queries com 30 usuários ≤ nº com 1 usuário."""
    url = reverse("contas:usuarios")
    cliente_adm.get(url)  # aquece caches (content types etc.)
    with CaptureQueriesContext(connection) as base:
        cliente_adm.get(url)
    _criar_carga(fabrica_usuario, 30)
    with django_assert_max_num_queries(len(base.captured_queries)):
        r = cliente_adm.get(url)
    assert r.status_code == 200


# ---------- USR-04 / USR-05: criar ----------

@pytest.mark.modulo("m1")
def test_criar_usuario_sucesso_redireciona_com_toast(cliente_adm, dados_usuario):
    """USR-04: sucesso → redirect para a lista + mensagem 'Usuário <nome> criado.'"""
    r = cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(nome="Maria Ficticia"), follow=True)
    assert r.redirect_chain and r.redirect_chain[-1][0] == reverse("contas:usuarios")
    assert "Usuário Maria Ficticia criado." in _html(r)
    u = get_user_model().objects.get(email="maria@exemplo.test")
    assert u.groups.filter(name="Base").exists()
    assert u.check_password("Senha-Forte-Ficticia-91")


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("papel", ["Adm", "Coordenador", "Base"])
def test_criar_com_cada_papel(cliente_adm, dados_usuario, papel):
    """USR-04: o papel escolhido vira o único grupo do usuário."""
    cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(email=f"{papel.lower()}@exemplo.test", papel=papel.lower()))
    u = get_user_model().objects.get(email=f"{papel.lower()}@exemplo.test")
    assert list(u.groups.values_list("name", flat=True)) == [papel]


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("senha", ["curta1", "123456789012", "aaaaaaaaaaaa"])
def test_criar_senha_fraca_recusada(cliente_adm, dados_usuario, senha):
    """USR-04: senha passa pelos validadores (mín. 10, não só numérica, não comum)."""
    r = cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(email="fraca@exemplo.test", senha=senha))
    assert r.status_code == 200
    assert not get_user_model().objects.filter(email="fraca@exemplo.test").exists()


@pytest.mark.modulo("m1")
def test_criar_email_duplicado_mesmo_com_maiusculas(cliente_adm, dados_usuario, usuario_base):
    """USR-05: e-mail duplicado (case-insensitive) → erro no campo."""
    n = get_user_model().objects.count()
    r = cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(email=usuario_base.email.upper()))
    assert r.status_code == 200
    assert "Já existe um usuário com este e-mail." in _html(r)
    assert get_user_model().objects.count() == n


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("campo", ["nome", "email", "papel", "senha"])
def test_criar_obrigatorio_vazio(cliente_adm, dados_usuario, campo):
    """USR-05: campo obrigatório vazio → erro, nada criado."""
    d = dados_usuario(email="vazio@exemplo.test")
    d[campo] = ""
    n = get_user_model().objects.count()
    r = cliente_adm.post(reverse("contas:usuario_novo"), d)
    assert r.status_code == 200
    assert get_user_model().objects.count() == n


@pytest.mark.modulo("m1")
def test_criar_senhas_diferentes(cliente_adm, dados_usuario):
    """USR-05: confirmação diferente → erro, nada criado."""
    r = cliente_adm.post(reverse("contas:usuario_novo"),
                         dados_usuario(email="dif@exemplo.test", confirmacao="Outra-Senha-Forte-77"))
    assert r.status_code == 200
    assert not get_user_model().objects.filter(email="dif@exemplo.test").exists()


@pytest.mark.modulo("m1")
def test_email_normalizado_minusculo_sem_espacos(cliente_adm, dados_usuario):
    """Modelo/USR-05: e-mail salvo em minúsculas e sem espaços nas pontas."""
    cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(email="  Caixa.Alta@Exemplo.TEST  "))
    assert get_user_model().objects.filter(email="caixa.alta@exemplo.test").exists()


@pytest.mark.modulo("m1")
def test_nome_acima_de_120_recusado(cliente_adm, dados_usuario):
    """Modelo (nome max 120): 121 caracteres é recusado sem 500."""
    r = cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(nome="n" * 121, email="longo@exemplo.test"))
    assert r.status_code == 200
    assert not get_user_model().objects.filter(email="longo@exemplo.test").exists()


@pytest.mark.modulo("m1")
def test_nome_com_120_aceito(cliente_adm, dados_usuario):
    """Modelo (nome max 120): limite exato aceito."""
    cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(nome="n" * 120, email="limite@exemplo.test"))
    assert get_user_model().objects.filter(email="limite@exemplo.test").exists()


@pytest.mark.modulo("m1")
def test_papel_pelo_nome_do_group_e_invalido(cliente_adm, dados_usuario):
    """USR-14: o valor do papel é o id; o nome do Group ('Adm') não vale."""
    r = cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(email="nomegrp@exemplo.test", papel="Adm"))
    assert r.status_code == 200
    assert "Papel inválido." in _html(r)
    assert not get_user_model().objects.filter(email="nomegrp@exemplo.test").exists()


@pytest.mark.modulo("m1")
def test_papel_vazio_mensagem(cliente_adm, dados_usuario):
    """USR-14: papel vazio → 'Escolha um papel.'"""
    r = cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(email="semp@exemplo.test", papel=""))
    assert r.status_code == 200
    assert "Escolha um papel." in _html(r)


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("campo", ["nome", "email", "senha"])
def test_obrigatorio_vazio_mensagem_padrao(cliente_adm, dados_usuario, campo):
    """USR-14: campo obrigatório vazio → 'Este campo é obrigatório.'"""
    d = dados_usuario(email="obrig@exemplo.test")
    d[campo] = ""
    r = cliente_adm.post(reverse("contas:usuario_novo"), d)
    assert r.status_code == 200
    assert "Este campo é obrigatório." in _html(r)


@pytest.mark.modulo("m1")
def test_papel_inexistente_recusado(cliente_adm, dados_usuario):
    """USR-04: papel fora de Adm|Coordenador|Base é recusado."""
    r = cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(email="papel@exemplo.test", papel="root"))
    assert r.status_code == 200
    assert "Papel inválido." in _html(r)
    assert not get_user_model().objects.filter(email="papel@exemplo.test").exists()


# ---------- USR-06 / 07 / 08: editar ----------

@pytest.mark.modulo("m1")
def test_editar_altera_nome_email_papel_ativo(cliente_adm, fabrica_usuario, dados_usuario):
    """USR-06: edita nome, e-mail, papel e ativo."""
    u = fabrica_usuario(papel="Base")
    r = cliente_adm.post(reverse("contas:usuario_editar", kwargs={"pk": u.pk}),
                         dados_usuario(nome="Novo Nome", email="novo@exemplo.test", papel="coordenador",
                                       ativo=False, com_senha=False))
    assert r.status_code == 302
    u.refresh_from_db()
    assert (u.nome, u.email, u.is_active) == ("Novo Nome", "novo@exemplo.test", False)
    assert list(u.groups.values_list("name", flat=True)) == ["Coordenador"]


@pytest.mark.modulo("m1")
def test_editar_nao_altera_senha(cliente_adm, fabrica_usuario, dados_usuario, senha_padrao):
    """USR-06: a edição não mexe na senha, mesmo se o POST trouxer campos de senha."""
    u = fabrica_usuario()
    cliente_adm.post(reverse("contas:usuario_editar", kwargs={"pk": u.pk}),
                     dados_usuario(email=u.email, nome=u.nome, senha="Outra-Senha-Forte-55"))
    u.refresh_from_db()
    assert u.check_password(senha_padrao)


@pytest.mark.modulo("m1")
def test_editar_email_duplicado(cliente_adm, fabrica_usuario, dados_usuario):
    """USR-05: duplicidade também vale na edição."""
    a, b = fabrica_usuario(), fabrica_usuario()
    r = cliente_adm.post(reverse("contas:usuario_editar", kwargs={"pk": b.pk}),
                         dados_usuario(nome=b.nome, email=a.email.upper(), com_senha=False))
    assert r.status_code == 200
    assert "Já existe um usuário com este e-mail." in _html(r)


@pytest.mark.modulo("m1")
def test_editar_pk_inexistente_404(cliente_adm):
    """PRM-03: objeto inexistente → 404 do produto."""
    r = cliente_adm.get(reverse("contas:usuario_editar", kwargs={"pk": 999999}))
    assert r.status_code == 404


@pytest.mark.modulo("m1")
def test_adm_nao_se_desativa(cliente_adm, usuario_adm, dados_usuario):
    """USR-07: Adm não desativa a si mesmo."""
    r = cliente_adm.post(reverse("contas:usuario_editar", kwargs={"pk": usuario_adm.pk}),
                         dados_usuario(nome=usuario_adm.nome, email=usuario_adm.email, papel="adm",
                                       ativo=False, com_senha=False))
    assert r.status_code == 200
    assert "Você não pode desativar a si mesmo nem remover o seu papel de administrador." in _html(r)
    usuario_adm.refresh_from_db()
    assert usuario_adm.is_active


@pytest.mark.modulo("m1")
def test_adm_nao_tira_de_si_o_papel(cliente_adm, usuario_adm, dados_usuario):
    """USR-07: Adm não troca o próprio papel."""
    r = cliente_adm.post(reverse("contas:usuario_editar", kwargs={"pk": usuario_adm.pk}),
                         dados_usuario(nome=usuario_adm.nome, email=usuario_adm.email, papel="base",
                                       com_senha=False))
    assert r.status_code == 200
    assert "Você não pode desativar a si mesmo nem remover o seu papel de administrador." in _html(r)
    assert usuario_adm.groups.filter(name="Adm").exists()


@pytest.mark.modulo("m1")
def test_adm_pode_editar_o_proprio_nome(cliente_adm, usuario_adm, dados_usuario):
    """USR-07 (limite): editar outros campos de si mesmo, mantendo papel e ativo, é permitido."""
    r = cliente_adm.post(reverse("contas:usuario_editar", kwargs={"pk": usuario_adm.pk}),
                         dados_usuario(nome="Adm Renomeado", email=usuario_adm.email, papel="adm",
                                       com_senha=False))
    assert r.status_code == 302
    usuario_adm.refresh_from_db()
    assert usuario_adm.nome == "Adm Renomeado"


@pytest.mark.modulo("m1")
def test_nunca_zero_adm_ativo(cliente_adm, usuario_adm, fabrica_usuario, dados_usuario):
    """USR-08: com um único Adm ativo (e outro Adm inativo), nenhuma edição o remove."""
    fabrica_usuario(papel="Adm", ativo=False)
    cliente_adm.post(reverse("contas:usuario_editar", kwargs={"pk": usuario_adm.pk}),
                     dados_usuario(nome=usuario_adm.nome, email=usuario_adm.email, papel="coordenador",
                                   ativo=False, com_senha=False))
    assert get_user_model().objects.filter(is_active=True, groups__name="Adm").exists()


@pytest.mark.modulo("m1")
def test_adm_pode_desativar_outro_adm_havendo_mais_de_um(cliente_adm, fabrica_usuario, dados_usuario):
    """USR-08 (limite): com dois Adm ativos, desativar o outro é permitido."""
    outro = fabrica_usuario(papel="Adm")
    r = cliente_adm.post(reverse("contas:usuario_editar", kwargs={"pk": outro.pk}),
                         dados_usuario(nome=outro.nome, email=outro.email, papel="adm", ativo=False,
                                       com_senha=False))
    assert r.status_code == 302
    outro.refresh_from_db()
    assert not outro.is_active


# ---------- USR-09: sem exclusão ----------

@pytest.mark.modulo("m1")
def test_nao_existe_rota_de_exclusao(cliente_adm, usuario_base):
    """USR-09: nenhuma rota de exclusão; POST de delete em editar não apaga."""
    from django.urls import NoReverseMatch
    for nome in ("contas:usuario_excluir", "contas:usuario_remover", "contas:usuario_apagar"):
        with pytest.raises(NoReverseMatch):
            reverse(nome, kwargs={"pk": usuario_base.pk})
    cliente_adm.post(reverse("contas:usuario_editar", kwargs={"pk": usuario_base.pk}), {"delete": "1"})
    assert get_user_model().objects.filter(pk=usuario_base.pk).exists()


# ---------- USR-10: trocar a própria senha ----------

@pytest.mark.modulo("m1")
@pytest.mark.parametrize("papel", ["Adm", "Coordenador", "Base"])
def test_trocar_senha_sucesso_mantem_sessao(client, fabrica_usuario, papel, senha_padrao):
    """USR-10: senha atual + nova + confirmação; sucesso mantém sessão."""
    u = fabrica_usuario(papel=papel)
    client.force_login(u)
    r = client.post(reverse("contas:trocar_senha"),
                    {"senha_atual": senha_padrao, "nova_senha": "Nova-Senha-Forte-42",
                     "confirmacao": "Nova-Senha-Forte-42"}, follow=True)
    assert r.status_code == 200
    assert "Senha alterada." in _html(r)
    u.refresh_from_db()
    assert u.check_password("Nova-Senha-Forte-42")
    assert client.get(reverse("contas:trocar_senha")).status_code == 200  # ainda logado


@pytest.mark.modulo("m1")
def test_trocar_senha_atual_errada(client, fabrica_usuario, senha_padrao):
    """USR-10: senha atual incorreta → erro, senha inalterada."""
    u = fabrica_usuario()
    client.force_login(u)
    r = client.post(reverse("contas:trocar_senha"),
                    {"senha_atual": "errada-errada-1", "nova_senha": "Nova-Senha-Forte-42",
                     "confirmacao": "Nova-Senha-Forte-42"})
    assert r.status_code == 200
    u.refresh_from_db()
    assert u.check_password(senha_padrao)


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("nova,conf", [("Nova-Senha-Forte-42", "Diferente-Forte-43"), ("curta1", "curta1")])
def test_trocar_senha_invalida(client, fabrica_usuario, senha_padrao, nova, conf):
    """USR-10/USR-04: confirmação diferente ou senha fraca → erro, inalterada."""
    u = fabrica_usuario()
    client.force_login(u)
    r = client.post(reverse("contas:trocar_senha"),
                    {"senha_atual": senha_padrao, "nova_senha": nova, "confirmacao": conf})
    assert r.status_code == 200
    u.refresh_from_db()
    assert u.check_password(senha_padrao)


# ---------- USR-11 / USR-12 ----------

@pytest.mark.modulo("m1")
def test_desativar_usuario_derruba_acesso_na_proxima_requisicao(cliente_adm, fabrica_usuario, dados_usuario):
    """USR-11/PAP-04: Adm desativa um usuário logado; a próxima requisição dele cai no login."""
    from django.test import Client
    client = Client()
    alvo = fabrica_usuario(papel="Coordenador")
    client.force_login(alvo)
    assert client.get(reverse("contas:trocar_senha")).status_code == 200
    cliente_adm.post(reverse("contas:usuario_editar", kwargs={"pk": alvo.pk}),
                     dados_usuario(nome=alvo.nome, email=alvo.email, papel="coordenador", ativo=False,
                                   com_senha=False))
    r = client.get(reverse("contas:trocar_senha"))
    assert r.status_code == 302 and reverse("login") in r.url


@pytest.mark.modulo("m1")
def test_xss_nome_escapado_na_lista_e_na_edicao(cliente_adm, fabrica_usuario):
    """USR-12/SEG-13: nome com <script> aparece como texto escapado."""
    payload = "<script>alert(1)</script>"
    u = fabrica_usuario(nome=payload)
    for url in (reverse("contas:usuarios"), reverse("contas:usuario_editar", kwargs={"pk": u.pk})):
        html = _html(cliente_adm.get(url))
        assert payload not in html
        assert "&lt;script&gt;" in html


@pytest.mark.modulo("m1")
def test_xss_nome_escapado_no_toast_de_criacao(cliente_adm, dados_usuario):
    """USR-12/SEG-13: o toast 'Usuário <nome> criado.' também escapa."""
    payload = "<img src=x onerror=alert(1)>"
    r = cliente_adm.post(reverse("contas:usuario_novo"),
                         dados_usuario(nome=payload, email="xss@exemplo.test"), follow=True)
    assert payload not in _html(r)


@pytest.mark.modulo("m1")
def test_xss_nome_escapado_no_menu_do_proprio_usuario(client, fabrica_usuario):
    """USR-12/SEG-13: nome exibido no shell do usuário logado é escapado."""
    payload = "<script>alert(2)</script>"
    client.force_login(fabrica_usuario(nome=payload))
    html = _html(client.get(reverse("contas:trocar_senha")))
    assert payload not in html


@pytest.mark.modulo("m1")
def test_idor_base_nao_edita_nem_le_outro_usuario(cliente_base, usuario_coordenador, dados_usuario):
    """PRM-02/USR-01: Base não lê nem altera outro usuário por pk (403, nada muda)."""
    url = reverse("contas:usuario_editar", kwargs={"pk": usuario_coordenador.pk})
    assert cliente_base.get(url).status_code == 403
    r = cliente_base.post(url, dados_usuario(nome="Invadido", email="inv@exemplo.test", papel="adm", com_senha=False))
    assert r.status_code == 403
    usuario_coordenador.refresh_from_db()
    assert usuario_coordenador.nome != "Invadido"
    assert not usuario_coordenador.groups.filter(name="Adm").exists()


@pytest.mark.modulo("m1")
def test_escalada_via_trocar_senha_nao_muda_papel(cliente_base, usuario_base, senha_padrao):
    """PRM-02: campos extras (papel, is_superuser) no POST de trocar senha são ignorados."""
    cliente_base.post(reverse("contas:trocar_senha"),
                      {"senha_atual": senha_padrao, "nova_senha": "Nova-Senha-Forte-42",
                       "confirmacao": "Nova-Senha-Forte-42", "papel": "Adm", "is_superuser": "on"})
    usuario_base.refresh_from_db()
    assert not usuario_base.is_superuser
    assert not usuario_base.groups.filter(name="Adm").exists()


# ---------- USR-06: redefinir senha (USR-13) ----------

@pytest.mark.modulo("m1")
def test_redefinir_senha_sucesso(cliente_adm, fabrica_usuario):
    """USR-06/USR-13: POST válido → redirect para editar + toast 'Senha de <nome> redefinida.'"""
    alvo = fabrica_usuario(nome="Alvo Ficticio")
    url_editar = reverse("contas:usuario_editar", kwargs={"pk": alvo.pk})
    r = cliente_adm.post(reverse("contas:usuario_redefinir_senha", kwargs={"pk": alvo.pk}),
                         {"nova_senha": "Redefinida-Forte-31", "confirmacao": "Redefinida-Forte-31"},
                         follow=True)
    assert r.redirect_chain and r.redirect_chain[-1][0] == url_editar
    assert "Senha de Alvo Ficticio redefinida." in _html(r)
    alvo.refresh_from_db()
    assert alvo.check_password("Redefinida-Forte-31")


@pytest.mark.modulo("m1")
@pytest.mark.parametrize("nova,conf", [("Redefinida-Forte-31", "Outra-Forte-32"), ("curta1", "curta1"),
                                        ("", "")])
def test_redefinir_senha_erro_rerenderiza_edicao(cliente_adm, fabrica_usuario, senha_padrao, nova, conf):
    """USR-06/USR-13: erro → 200 (tela de edição) e senha inalterada."""
    alvo = fabrica_usuario()
    r = cliente_adm.post(reverse("contas:usuario_redefinir_senha", kwargs={"pk": alvo.pk}),
                         {"nova_senha": nova, "confirmacao": conf})
    assert r.status_code == 200
    assert alvo.email in _html(r)
    alvo.refresh_from_db()
    assert alvo.check_password(senha_padrao)


@pytest.mark.modulo("m1")
def test_redefinir_senha_pk_inexistente_404(cliente_adm):
    """PRM-03/USR-13: pk inexistente → 404."""
    r = cliente_adm.post(reverse("contas:usuario_redefinir_senha", kwargs={"pk": 999999}),
                         {"nova_senha": "Redefinida-Forte-31", "confirmacao": "Redefinida-Forte-31"})
    assert r.status_code == 404


@pytest.mark.modulo("m1")
def test_adm_redefine_a_propria_senha_pelo_fluxo_admin(cliente_adm, usuario_adm):
    """USR-06 (limite): redefinir a própria senha pela rota admin é permitido e não derruba o Adm."""
    r = cliente_adm.post(reverse("contas:usuario_redefinir_senha", kwargs={"pk": usuario_adm.pk}),
                         {"nova_senha": "Redefinida-Forte-31", "confirmacao": "Redefinida-Forte-31"})
    assert r.status_code == 302
    usuario_adm.refresh_from_db()
    assert usuario_adm.is_active and usuario_adm.groups.filter(name="Adm").exists()


# ---------- USR-08: mensagem exata (USR-14) ----------

@pytest.mark.modulo("m1")
def test_ultimo_adm_mensagem(cliente_adm, usuario_adm, dados_usuario):
    """USR-08/USR-14: recusa de zerar Adm ativo mostra uma das mensagens definidas em USR-14."""
    r = cliente_adm.post(reverse("contas:usuario_editar", kwargs={"pk": usuario_adm.pk}),
                         dados_usuario(nome=usuario_adm.nome, email=usuario_adm.email, papel="coordenador",
                                       ativo=False, com_senha=False))
    h = _html(r)
    assert r.status_code == 200
    assert ("É preciso manter pelo menos um administrador ativo." in h
            or "Você não pode desativar a si mesmo nem remover o seu papel de administrador." in h)
