import pytest
from django.core.management import call_command

from apps.contas.models import Usuario

pytestmark = [pytest.mark.modulo("m0"), pytest.mark.django_db]


def test_semear_demo_cria_tres_usuarios_e_e_idempotente(capsys):
    call_command("semear_demo")
    saida = capsys.readouterr().out
    assert "Senha gerada" in saida
    call_command("semear_demo")
    assert Usuario.objects.count() == 3
    papeis = {u.email: u.groups.get().name for u in Usuario.objects.all()}
    assert papeis == {
        "adm@exemplo.test": "Adm",
        "coord@exemplo.test": "Coordenador",
        "base@exemplo.test": "Base",
    }


def test_semear_demo_senha_informada_nao_e_impressa(capsys):
    call_command("semear_demo", "--senha", "SenhaForte#12345")
    assert "SenhaForte" not in capsys.readouterr().out
    assert Usuario.objects.get(email="adm@exemplo.test").check_password("SenhaForte#12345")
