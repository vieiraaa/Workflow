"""Botão "Reconsultar DataJud" do painel: fila de novo só para quem falhou ou não foi encontrado."""

import pytest
from django.urls import reverse

from apps.juridico import cnj, servico
from apps.juridico.models import Envio, ItemEnvio, Processo

pytestmark = [pytest.mark.modulo("m8"), pytest.mark.django_db]


def _processo(seq, situacao, valido=True):
    numero = cnj.numero_valido_de(seq, 2022, 8, 26, 100)
    digitos = cnj.so_digitos(numero)
    if not valido:
        digitos = digitos[:-1] + str((int(digitos[-1]) + 1) % 10)
    return Processo.objects.create(
        numero=cnj.formatar(digitos), numero_digitos=digitos, numero_valido=valido,
        cnj_validacao=situacao, origem_campos={},
    )  # fmt: skip


@pytest.fixture
def processos():
    return {
        "falhou": _processo(1, "falhou"),
        "nao_encontrado": _processo(2, "nao_encontrado"),
        "confere": _processo(3, "confere"),
        "divergente": _processo(4, "divergente"),
        "nao_consultado": _processo(5, "nao_consultado"),
        "invalido": _processo(6, "falhou", valido=False),
    }


def test_so_falhou_e_nao_encontrado_com_numero_valido(processos):
    pks = set(servico.a_reconsultar().values_list("pk", flat=True))
    assert pks == {processos["falhou"].pk, processos["nao_encontrado"].pk}


def test_excluido_fica_de_fora(processos, usuario_adm):
    from django.utils import timezone

    processos["falhou"].excluido_em = timezone.now()
    processos["falhou"].save()
    assert list(servico.a_reconsultar()) == [processos["nao_encontrado"]]


def test_post_enfileira_e_abre_o_envio(processos, cliente_adm):
    resposta = cliente_adm.post(reverse("juridico:reconsultar_cnj"))
    envio = Envio.objects.get()
    assert resposta.status_code == 302 and resposta["Location"] == reverse(
        "juridico:envio", kwargs={"pk": envio.pk}
    )
    assert envio.origem == Envio.CNJ and envio.carteira is None
    assert set(envio.itens.values_list("numero_informado", flat=True)) == {
        processos["falhou"].numero_digitos,
        processos["nao_encontrado"].numero_digitos,
    }
    assert set(envio.itens.values_list("status", flat=True)) == {ItemEnvio.NA_FILA}


def test_segundo_clique_nao_repete_o_que_ja_esta_na_fila(processos, cliente_adm):
    cliente_adm.post(reverse("juridico:reconsultar_cnj"))
    resposta = cliente_adm.post(reverse("juridico:reconsultar_cnj"), follow=True)
    assert Envio.objects.count() == 1 and ItemEnvio.objects.count() == 2
    assert "Nenhum processo para consultar de novo" in resposta.content.decode()


def test_painel_mostra_o_botao_com_a_contagem(processos, cliente_adm):
    html = cliente_adm.get(reverse("juridico:painel")).content.decode()
    assert reverse("juridico:reconsultar_cnj") in html
    assert "Reconsultar DataJud" in html and "(2)" in html


def test_painel_sem_nada_a_reconsultar_nao_mostra_o_botao(cliente_adm):
    _processo(3, "confere")
    html = cliente_adm.get(reverse("juridico:painel")).content.decode()
    assert reverse("juridico:reconsultar_cnj") not in html


def test_get_nao_vale_e_anonimo_vai_para_o_login(processos, cliente_adm, cliente_anonimo):
    assert cliente_adm.get(reverse("juridico:reconsultar_cnj")).status_code == 405
    resposta = cliente_anonimo.post(reverse("juridico:reconsultar_cnj"))
    assert resposta.status_code == 302 and reverse("login") in resposta["Location"]
    assert not Envio.objects.exists()


def test_sem_acesso_ao_cadastro_e_403(processos, cliente_base):
    assert cliente_base.post(reverse("juridico:reconsultar_cnj")).status_code == 403
    assert not Envio.objects.exists()


def test_worker_reconsulta_e_atualiza_o_mesmo_processo(processos, usuario_adm, monkeypatch):
    from apps.juridico import processamento

    class DataJudFalso:  # continua não encontrado, mas consultado de novo
        def __init__(self, config):
            pass

        def consultar(self, alias, digitos):
            return None

    monkeypatch.setattr(processamento, "DataJud", DataJudFalso)
    envio, n = servico.criar_envio_reconsulta(usuario_adm)
    assert n == 2
    while (item := processamento.reservar_proximo()) is not None:
        processamento.processar_item(item)
    assert Processo.objects.count() == 6  # nenhum processo novo
    assert set(envio.itens.values_list("acao", flat=True)) == {ItemEnvio.ATUALIZADO}
    for chave in ("falhou", "nao_encontrado"):
        processos[chave].refresh_from_db()
        assert processos[chave].cnj_validacao == "nao_encontrado"
        assert processos[chave].cnj_consultado_em is not None
