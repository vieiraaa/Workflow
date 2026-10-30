"""Login pelo Active Directory (D-039). O AD é sempre mock: os testes nunca tocam a rede."""

from unittest import mock

import pytest
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from apps.contas import ad
from apps.contas.models import Setor, Usuario
from apps.contas.permissoes import papel_de

pytestmark = [pytest.mark.modulo("m1"), pytest.mark.django_db]

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


@pytest.fixture(autouse=True)
def modo_ad(settings):
    settings.LOGIN_AD = True
    settings.AUTHENTICATION_BACKENDS = ["apps.contas.ad.BackendAD"]
    settings.AD_GRUPOS_PERMITIDOS = []
    cache.clear()
    yield
    cache.clear()


def _dados(login="maria.souza", email="maria.souza@eem.adv.br", nome="Maria Souza", grupos=()):
    return ad.DadosAD(login=login, email=email, nome=nome, grupos=list(grupos))


@pytest.fixture
def ad_aceita():
    with mock.patch.object(ad, "autenticar_no_ad", return_value=_dados()) as m:
        yield m


@pytest.fixture
def ad_recusa():
    with mock.patch.object(ad, "autenticar_no_ad", return_value=None) as m:
        yield m


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("maria.souza", "maria.souza"),
        ("  EEM\\Maria.Souza ", "maria.souza"),
        ("maria.souza@eem.adv.br", "maria.souza"),
        ("*)(objectClass=*", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_normalizar_login(texto, esperado):
    assert ad.normalizar_login(texto) == esperado


def test_tela_pede_usuario_de_rede(cliente_anonimo):
    corpo = cliente_anonimo.get(reverse("login")).content.decode()
    assert "Usuário" in corpo and "nome.sobrenome" in corpo and "usuário de rede" in corpo
    assert 'id="carregamento"' in corpo


def test_primeiro_login_cria_usuario_base_no_setor_padrao(cliente_anonimo, ad_aceita):
    geral = Setor.objects.get_or_create(nome="Geral")[0]
    r = cliente_anonimo.post(reverse("login"), {"username": "EEM\\maria.souza", "password": "x"})
    assert r.status_code == 302 and r.url == reverse("inicio")
    ad_aceita.assert_called_once_with("maria.souza", "x")
    u = Usuario.objects.get(email="maria.souza@eem.adv.br")
    assert u.nome == "Maria Souza" and u.setor == geral and not u.has_usable_password()
    assert papel_de(u) == "base"
    assert cliente_anonimo.session["_auth_user_id"] == str(u.pk)


def test_usuario_existente_mantem_papel(cliente_anonimo, usuario_adm):
    with mock.patch.object(
        ad, "autenticar_no_ad", return_value=_dados(email=usuario_adm.email.upper())
    ):
        r = cliente_anonimo.post(reverse("login"), {"username": "ana", "password": "x"})
    assert r.status_code == 302
    usuario_adm.refresh_from_db()
    assert papel_de(usuario_adm) == "adm"
    assert Usuario.objects.filter(email__iexact=usuario_adm.email).count() == 1


def test_senha_local_nao_vale(cliente_anonimo, usuario_adm, senha_teste, ad_recusa):
    r = cliente_anonimo.post(
        reverse("login"), {"username": usuario_adm.email, "password": senha_teste}
    )
    assert r.status_code == 200
    assert list(r.context["form"].non_field_errors()) == ["Usuário ou senha inválidos."]
    assert "_auth_user_id" not in cliente_anonimo.session


def test_usuario_inativo_nao_entra(cliente_anonimo, usuario_base):
    usuario_base.is_active = False
    usuario_base.save()
    with mock.patch.object(ad, "autenticar_no_ad", return_value=_dados(email=usuario_base.email)):
        r = cliente_anonimo.post(reverse("login"), {"username": "bia", "password": "x"})
    assert r.status_code == 200 and "_auth_user_id" not in cliente_anonimo.session


def test_ad_indisponivel_avisa(cliente_anonimo):
    with mock.patch.object(ad, "autenticar_no_ad", side_effect=ad.ADIndisponivel("rede")):
        r = cliente_anonimo.post(reverse("login"), {"username": "maria.souza", "password": "x"})
    assert list(r.context["form"].non_field_errors()) == [
        "Não foi possível conectar ao AD. Tente novamente em instantes."
    ]


def test_falha_de_infra_vira_ad_indisponivel():
    with mock.patch.object(ad, "_credencial_servico", side_effect=OSError("sem rede")):
        with pytest.raises(ad.ADIndisponivel):
            ad.autenticar_no_ad("maria.souza", "x")


def test_senha_vazia_nem_consulta_o_ad():
    with mock.patch.object(ad, "_credencial_servico") as cred:
        assert ad.autenticar_no_ad("maria.souza", "") is None
    cred.assert_not_called()


def test_grupo_fora_dos_permitidos_nao_entra(cliente_anonimo, settings):
    settings.AD_GRUPOS_PERMITIDOS = ["controladoria"]
    with mock.patch.object(ad, "autenticar_no_ad", return_value=_dados(grupos=["Financeiro"])):
        r = cliente_anonimo.post(reverse("login"), {"username": "maria.souza", "password": "x"})
    assert list(r.context["form"].non_field_errors()) == [
        "Seu usuário não tem permissão para acessar o Construtor de Workflows."
    ]
    assert not Usuario.objects.filter(email="maria.souza@eem.adv.br").exists()


def test_grupo_permitido_entra(cliente_anonimo, settings):
    settings.AD_GRUPOS_PERMITIDOS = ["controladoria"]
    with mock.patch.object(ad, "autenticar_no_ad", return_value=_dados(grupos=["Controladoria"])):
        r = cliente_anonimo.post(reverse("login"), {"username": "maria.souza", "password": "x"})
    assert r.status_code == 302


def test_cinco_erros_bloqueiam_sem_consultar_o_ad(cliente_anonimo, ad_recusa):
    for _ in range(5):
        cliente_anonimo.post(reverse("login"), {"username": "maria.souza", "password": "errada"})
    r = cliente_anonimo.post(reverse("login"), {"username": "maria.souza", "password": "errada"})
    assert ad_recusa.call_count == 5
    assert r.context["form"].non_field_errors()[0].startswith("Muitas tentativas.")
    r = cliente_anonimo.post(
        reverse("login"), {"username": "maria.souza", "password": "x"}, **FETCH
    )
    assert r.status_code == 429


def test_fetch_sucesso_devolve_nome_e_destino(cliente_anonimo, ad_aceita):
    r = cliente_anonimo.post(
        reverse("login") + "?next=/fluxos/",
        {"username": "maria.souza", "password": "x", "next": "/fluxos/"},
        **FETCH,
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True, "nome": "Maria", "destino": "/fluxos/"}


def test_fetch_erro_devolve_json(cliente_anonimo, ad_recusa):
    r = cliente_anonimo.post(
        reverse("login"), {"username": "maria.souza", "password": "errada"}, **FETCH
    )
    assert r.status_code == 400
    assert r.json() == {
        "ok": False,
        "erros": [{"campo": None, "mensagem": "Usuário ou senha inválidos."}],
    }


def test_login_adm_nasce_adm(cliente_anonimo, settings):
    settings.AD_LOGINS_ADM = ["joao.vieira"]
    dados = _dados(login="joao.vieira", email="joao.vieira@eem.adv.br", nome="João Vieira")
    with mock.patch.object(ad, "autenticar_no_ad", return_value=dados):
        r = cliente_anonimo.post(reverse("login"), {"username": "joao.vieira", "password": "x"})
    assert r.status_code == 302
    assert papel_de(Usuario.objects.get(email="joao.vieira@eem.adv.br")) == "adm"


def test_login_adm_que_ja_era_base_vira_adm(cliente_anonimo, settings, usuario_base):
    settings.AD_LOGINS_ADM = ["joao.vieira"]
    dados = _dados(login="joao.vieira", email=usuario_base.email)
    with mock.patch.object(ad, "autenticar_no_ad", return_value=dados):
        cliente_anonimo.post(reverse("login"), {"username": "joao.vieira", "password": "x"})
    assert papel_de(Usuario.objects.get(pk=usuario_base.pk)) == "adm"


def test_outros_logins_nao_viram_adm(cliente_anonimo, settings, ad_aceita):
    settings.AD_LOGINS_ADM = ["joao.vieira"]
    cliente_anonimo.post(reverse("login"), {"username": "maria.souza", "password": "x"})
    assert papel_de(Usuario.objects.get(email="maria.souza@eem.adv.br")) == "base"


def test_cargo_vem_do_ad_e_atualiza_a_cada_login():
    def entrar(cargo):
        with mock.patch.object(ad, "autenticar_no_ad", return_value=_dados()) as m:
            m.return_value.cargo = cargo
            Client().post(reverse("login"), {"username": "maria.souza", "password": "x"})
        return Usuario.objects.get(email="maria.souza@eem.adv.br").cargo

    assert entrar("Analista") == "Analista"
    assert entrar("Coordenadora de Prazos") == "Coordenadora de Prazos"
    assert entrar("") == "Coordenadora de Prazos"  # AD sem cargo não apaga o que já existe
