import pytest
from cryptography.fernet import Fernet

from apps.credenciais import cofre

pytestmark = pytest.mark.modulo("m5")
SEGREDO = "SEGREDO-FICTICIO-123"


def test_cifra_e_decifra_sem_deixar_o_valor_em_claro(chave_credenciais):
    token = cofre.cifrar({"valor": SEGREDO, "usuario": "u"})
    assert SEGREDO not in token and token != cofre.cifrar({"valor": SEGREDO, "usuario": "u"})
    assert cofre.decifrar(token) == {"valor": SEGREDO, "usuario": "u"}


def test_sem_chave_recusa_cifrar_e_decifrar(chave_credenciais, settings):
    token = cofre.cifrar({"valor": SEGREDO})
    settings.CREDENCIAIS_CHAVE = ""
    assert not cofre.chave_configurada()
    for acao in (lambda: cofre.cifrar({}), lambda: cofre.decifrar(token)):
        with pytest.raises(cofre.ErroCofre) as erro:
            acao()
        assert "chave" in erro.value.mensagem.lower()


def test_chave_trocada_ou_invalida_vira_erro_claro_sem_texto_da_biblioteca(
    chave_credenciais, settings
):
    token = cofre.cifrar({"valor": SEGREDO})
    settings.CREDENCIAIS_CHAVE = Fernet.generate_key().decode()
    with pytest.raises(cofre.ErroCofre) as erro:
        cofre.decifrar(token)
    assert "chave" in erro.value.mensagem.lower() and "InvalidToken" not in erro.value.mensagem
    settings.CREDENCIAIS_CHAVE = "isto-nao-e-uma-chave"
    with pytest.raises(cofre.ErroCofre) as erro:
        cofre.cifrar({})
    assert "chave" in erro.value.mensagem.lower() and "isto-nao" not in erro.value.mensagem


def test_token_corrompido_vira_erro_do_cofre(chave_credenciais):
    with pytest.raises(cofre.ErroCofre):
        cofre.decifrar("lixo")
