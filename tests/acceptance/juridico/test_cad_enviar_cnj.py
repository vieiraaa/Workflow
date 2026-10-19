"""Aceite M8 · cadastrar pelo CNJ (CAD-05, CAD-06b no formulário, TEL-30). Só pela spec."""
import re

import pytest
from django.urls import reverse

from .conftest import cnj, criar_processo

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

URL = "juridico:enviar_cnj"


def test_tela_tem_numeros_e_carteira(cad, ver):
    """TEL-30: textarea `numeros` e `carteira` com as carteiras ativas + 'Outra / não sei'."""
    cad.carteiras["Volvo"].__class__.objects.filter(pk=cad.carteiras["Volvo"].pk).update(ativa=False)
    r = cad.ana.get(reverse(URL))
    h = ver.html(r)
    assert r.status_code == 200 and 'name="numeros"' in h and 'name="carteira"' in h
    assert "Ativos" in h and "Ailos" in h and "Outra / não sei" in h and "Volvo" not in h


def test_enfileira_numeros_novos_com_separadores_variados(cad):
    """CAD-05: separadores quebra de linha, vírgula e ponto e vírgula; cada número de 20 dígitos vira um item na fila."""
    (f1, d1), (_, d2), (f3, d3) = cnj(1), cnj(2), cnj(3)
    r = cad.ana.post(reverse(URL), {"numeros": f"{f1}\n{d2}, {f3} ;", "carteira": cad.carteiras["Ativos"].pk})
    envio = cad.Envio.objects.get()
    assert r.status_code == 302 and r["Location"] == reverse("juridico:envio", kwargs={"pk": envio.pk})
    assert envio.origem == "cnj" and envio.enviado_por == cad.ana_u and envio.carteira == cad.carteiras["Ativos"]
    itens = cad.ItemEnvio.objects.filter(envio=envio)
    assert itens.count() == 3 and set(itens.values_list("status", flat=True)) == {"na_fila"}
    assert {"".join(c for c in i.numero_informado if c.isdigit()) for i in itens} == {d1, d2, d3}


def test_numero_invalido_vira_item_com_erro(cad, ver):
    """CAD-05: fora do padrão de 20 dígitos → item com erro 'Número inválido (o padrão CNJ tem 20 dígitos): <texto>'."""
    f1, _ = cnj(1)
    r = cad.ana.post(reverse(URL), {"numeros": f"{f1}\n12345\nabc", "carteira": ""})
    assert r.status_code == 302
    itens = {i.numero_informado: i for i in cad.ItemEnvio.objects.all()}
    assert {i.status for k, i in itens.items() if k in ("12345", "abc")} == {"erro"}
    assert itens["12345"].motivo == "Número inválido (o padrão CNJ tem 20 dígitos): 12345"
    assert itens["abc"].motivo == "Número inválido (o padrão CNJ tem 20 dígitos): abc"
    assert sum(1 for i in itens.values() if i.status == "na_fila") == 1


def test_vazio(cad, ver):
    """CAD-05: vazio → 'Informe ao menos um número.' e nada criado (também só separadores/espaços)."""
    for v in ("", "   \n ; , "):
        r = cad.ana.post(reverse(URL), {"numeros": v, "carteira": ""})
        assert r.status_code == 200 and "Informe ao menos um número." in ver.texto(r)
    assert cad.Envio.objects.count() == 0


def test_limite_de_50_numeros(cad, ver):
    """CAD-05: até 50 números; 51 → recusado, nada criado."""
    lista = [cnj(i)[0] for i in range(1, 52)]
    r = cad.ana.post(reverse(URL), {"numeros": "\n".join(lista), "carteira": ""})
    assert r.status_code == 200 and cad.Envio.objects.count() == 0
    assert "50" in ver.texto(r)
    r = cad.ana.post(reverse(URL), {"numeros": "\n".join(lista[:50]), "carteira": ""})
    assert r.status_code == 302 and cad.ItemEnvio.objects.count() == 50


def test_carteira_inexistente_ou_inativa_e_recusada(cad):
    """CAD-05: carteira só dentre as ativas (pk inválido/inativa → 200 com erro de campo, nada criado)."""
    cad.Carteira.objects.filter(pk=cad.carteiras["Volvo"].pk).update(ativa=False)
    for valor in (cad.carteiras["Volvo"].pk, 999999, "abc"):
        r = cad.ana.post(reverse(URL), {"numeros": cnj(1)[0], "carteira": valor})
        assert r.status_code == 200, valor
    assert cad.Envio.objects.count() == 0


def test_cnj_exige_acesso(cad):
    """cadastro.enviar: sem acesso 403; anônimo login."""
    assert cad.carla.post(reverse(URL), {"numeros": cnj(1)[0], "carteira": ""}).status_code == 403
    r = cad.anonimo.post(reverse(URL), {"numeros": cnj(1)[0], "carteira": ""})
    assert r.status_code == 302 and reverse("login") in r["Location"]
    assert cad.Envio.objects.count() == 0


# ---------------- CAD-06 (b) no formulário: dois passos ----------------

def test_numero_ja_existente_mostra_confirmacao_antes_de_enfileirar(cad, ver):
    """CAD-06b/CAD-23(3): se algum número já existe → 200 com confirmação por número ('Este processo já existia: cadastrado
    por <nome> (<e-mail>) em DD/MM/AAAA via <origem>'); NADA é enfileirado até confirmar."""
    novo, existente = cnj(1), cnj(2)
    p = criar_processo(cad, numero=existente, usuario=cad.bruno_u, via="pdf")
    r = cad.ana.post(reverse(URL), {"numeros": f"{novo[0]}\n{existente[0]}", "carteira": ""})
    t = ver.texto(r)
    assert r.status_code == 200 and cad.Envio.objects.count() == 0 and cad.ItemEnvio.objects.count() == 0
    assert re.search(r"já exist\w*.{0,20}cadastrado por Bruno Lima \(bruno\.lima@exemplo\.test\) em " + ver.data_br(p.criado_em.astimezone()) + r".{0,8}via PDF", t, re.I)
    assert existente[0] in t and novo[0] in t
    assert 'name="confirmar"' in ver.html(r) and "Confirmar" in t


def test_confirmar_enfileira_e_redireciona(cad):
    """CAD-23(3): 2º POST com os mesmos numeros+carteira + confirmar=1 → enfileira e redireciona para o envio."""
    novo, existente = cnj(1), cnj(2)
    criar_processo(cad, numero=existente)
    dados = {"numeros": f"{novo[0]}\n{existente[0]}", "carteira": cad.carteiras["Ativos"].pk}
    r = cad.ana.post(reverse(URL), {**dados, "confirmar": "1"})
    envio = cad.Envio.objects.get()
    assert r.status_code == 302 and r["Location"] == reverse("juridico:envio", kwargs={"pk": envio.pk})
    assert cad.ItemEnvio.objects.filter(envio=envio).count() == 2


@pytest.mark.parametrize("via,rotulo", [("pdf", "PDF"), ("cnj", "CNJ"), ("manual", "manual")])
def test_confirmacao_mostra_a_origem_de_cada_cadastro(cad, ver, via, rotulo):
    """CAD-06b: 'via <PDF|CNJ|manual>' conforme criado_via do processo existente."""
    ex = cnj(2)
    criar_processo(cad, numero=ex, via=via)
    t = ver.texto(cad.ana.post(reverse(URL), {"numeros": ex[0], "carteira": ""}))
    assert f"via {rotulo}" in t


def test_todos_novos_enfileira_direto_sem_confirmacao(cad):
    """CAD-23(3): se TODOS são novos e válidos, enfileira direto (redirect)."""
    r = cad.ana.post(reverse(URL), {"numeros": f"{cnj(1)[0]}\n{cnj(2)[0]}", "carteira": ""})
    assert r.status_code == 302 and cad.ItemEnvio.objects.count() == 2


def test_invalidos_viram_item_com_erro_mesmo_apos_confirmar(cad):
    """CAD-23(3): inválidos (≠ 20 dígitos) viram item com erro em qualquer caso, inclusive no passo de confirmação."""
    ex = cnj(2)
    criar_processo(cad, numero=ex)
    cad.ana.post(reverse(URL), {"numeros": f"{ex[0]}\n999", "carteira": "", "confirmar": "1"})
    assert cad.ItemEnvio.objects.filter(status="erro", numero_informado="999").count() == 1


def test_numero_excluido_tambem_conta_como_existente_na_confirmacao(cad, ver):
    """CAD-06d/b: número de processo excluído aparece na confirmação (será restaurado), nunca é tratado como novo silenciosamente."""
    from django.utils import timezone
    ex = cnj(2)
    criar_processo(cad, numero=ex, excluido_em=timezone.now(), excluido_por=cad.bruno_u)
    r = cad.ana.post(reverse(URL), {"numeros": ex[0], "carteira": ""})
    assert r.status_code == 200 and cad.ItemEnvio.objects.count() == 0 and re.search(r"já exist", ver.texto(r), re.I)
