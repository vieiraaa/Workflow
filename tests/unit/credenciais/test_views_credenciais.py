import pytest
from django.db import connection
from django.urls import reverse

from apps.credenciais.models import Credencial

pytestmark = [pytest.mark.modulo("m5"), pytest.mark.django_db]
SEGREDO = "SEGREDO-FICTICIO-VIEW-456"


def _dados(**extra):
    return {"nome": "Digisac", "tipo": "bearer", "valor": SEGREDO, "setor": "", **extra}


def _html(resposta):
    return resposta.content.decode()


@pytest.mark.parametrize("rota", ["credenciais:lista", "credenciais:nova"])
def test_so_adm_acessa(rota, cliente_adm, cliente_coordenador, cliente_base, cliente_anonimo):
    url = reverse(rota)
    assert cliente_adm.get(url).status_code == 200
    assert cliente_coordenador.get(url).status_code == 403
    assert cliente_base.get(url).status_code == 403
    resposta = cliente_anonimo.get(url)
    assert resposta.status_code == 302 and resposta["Location"].startswith(reverse("login"))


def test_criar_cifra_o_valor_e_nao_o_mostra(cliente_adm, usuario_adm, chave_credenciais):
    resposta = cliente_adm.post(reverse("credenciais:nova"), _dados())
    assert resposta["Location"] == reverse("credenciais:lista")
    credencial = Credencial.objects.get()
    assert credencial.criado_por == usuario_adm and credencial.dados()["valor"] == SEGREDO
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT dados_cifrados FROM "{Credencial._meta.db_table}"')
        assert SEGREDO not in cursor.fetchone()[0]
    lista = _html(cliente_adm.get(resposta["Location"]))
    assert "Credencial Digisac salva." in lista and SEGREDO not in lista
    edicao = _html(cliente_adm.get(reverse("credenciais:editar", kwargs={"pk": credencial.pk})))
    assert SEGREDO not in edicao


def test_contexto_da_lista(cliente_adm, chave_credenciais):
    cliente_adm.post(reverse("credenciais:nova"), _dados())
    contexto = cliente_adm.get(reverse("credenciais:lista")).context
    linha = contexto["credenciais"][0]
    assert linha["nome"] == "Digisac" and linha["tipo_rotulo"] == "Bearer token"
    assert linha["url_editar"] and linha["url_excluir"] and linha["setor_nome"] == ""
    assert contexto["total"] == 1 and contexto["chave_ausente"] is False and contexto["pode_criar"]


@pytest.mark.parametrize(
    "extra,mensagem",
    [
        ({"nome": ""}, "Este campo é obrigatório."),
        ({"nome": "n" * 81}, "Use no máximo 80 caracteres."),
        ({"valor": ""}, "Este campo é obrigatório."),
        ({"tipo": "oauth"}, "Valor inválido."),
        ({"setor": "999999"}, "Valor inválido."),
        ({"tipo": "header", "header_nome": ""}, "Este campo é obrigatório."),
        ({"tipo": "basic", "usuario": ""}, "Este campo é obrigatório."),
        ({"tipo": "smtp", "usuario": "u", "host": "", "porta": "587"}, "Este campo é obrigatório."),
        ({"tipo": "smtp", "usuario": "u", "host": "h", "porta": "99999"}, "Valor inválido."),
    ],
)
def test_validacao(extra, mensagem, cliente_adm, chave_credenciais):
    resposta = cliente_adm.post(reverse("credenciais:nova"), _dados(**extra))
    assert resposta.status_code == 200 and mensagem in _html(resposta)
    assert Credencial.objects.count() == 0


def test_nome_unico_sem_diferenciar_maiusculas(cliente_adm, chave_credenciais):
    cliente_adm.post(reverse("credenciais:nova"), _dados())
    resposta = cliente_adm.post(reverse("credenciais:nova"), _dados(nome="DIGISAC"))
    assert "Já existe uma credencial com este nome." in _html(resposta)
    assert Credencial.objects.count() == 1


def test_sem_chave_recusa_salvar(cliente_adm, settings):
    settings.CREDENCIAIS_CHAVE = ""
    resposta = cliente_adm.post(reverse("credenciais:nova"), _dados())
    assert resposta.status_code == 200 and "chave" in _html(resposta).lower()
    assert Credencial.objects.count() == 0
    assert cliente_adm.get(reverse("credenciais:lista")).context["chave_ausente"] is True


def test_editar_vazio_mantem_e_novo_valor_troca(cliente_adm, chave_credenciais):
    cliente_adm.post(reverse("credenciais:nova"), _dados())
    credencial = Credencial.objects.get()
    url = reverse("credenciais:editar", kwargs={"pk": credencial.pk})
    resposta = cliente_adm.post(url, _dados(valor="", nome="Digisac 2"), follow=True)
    assert "Credencial Digisac 2 salva." in _html(resposta)
    credencial.refresh_from_db()
    assert credencial.nome == "Digisac 2" and credencial.dados()["valor"] == SEGREDO
    cliente_adm.post(url, _dados(valor="NOVO-VALOR-789", nome="Digisac 2"))
    credencial.refresh_from_db()
    assert credencial.dados()["valor"] == "NOVO-VALOR-789"


def test_excluir_so_por_post(cliente_adm, chave_credenciais):
    cliente_adm.post(reverse("credenciais:nova"), _dados())
    url = reverse("credenciais:excluir", kwargs={"pk": Credencial.objects.get().pk})
    assert cliente_adm.get(url).status_code == 405 and Credencial.objects.count() == 1
    resposta = cliente_adm.post(url, follow=True)
    assert "Credencial Digisac excluída." in _html(resposta) and Credencial.objects.count() == 0
    assert cliente_adm.post(url).status_code == 404


def test_nao_adm_nao_altera_nada(
    cliente_adm, cliente_coordenador, cliente_base, cliente_anonimo, chave_credenciais
):
    cliente_adm.post(reverse("credenciais:nova"), _dados())
    credencial = Credencial.objects.get()
    for cliente in (cliente_coordenador, cliente_base, cliente_anonimo):
        cliente.post(reverse("credenciais:nova"), _dados(nome="Invasor"))
        cliente.post(reverse("credenciais:editar", kwargs={"pk": credencial.pk}), _dados(nome="X"))
        cliente.post(reverse("credenciais:excluir", kwargs={"pk": credencial.pk}))
    assert list(Credencial.objects.values_list("nome", flat=True)) == ["Digisac"]
