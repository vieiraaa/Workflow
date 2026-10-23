"""Aceite M8 · DUPLICIDADE: mostrar que já temos e QUEM enviou (CAD-06 a–d). Ponto central pedido pelo usuário. Só pela spec."""
import re
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from .conftest import campos_dify, cnj, criar_processo, pdf_processo

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

NUM, DIG = cnj(1234)


def _envio_url(item):
    return reverse("juridico:envio", kwargs={"pk": item.envio_id})


def _momentos(dt_alvo, *extras):
    """DD/MM/AAAA HH:MM aceitos para um instante (tolera 1 min de diferença entre criado/iniciado/terminado)."""
    base = timezone.localtime(dt_alvo)
    return {(base + timedelta(minutes=m)).strftime("%d/%m/%Y %H:%M") for m in (-1, 0, 1)}


def _aviso_arquivo(t, numero, nome, email):
    pat = rf"Já temos este arquivo: processo {re.escape(numero)} · enviado por {re.escape(nome)} \({re.escape(email)}\) em (\d{{2}}/\d{{2}}/\d{{4}} \d{{2}}:\d{{2}})\."
    return re.search(pat, t)


# ---------------- (a) mesmo arquivo ----------------

def test_mesmo_arquivo_e_detectado_na_hora_sem_chamar_o_dify(cad, ingerir, enviar):
    """CAD-06a: sha256 igual a item já concluído é detectado NO ENVIO (antes da fila): item ignorado, nenhuma chamada ao Dify."""
    arq = pdf_processo(NUM)
    enviar(cad.ana, arq)
    from django.core.management import call_command
    call_command("processar_cadastros", "--uma-vez")
    chamadas = len(cad.dify.chats)
    original = cad.ItemEnvio.objects.get()
    r = enviar(cad.bruno, arq)  # outro usuário, mesmo arquivo — SEM rodar o worker
    novo = cad.ItemEnvio.objects.exclude(pk=original.pk).get()
    assert r.status_code == 302 and novo.status == "ignorado" and novo.duplicado_de_id == original.pk
    call_command("processar_cadastros", "--uma-vez")
    assert len(cad.dify.chats) == chamadas and cad.dify.uploads == [] and cad.Processo.objects.count() == 1
    novo.refresh_from_db()
    assert novo.status == "ignorado" and novo.processo_id in (None, original.processo_id)


def test_tela_do_envio_mostra_quem_enviou_nome_email_e_quando(cad, ingerir, enviar, ver):
    """CAD-06a: 'Já temos este arquivo: processo <número> · enviado por <nome> (<e-mail>) em DD/MM/AAAA HH:MM.' + link p/ o processo."""
    arq = pdf_processo(NUM)
    enviar(cad.ana, arq)
    from django.core.management import call_command
    call_command("processar_cadastros", "--uma-vez")
    original = cad.ItemEnvio.objects.get()
    p = original.processo
    enviar(cad.bruno, arq)
    novo = cad.ItemEnvio.objects.exclude(pk=original.pk).get()
    r = cad.bruno.get(_envio_url(novo))
    t = ver.texto(r)
    m = _aviso_arquivo(t, NUM, "Ana Souza", "ana.souza@exemplo.test")
    assert m, t[:2000]
    assert m.group(1) in _momentos(original.envio.criado_em) | _momentos(original.envio.iniciado_em or original.envio.criado_em) | \
        _momentos(original.envio.terminado_em or original.envio.criado_em)
    assert reverse("juridico:processo", kwargs={"pk": p.pk}) in ver.html(r)


def test_aviso_aparece_tambem_para_o_adm_e_identifica_o_autor_do_envio_original_nao_o_atual(cad, enviar, rodar, ver):
    """CAD-06a: quem aparece é QUEM ENVIOU O ORIGINAL (Ana), mesmo quando o reenvio é do Adm."""
    arq = pdf_processo(NUM)
    enviar(cad.ana, arq)
    rodar()
    original = cad.ItemEnvio.objects.get()
    enviar(cad.adm, arq)
    novo = cad.ItemEnvio.objects.exclude(pk=original.pk).get()
    t = ver.texto(cad.adm.get(_envio_url(novo)))
    assert _aviso_arquivo(t, NUM, "Ana Souza", "ana.souza@exemplo.test")


def test_mesmo_usuario_reenviando_tambem_e_avisado(cad, enviar, rodar, ver):
    """CAD-06a: 'de qualquer usuário' inclui o próprio — ele vê o próprio nome/e-mail."""
    arq = pdf_processo(NUM)
    enviar(cad.ana, arq)
    rodar()
    enviar(cad.ana, arq)
    novo = cad.ItemEnvio.objects.order_by("pk").last()
    assert novo.status == "ignorado"
    assert _aviso_arquivo(ver.texto(cad.ana.get(_envio_url(novo))), NUM, "Ana Souza", "ana.souza@exemplo.test")


def test_arquivo_com_outro_nome_mas_mesmo_conteudo_e_duplicado(cad, enviar, rodar):
    """CAD-06a: a identidade é o sha256 (conteúdo), não o nome do arquivo."""
    conteudo, _ = pdf_processo(NUM)
    enviar(cad.ana, (conteudo, "um.pdf"))
    rodar()
    enviar(cad.bruno, (conteudo, "outro-nome-totalmente-diferente.pdf"))
    assert cad.ItemEnvio.objects.order_by("pk").last().status == "ignorado"


def test_conteudo_diferente_com_mesmo_nome_nao_e_duplicado_de_arquivo(cad, enviar, rodar):
    """CAD-06a: mesmo nome, conteúdo diferente → NÃO é 'mesmo arquivo' (vai para a fila)."""
    a, _ = pdf_processo(NUM, "a")
    b, _ = pdf_processo(NUM, "b")
    enviar(cad.ana, (a, "igual.pdf"))
    rodar()
    enviar(cad.bruno, (b, "igual.pdf"))
    assert cad.ItemEnvio.objects.order_by("pk").last().status == "na_fila"


def test_arquivo_que_falhou_antes_nao_conta_como_duplicado(cad, enviar, rodar):
    """CAD-06a: só vale contra item JÁ CONCLUÍDO; um envio anterior com erro não bloqueia o reenvio."""
    arq = pdf_processo(NUM)
    cad.dify.modo = "500"
    enviar(cad.ana, arq)
    rodar()
    assert cad.ItemEnvio.objects.get().status == "erro"
    cad.dify.modo = None
    enviar(cad.ana, arq)
    assert cad.ItemEnvio.objects.order_by("pk").last().status == "na_fila"


def test_arquivo_em_fila_ainda_nao_concluido_nao_e_duplicado(cad, enviar):
    """CAD-06a: item ainda na fila (não concluído) não gera 'Já temos este arquivo'."""
    arq = pdf_processo(NUM)
    enviar(cad.ana, arq)
    enviar(cad.bruno, arq)
    assert list(cad.ItemEnvio.objects.order_by("pk").values_list("status", flat=True)) == ["na_fila", "na_fila"]


def test_lote_misto_ignora_so_o_duplicado(cad, enviar, rodar):
    """CAD-06a: num lote com um arquivo repetido e um novo, só o repetido é ignorado; o novo entra na fila."""
    arq = pdf_processo(NUM, "a")
    novo = pdf_processo(cnj(2)[0], "b")
    enviar(cad.ana, arq)
    rodar()
    enviar(cad.bruno, arq, novo)
    itens = list(cad.ItemEnvio.objects.filter(envio__enviado_por=cad.bruno_u).order_by("pk"))
    assert [i.status for i in itens] == ["ignorado", "na_fila"]


def test_envio_so_de_duplicados_nao_cria_processo_nem_chama_ia(cad, enviar, rodar):
    """CAD-06a: 3 reenvios do mesmo arquivo → 3 ignorados, 1 processo, 1 chamada ao Dify no total."""
    arq = pdf_processo(NUM)
    enviar(cad.ana, arq)
    rodar()
    for c in (cad.bruno, cad.adm, cad.ana):
        enviar(c, arq)
    rodar()
    assert cad.ItemEnvio.objects.filter(status="ignorado").count() == 3 and cad.Processo.objects.count() == 1 and len(cad.dify.chats) == 1


def test_status_json_traz_o_aviso_de_duplicado(cad, enviar, rodar):
    """CAD-23(8b): itens[].aviso com o texto de duplicidade e processo_url do processo existente (auto-refresh da tela do envio)."""
    arq = pdf_processo(NUM)
    enviar(cad.ana, arq)
    rodar()
    original = cad.ItemEnvio.objects.get()
    enviar(cad.bruno, arq)
    novo = cad.ItemEnvio.objects.exclude(pk=original.pk).get()
    j = cad.bruno.get(reverse("juridico:status") + f"?envio={novo.envio_id}").json()
    (it,) = j["itens"]
    assert it["pk"] == novo.pk and it["status"] == "ignorado"
    assert "Já temos este arquivo" in it["aviso"] and "ana.souza@exemplo.test" in it["aviso"] and "Ana Souza" in it["aviso"]
    assert it["processo_url"] == reverse("juridico:processo", kwargs={"pk": original.processo_id})


# ---------------- (b) mesmo número, PDF diferente ----------------

def test_mesmo_numero_atualiza_o_processo_e_avisa_quem_cadastrou(cad, ingerir, ver):
    """CAD-06b: 'Este processo já existia: cadastrado por <nome> (<e-mail>) em DD/MM/AAAA via PDF. Atualizado: <campos>'."""
    item1, p1 = ingerir(cad.ana, NUM, variante="a")
    item2, p2 = ingerir(cad.bruno, NUM, variante="b", campos={"comarca": "Campinas", "valor_causa": "R$ 5.000,00"})
    assert p2.pk == p1.pk and cad.Processo.objects.count() == 1 and item2.acao == "atualizado" and item2.status == "concluido"
    t = ver.texto(cad.bruno.get(_envio_url(item2)))
    pre = "Este processo já existia: cadastrado por Ana Souza (ana.souza@exemplo.test) em " + ver.data_br(p1.criado_em.astimezone())
    assert pre in t and "via PDF." in t and "Atualizado:" in t and "nenhum dado novo" not in t
    assert p2.comarca == "Campinas" and str(p2.valor_causa) == "5000.00"


def test_mesmo_numero_sem_dado_novo(cad, ingerir, ver):
    """CAD-06b: PDF diferente com os MESMOS dados → 'Atualizado: nenhum dado novo.'"""
    ingerir(cad.ana, NUM, variante="a")
    item2, _ = ingerir(cad.bruno, NUM, variante="b")
    t = ver.texto(cad.bruno.get(_envio_url(item2)))
    assert "Este processo já existia: cadastrado por Ana Souza" in t and "nenhum dado novo" in t


def test_aviso_do_numero_igual_quem_cadastrou_e_o_criador_nao_o_ultimo_a_atualizar(cad, ingerir, ver):
    """CAD-06b: 'cadastrado por' = quem CRIOU (criado_por); uma 3ª pessoa vê Ana, não o Bruno que atualizou depois."""
    ingerir(cad.ana, NUM, variante="a")
    ingerir(cad.bruno, NUM, variante="b", campos={"comarca": "Santos"})
    item3, _ = ingerir(cad.adm, NUM, variante="c", campos={"comarca": "Santos", "juizo": "9ª Vara"})
    t = ver.texto(cad.adm.get(_envio_url(item3)))
    assert "cadastrado por Ana Souza (ana.souza@exemplo.test)" in t and "Bruno Lima (bruno.lima@exemplo.test) em" not in t.split("Atualizado")[0]


def test_numero_em_formatos_diferentes_e_o_mesmo(cad, ingerir):
    """CAD-06b: o número pode vir formatado ou só em dígitos do Dify — é o mesmo processo (numero_digitos)."""
    ingerir(cad.ana, NUM, variante="a")
    n2 = cnj(1234)
    _, p = ingerir(cad.bruno, NUM, variante="b", campos={"numero_cnj": n2[1]})
    assert cad.Processo.objects.count() == 1 and p.numero == NUM


def test_numero_valido_e_unico_no_banco(cad, ingerir):
    """Modelo Processo.numero_digitos único quando válido (CAD-06): três PDFs do mesmo número = um processo."""
    for v, c in (("a", cad.ana), ("b", cad.bruno), ("c", cad.adm)):
        ingerir(c, NUM, variante=v)
    assert cad.Processo.objects.filter(numero_digitos=DIG).count() == 1


@pytest.mark.parametrize("via,rotulo", [("cnj", "CNJ"), ("manual", "manual")])
def test_aviso_cita_a_origem_do_cadastro_original(cad, ingerir, ver, via, rotulo):
    """CAD-06b: 'via <PDF|CNJ|manual>' conforme como o processo foi criado."""
    criar_processo(cad, numero=(NUM, DIG), usuario=cad.bruno_u, via=via, adverso_nome="Antigo")
    item, _ = ingerir(cad.ana, NUM)
    t = ver.texto(cad.ana.get(_envio_url(item)))
    assert "Este processo já existia: cadastrado por Bruno Lima (bruno.lima@exemplo.test) em" in t and f"via {rotulo}." in t


def test_numero_colado_no_formulario_cnj_de_processo_existente_mostra_o_aviso_no_item(cad, enviar_cnj, rodar, ver):
    """CAD-06b: número de processo existente enviado pelo CNJ (após confirmar) → item mostra 'Este processo já existia: …'."""
    criar_processo(cad, numero=(NUM, DIG), usuario=cad.bruno_u, via="pdf")
    cad.datajud.fontes[DIG] = {"numeroProcesso": DIG, "tribunal": "TJSP", "dataAjuizamento": "2022-03-15T00:00:00.000Z",
                               "orgaoJulgador": {"nome": "1ª Vara Cível do Foro Central de São Paulo"}, "assuntos": [], "movimentos": []}
    enviar_cnj(cad.ana, NUM, confirmar="1")
    rodar()
    item = cad.ItemEnvio.objects.get()
    t = ver.texto(cad.ana.get(_envio_url(item)))
    assert item.status == "concluido" and item.acao == "atualizado" and cad.Processo.objects.count() == 1
    assert "Este processo já existia: cadastrado por Bruno Lima (bruno.lima@exemplo.test) em" in t and "via PDF." in t


# ---------------- detalhe do processo: cadastrado por + histórico ----------------

def test_detalhe_mostra_cadastrado_por_e_historico_de_envios_com_usuario(cad, ingerir, ver):
    """CAD-06b: 'Cadastrado por <nome> em <data> via <origem>' e o histórico de envios com o usuário de cada um."""
    _, p = ingerir(cad.ana, NUM, variante="a")
    ingerir(cad.bruno, NUM, variante="b", campos={"comarca": "Osasco"})
    ingerir(cad.adm, NUM, variante="c", campos={"comarca": "Osasco", "juizo": "3ª Vara"})
    t = ver.texto(cad.adm.get(reverse("juridico:processo", kwargs={"pk": p.pk})))
    assert re.search(rf"Cadastrado por Ana Souza( \(ana\.souza@exemplo\.test\))? em {ver.data_br(p.criado_em.astimezone())}( \d{{2}}:\d{{2}})? via PDF", t)
    for nome, email in (("Ana Souza", "ana.souza@exemplo.test"), ("Bruno Lima", "bruno.lima@exemplo.test")):
        assert nome in t and email in t
    assert t.count("Ana Souza") >= 2 or t.count("ana.souza@exemplo.test") >= 1
    r = cad.adm.get(reverse("juridico:processo", kwargs={"pk": p.pk}))
    assert len(r.context["envios"]) >= 3


def test_detalhe_do_processo_criado_via_cnj_e_manual(cad, ver):
    """CAD-06b: origem 'CNJ' e 'manual' no cabeçalho 'Cadastrado por …'."""
    for i, (via, rotulo) in enumerate((("cnj", "CNJ"), ("manual", "manual"))):
        p = criar_processo(cad, numero=cnj(300 + i), usuario=cad.bruno_u, via=via)
        t = ver.texto(cad.ana.get(reverse("juridico:processo", kwargs={"pk": p.pk})))
        assert re.search(rf"Cadastrado por Bruno Lima( \(bruno\.lima@exemplo\.test\))? em {ver.data_br(p.criado_em.astimezone())}( \d{{2}}:\d{{2}})? via {rotulo}", t)


# ---------------- (c) dígito verificador inválido ----------------

def test_digito_invalido_nunca_e_o_mesmo_de_outro(cad, ingerir):
    """CAD-06c: número com DV inválido NUNCA é considerado o mesmo: cada PDF cria Processo novo com a pendência exata."""
    ruim = cnj(1234, dv_errado=True)
    _, p1 = ingerir(cad.ana, ruim[0], variante="a")
    _, p2 = ingerir(cad.bruno, ruim[0], variante="b")
    assert p1.pk != p2.pk and cad.Processo.objects.count() == 2
    for p in (p1, p2):
        assert p.numero_valido is False and "Número CNJ com dígito verificador inválido: confira no PDF." in p.pendencias
        assert p.status == "COM_PENDENCIAS"


def test_digito_invalido_nao_mescla_com_o_valido_parecido(cad, ingerir):
    """CAD-06c: o processo válido com o 'mesmo' número (DV certo) não é tocado por um PDF com DV errado."""
    bom, ruim = cnj(1234), cnj(1234, dv_errado=True)
    _, p_bom = ingerir(cad.ana, bom[0], variante="a", campos={"comarca": "Original"})
    _, p_ruim = ingerir(cad.bruno, ruim[0], variante="b", campos={"comarca": "Outra"})
    p_bom.refresh_from_db()
    assert p_ruim.pk != p_bom.pk and p_bom.comarca == "Original"


def test_digito_invalido_nao_consulta_o_datajud(cad, ingerir):
    """CAD-10/06c: a validação no CNJ só roda com numero_valido."""
    _, p = ingerir(cad.ana, cnj(1234, dv_errado=True)[0])
    assert cad.datajud.buscas == [] and p.cnj_validacao == "nao_consultado"


def test_digito_invalido_nao_avisa_duplicidade_de_numero(cad, ingerir, ver):
    """CAD-06c: o item de DV inválido não exibe 'Este processo já existia'."""
    ruim = cnj(1234, dv_errado=True)
    ingerir(cad.ana, ruim[0], variante="a")
    item, _ = ingerir(cad.bruno, ruim[0], variante="b")
    assert "Este processo já existia" not in ver.texto(cad.bruno.get(_envio_url(item))) and item.acao == "novo"


# ---------------- (d) excluído ----------------

def test_numero_de_processo_excluido_e_restaurado_e_atualizado(cad, ingerir, ver):
    """CAD-06d: processo excluído com o mesmo número é restaurado e atualizado, com o aviso 'Este processo tinha sido excluído por…'."""
    _, p = ingerir(cad.ana, NUM, variante="a")
    cad.bruno.post(reverse("juridico:excluir", kwargs={"pk": p.pk}))
    p.refresh_from_db()
    assert p.excluido_em is not None and p.excluido_por == cad.bruno_u
    item, p2 = ingerir(cad.ana, NUM, variante="b", campos={"comarca": "Restaurada"})
    p.refresh_from_db()
    assert p2.pk == p.pk and p.excluido_em is None and p.comarca == "Restaurada" and cad.Processo.objects.count() == 1
    t = ver.texto(cad.ana.get(_envio_url(item)))
    assert re.search(r"Este processo tinha sido excluído por Bruno Lima( \(bruno\.lima@exemplo\.test\))? em " + ver.data_br(timezone.now().astimezone()) + r"( \d{2}:\d{2})? e foi restaurado\.", t)
    assert cad.ana.get(reverse("juridico:processo", kwargs={"pk": p.pk})).status_code == 200


def test_arquivo_de_processo_excluido_ainda_e_duplicado_de_arquivo(cad, enviar, rodar):
    """CAD-06a/d: o item concluído continua valendo para sha256 mesmo se o processo foi excluído (a tela explica)."""
    arq = pdf_processo(NUM)
    enviar(cad.ana, arq)
    rodar()
    p = cad.Processo.objects.get()
    cad.ana.post(reverse("juridico:excluir", kwargs={"pk": p.pk}))
    enviar(cad.bruno, arq)
    assert cad.ItemEnvio.objects.order_by("pk").last().status == "ignorado"
