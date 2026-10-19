"""Telas do Jurídico (M8, TEL-27..35) contra as views reais: template específico + trechos do contrato."""

import pytest
from django.urls import reverse

from apps.juridico.models import Carteira, Envio, ItemEnvio, Processo

pytestmark = [pytest.mark.modulo("m8"), pytest.mark.django_db]

HOSTIL = "<script>alert(1)</script>"


def nomes(resposta):
    return [t.name for t in resposta.templates]


@pytest.fixture
def carteira(db):
    return Carteira.objects.get_or_create(nome="Ativos", defaults={"empresa": "ATIVOS S.A."})[0]


@pytest.fixture
def processo(db, carteira, usuario_adm):
    return Processo.objects.create(
        numero="0008655-91.2025.8.16.0024", numero_digitos="00086559120258160024", numero_valido=True, status=Processo.CONFERIR,
        adverso_nome=f"Fulano {HOSTIL}", adverso_cpf_cnpj="01704835925", carteira=carteira, comarca="Curitiba",
        criado_por=usuario_adm, criado_via=Processo.PDF, pendencias=[],
    )


@pytest.fixture
def envio(db, usuario_adm, carteira, processo):
    e = Envio.objects.create(origem=Envio.PDF, enviado_por=usuario_adm, carteira=carteira)
    ItemEnvio.objects.create(envio=e, nome_arquivo=f"a{HOSTIL}.pdf", status=ItemEnvio.NA_FILA)
    ItemEnvio.objects.create(envio=e, nome_arquivo="b.pdf", status=ItemEnvio.ERRO, etapa_erro="IA (Dify)", motivo="A IA não respondeu", processo=processo)
    return e


def test_painel_vazio_e_com_dados(cliente_adm, processo):
    r = cliente_adm.get(reverse("juridico:painel"))
    assert "juridico/painel.html" in nomes(r) and r.status_code == 200
    assert b"Painel de Processos" in r.content and b"0008655-91.2025.8.16.0024" in r.content
    assert HOSTIL.encode() not in r.content and b"&lt;script&gt;" in r.content
    assert b"***.***" not in r.content and b"Cadastro manual" in r.content and b"Configura" in r.content
    Processo.objects.all().delete()
    r = cliente_adm.get(reverse("juridico:painel"))
    assert b"Nenhum processo cadastrado ainda" in r.content


def test_painel_com_fila_liga_o_refresh(cliente_adm, envio):
    r = cliente_adm.get(reverse("juridico:painel"))
    assert b"data-status-url" in r.content and reverse("juridico:status").encode() in r.content


def test_painel_filtrado(cliente_adm, processo):
    r = cliente_adm.get(reverse("juridico:painel") + "?q=zzzz&status=CONFERIR")
    assert b"Nenhum processo encontrado" in r.content


def test_conferencia(cliente_adm, processo):
    r = cliente_adm.get(reverse("juridico:processo", kwargs={"pk": processo.pk}))
    assert "juridico/processo.html" in nomes(r) and "componentes/formulario_processo.html" in nomes(r)
    for trecho in (b"Valida", b"Marcar como cadastrado no Espaider", b"Consultar CNJ de novo", b'name="numero"', b"Hist"):
        assert trecho in r.content, trecho
    assert HOSTIL.encode() not in r.content


def test_cadastro_manual(cliente_adm):
    r = cliente_adm.get(reverse("juridico:processo_novo"))
    assert "juridico/processo_novo.html" in nomes(r) and b"Cadastrar processo" in r.content


def test_enviar_pdfs_e_cnj(cliente_adm):
    r = cliente_adm.get(reverse("juridico:enviar_pdfs"))
    assert "juridico/enviar_pdfs.html" in nomes(r) and b'name="arquivos"' in r.content and b"multiple" in r.content
    r = cliente_adm.post(reverse("juridico:enviar_pdfs"), {})
    assert "juridico/enviar_pdfs.html" in nomes(r) and b"Escolha ao menos um PDF." in r.content
    r = cliente_adm.get(reverse("juridico:enviar_cnj"))
    assert "juridico/enviar_cnj.html" in nomes(r) and b'name="numeros"' in r.content
    r = cliente_adm.post(reverse("juridico:enviar_cnj"), {"numeros": "", "carteira": ""})
    assert "juridico/enviar_cnj.html" in nomes(r) and b"Informe ao menos um n" in r.content


def test_envios_e_detalhe_do_envio(cliente_adm, envio):
    r = cliente_adm.get(reverse("juridico:envios"))
    assert "juridico/envios.html" in nomes(r)
    r = cliente_adm.get(reverse("juridico:envio", kwargs={"pk": envio.pk}))
    assert "juridico/envio.html" in nomes(r) and b"data-envio" in r.content and b"Tentar de novo" in r.content
    assert HOSTIL.encode() not in r.content and f"status/?envio={envio.pk}".encode() in r.content
    Envio.objects.all().delete()
    assert b"Nenhum envio ainda" in cliente_adm.get(reverse("juridico:envios")).content


def test_log_de_erros(cliente_adm, envio):
    r = cliente_adm.get(reverse("juridico:erros"))
    assert "juridico/erros.html" in nomes(r) and b"Casos por dia" in r.content and b"Resolvido" in r.content
    assert HOSTIL.encode() not in r.content
    ItemEnvio.objects.all().delete()
    assert b"Nenhum erro pendente" in cliente_adm.get(reverse("juridico:erros")).content


def test_audiencias_config_e_excluidos(cliente_adm, processo):
    r = cliente_adm.get(reverse("juridico:audiencias"))
    assert "juridico/audiencias.html" in nomes(r) and b"Nenhuma audi" in r.content
    r = cliente_adm.get(reverse("juridico:config"))
    assert "juridico/config.html" in nomes(r) and b"Testar conex" in r.content and b"Ativos" in r.content
    r = cliente_adm.get(reverse("juridico:excluidos"))
    assert "juridico/excluidos.html" in nomes(r) and b"Nenhum processo exclu" in r.content


def test_sem_acesso_403_e_menu_so_com_acesso(cliente_base, cliente_adm):
    assert cliente_base.get(reverse("juridico:painel")).status_code == 403
    html = cliente_adm.get(reverse("inicio")).content
    assert b"Cadastro de processos" in html and b"sidebar__grupo" in html
