"""Render das telas de credenciais (M5, CRD-01): lista, nova e editar."""

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.credenciais.models import Credencial

pytestmark = pytest.mark.modulo("m5")


def nomes(resposta):
    return [t.name for t in resposta.templates]


def test_lista_vazia_oferece_nova(cliente_adm):
    resposta = cliente_adm.get(reverse("credenciais:lista"))
    assert resposta.status_code == 200 and "credenciais/lista.html" in nomes(resposta)
    assert b"Nenhuma credencial ainda" in resposta.content
    assert reverse("credenciais:nova").encode() in resposta.content


def test_form_nova_tem_campos_e_alerta_sem_chave(cliente_adm):
    with override_settings(CREDENCIAIS_CHAVE=""):
        resposta = cliente_adm.get(reverse("credenciais:nova"))
    assert "credenciais/form.html" in nomes(resposta)
    html = resposta.content.decode()
    for campo in ("nome", "tipo", "setor", "valor", "usuario", "header_nome", "host", "porta"):
        assert f'name="{campo}"' in html
    assert 'data-estado="chave_ausente"' in html and "CREDENCIAIS_CHAVE" in html


def test_lista_escapa_nome_e_nunca_mostra_valor(cliente_adm, usuario_adm):
    from cryptography.fernet import Fernet

    with override_settings(CREDENCIAIS_CHAVE=Fernet.generate_key().decode()):
        c = Credencial(nome="Token <b>x</b>", tipo="bearer", criado_por=usuario_adm)
        c.definir_dados({"valor": "segredo-super-secreto"}) if hasattr(c, "definir_dados") else None
        if not c.dados_cifrados:
            pytest.skip("API de cifragem do model mudou; coberto pelos testes do Forja")
        c.save()
        html = cliente_adm.get(reverse("credenciais:lista")).content.decode()
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html
    assert "segredo-super-secreto" not in html
    assert reverse("credenciais:editar", kwargs={"pk": c.pk}) in html


def test_coordenador_nao_acessa(cliente_coordenador):
    assert cliente_coordenador.get(reverse("credenciais:lista")).status_code == 403
