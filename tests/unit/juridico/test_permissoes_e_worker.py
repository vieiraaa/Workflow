"""T-078: escopo setor_com_acesso (CAD-02), semente de carteiras e worker --uma-vez."""

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.contas.permissoes import escopo, pode
from apps.juridico.models import Carteira, ConfigCadastro, Envio, ItemEnvio, Processo

pytestmark = [pytest.mark.modulo("m8"), pytest.mark.django_db]


def test_semente_de_carteiras_e_config_unica():
    nomes = set(Carteira.objects.values_list("nome", flat=True))
    assert nomes >= {"Ativos", "Ailos", "Volvo", "Toyota", "BTB", "John Deere"}
    assert ConfigCadastro.obter().pk == ConfigCadastro.obter().pk == 1


def test_escopo_setor_com_acesso(usuario_adm, usuario_coordenador, usuario_base):
    config = ConfigCadastro.obter()
    assert pode(usuario_adm, "cadastro.ver") and pode(usuario_adm, "cadastro.configurar")
    assert not pode(usuario_coordenador, "cadastro.ver")  # lista de setores vazia: só o Adm
    config.setores_com_acesso.add(usuario_coordenador.setor)
    usuario_coordenador._acesso_cadastro = usuario_base._acesso_cadastro = None
    for atributo in ("_acesso_cadastro", "_papel_cache"):
        usuario_coordenador.__dict__.pop(atributo, None)
        usuario_base.__dict__.pop(atributo, None)
    assert pode(usuario_coordenador, "cadastro.ver") and pode(usuario_base, "cadastro.editar")
    assert not pode(usuario_coordenador, "cadastro.configurar")
    assert escopo(usuario_base, Processo.objects).count() == 0


def test_rotas_exigem_login_e_acesso(cliente_anonimo, cliente_base):
    for nome in ("painel", "envios", "erros", "audiencias", "enviar_pdfs", "enviar_cnj", "config"):
        resposta = cliente_anonimo.get(reverse(f"juridico:{nome}"))
        assert resposta.status_code == 302 and reverse("login") in resposta["Location"]
        assert cliente_base.get(reverse(f"juridico:{nome}")).status_code == 403  # sem acesso


def test_worker_uma_vez_com_fila_vazia_sai(capsys):
    call_command("processar_cadastros", "--uma-vez")
    assert "0 item(ns) processado(s)." in capsys.readouterr().out


def test_worker_sem_credencial_vira_erro_claro_e_encerra_o_envio(usuario_adm):
    envio = Envio.objects.create(origem=Envio.CNJ, enviado_por=usuario_adm)
    from apps.juridico import cnj

    numero = cnj.so_digitos(cnj.numero_valido_de(12345, 2022, 8, 26, 100))
    item = ItemEnvio.objects.create(envio=envio, numero_informado=numero)
    call_command("processar_cadastros", "--uma-vez")
    item.refresh_from_db(), envio.refresh_from_db()
    assert item.status == ItemEnvio.CONCLUIDO  # CNJ: o processo é gravado mesmo se o DataJud falhar
    assert item.etapa_erro in ("CNJ (DataJud)", "Dados incompletos") and item.processo_id
    assert envio.terminado_em is not None
