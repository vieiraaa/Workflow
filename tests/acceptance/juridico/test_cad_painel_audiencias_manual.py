"""Aceite M8 · painel, audiências, exclusão e cadastro manual (CAD-16, CAD-18 máscara/escape, CAD-19, CAD-20, CAD-21; TEL-27/34/35)."""
import re
from datetime import datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from .conftest import cnj, criar_processo, fonte_datajud

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

PAINEL = "juridico:painel"


def _painel(c, **q):
    return c.get(reverse(PAINEL), q)


def _num(i):
    return cnj(9000 + i)


# ---------------- painel (CAD-16) ----------------

def test_painel_vazio_mostra_a_mensagem(cad, ver):
    """CAD-16: 'Nenhum processo cadastrado ainda. Envie os PDFs ou cadastre pelo número.'"""
    r = _painel(cad.ana)
    t = ver.texto(r)
    assert r.status_code == 200 and "Nenhum processo cadastrado ainda" in t and "Envie os PDFs ou cadastre pelo número." in t


def test_painel_estrutura_barra_superior_e_contadores(cad, ver):
    """CAD-16 (barra superior continua) + CAD-24 (contadores agora na esteira): título 'Painel de Processos', Menu, 'Audiências (N)', Atualizar;
    contagens em 'N processos extraídos', '33% já cadastrados no Espaider' e nas três etapas (antes: 'N processos · N com pendências · N cadastrados')."""
    criar_processo(cad, numero=_num(1))
    criar_processo(cad, numero=_num(2), status="COM_PENDENCIAS", pendencias=["Verificar: Juízo"])
    criar_processo(cad, numero=_num(3), status="CADASTRADO")
    r = _painel(cad.ana)
    t = ver.texto(r)
    for trecho in ("Painel de Processos", "Menu", "Audiências (0)", "Atualizar"):
        assert trecho in t, trecho
    f = r.context["fluxo"]
    assert (f["com_pendencias"], f["conferir"], f["cadastrados"], f["total"]) == (1, 1, 1, 3)
    assert re.search(r"\b3 processos extraídos\b", t) and "33% já cadastrados no Espaider" in t
    for numero, nome in ((1, "Com pendências"), (1, "Conferir"), (1, "Cadastrado")):
        assert re.search(rf"\b{numero}\b\s*{nome}", t), nome


def test_menu_do_painel_tem_as_entradas_da_spec_e_config_so_para_adm(cad, ver):
    """CAD-16: Menu = Enviar PDFs, Cadastrar pelo nº (CNJ), Cadastro manual, Log de erros e desempenho, Envios, Configuração (Adm)."""
    t_ana = ver.texto(_painel(cad.ana))
    for e in ("Enviar PDFs para leitura", "Cadastrar pelo nº (CNJ)", "Cadastro manual de processo", "Log de erros e desempenho", "Envios"):
        assert e in t_ana, e
    assert "Configuração" not in t_ana.split("Painel de Processos")[1][:3000] or reverse("juridico:config") not in ver.html(_painel(cad.ana))
    assert reverse("juridico:config") in ver.html(_painel(cad.adm))
    for rota in ("juridico:enviar_pdfs", "juridico:enviar_cnj", "juridico:processo_novo", "juridico:erros", "juridico:envios"):
        assert reverse(rota) in ver.html(_painel(cad.ana))


def test_contexto_do_painel_segue_cad_19(cad):
    """CAD-19: resumo {total, com_pendencias, conferir, cadastrados, na_fila, erros}, ultimos_envios, processos, filtros, carteiras,
    aviso_datajud, atualizar_auto, url_status."""
    criar_processo(cad, numero=_num(1))
    criar_processo(cad, numero=_num(2), status="CADASTRADO")
    ctx = _painel(cad.adm).context
    for k in ("resumo", "ultimos_envios", "processos", "filtros", "carteiras", "aviso_datajud", "atualizar_auto", "url_status"):
        assert k in ctx, k
    assert {"total", "com_pendencias", "conferir", "cadastrados", "na_fila", "erros"} <= set(ctx["resumo"])
    assert ctx["resumo"]["total"] == 2 and ctx["resumo"]["conferir"] == 1 and ctx["resumo"]["cadastrados"] == 1
    assert {"status", "carteira", "tribunal", "cnj", "q", "ordem"} <= set(ctx["filtros"])
    assert ctx["url_status"] == reverse("juridico:status")


def test_tres_colunas_clientes_com_contagem_e_filtro(cad, ver):
    """CAD-16 (clientes filtram a lista, título 'Processos · <carteira> (N)') + CAD-24 (formato dos clientes): 'Todos', cada carteira ativa e 'Outros' com
    'cadastrados/total' (antes: 'Todos (5)', 'Ativos (3)'…)."""
    for i in range(3):
        criar_processo(cad, numero=_num(i), carteira=cad.carteiras["Ativos"])
    criar_processo(cad, numero=_num(10), carteira=cad.carteiras["Ailos"])
    criar_processo(cad, numero=_num(11), carteira=None)
    r = _painel(cad.ana)
    t = ver.texto(r)
    for rotulo in ("CLIENTES", "Todos", "Ativos", "Ailos", "Outros", "Processos"):
        assert rotulo.lower() in t.lower(), rotulo
    assert re.search(r"Todos\s*0\s*/\s*5", t) and re.search(r"Ativos\s*0\s*/\s*3", t) and re.search(r"Ailos\s*0\s*/\s*1", t) and re.search(r"Outros\s*0\s*/\s*1", t)
    por = {c["nome"]: c for c in r.context["clientes"]}
    assert (por["Todos"]["total"], por["Ativos"]["total"], por["Ailos"]["total"], por["Outros"]["total"]) == (5, 3, 1, 1)
    assert len(_painel(cad.ana, carteira=cad.carteiras["Ativos"].pk).context["processos"]) == 3
    assert "Processos · Ativos (3)" in ver.texto(_painel(cad.ana, carteira=cad.carteiras["Ativos"].pk))


def test_carteira_inativa_nao_aparece_na_coluna_de_clientes(cad, ver):
    """CAD-16: só carteiras ATIVAS na coluna (modelo Carteira.ativa)."""
    cad.Carteira.objects.filter(pk=cad.carteiras["Volvo"].pk).update(ativa=False)
    t = ver.texto(_painel(cad.ana))
    assert "Volvo" not in t and "Ailos" in t


def test_cartao_do_processo_tem_numero_adverso_documento_mascarado_e_linha_de_dados(cad, ver):
    """CAD-16/18: cartão com número, adverso + CPF/CNPJ MASCARADO, 'carteira · comarca · valor', chip de status, Excluir."""
    p = criar_processo(cad, numero=_num(1), adverso_nome="Maria Adversa", adverso_cpf_cnpj="123.456.789-09", comarca="Campinas", valor_causa="1234.56")
    t = ver.texto(_painel(cad.ana))
    assert p.numero in t and "Maria Adversa" in t and "***.456.789-**" in t and "123.456.789-09" not in t
    assert "Ativos" in t and "Campinas" in t and "1.234,56" in t and "conferir" in t.lower() and "Excluir" in t


def test_mascara_cnpj_e_varios_documentos_e_tamanho_estranho(cad, ver):
    """CAD-23(7): CNPJ → **.345.678/0001-** ; vários separados por '; ' um a um; outro tamanho → •••."""
    criar_processo(cad, numero=_num(1), adverso_nome="Empresa A", adverso_cpf_cnpj="12.345.678/0001-95")
    criar_processo(cad, numero=_num(2), adverso_nome="Dupla B", adverso_cpf_cnpj="123.456.789-09; 98.765.432/0001-10")
    criar_processo(cad, numero=_num(3), adverso_nome="Curto C", adverso_cpf_cnpj="12345")
    h = ver.texto(_painel(cad.ana))
    assert "**.345.678/0001-**" in h and "12.345.678/0001-95" not in h
    assert "***.456.789-**; **.765.432/0001-**" in h and "98.765.432/0001-10" not in h
    assert "•••" in h and "12345" not in h


def test_documento_completo_so_no_detalhe(cad, ver):
    """CAD-18: CPF/CNPJ completo só no detalhe do processo."""
    p = criar_processo(cad, adverso_cpf_cnpj="123.456.789-09")
    assert "123.456.789-09" in ver.texto(cad.ana.get(reverse("juridico:processo", kwargs={"pk": p.pk})))
    assert "123.456.789-09" not in ver.html(_painel(cad.ana))


def test_datas_sempre_dd_mm_aaaa_nunca_iso(cad, ver):
    """CAD-16 (datas DD/MM/AAAA continua; nunca ISO nem serial do Excel) — agora verificada onde a data aparece no v2: ficha (Distribuído em), chip de
    audiência da lista, folha da audiência, 'Cadastrado no Espaider em' e faixa do CNJ (antes: data de citação no bloco de detalhes)."""
    quando = timezone.now() + timedelta(days=4)
    p = criar_processo(cad, distribuido_em="2022-03-15", data_citacao="2022-04-20", proxima_audiencia=quando, cnj_validacao="confere", cnj_consultado_em=timezone.now())
    t = ver.texto(_painel(cad.ana, p=p.pk))
    assert "15/03/2022" in t and "2022-03-15" not in t and "2022-04-20" not in t and "44635" not in t
    assert f"{timezone.localtime(quando):%d/%m/%Y %H:%M}" in t                     # chip de audiência na lista
    c = criar_processo(cad, numero=cnj(8888), status="CADASTRADO", cadastrado_espaider_em=timezone.now(), cadastrado_espaider_por=cad.ana_u)
    assert f"Cadastrado no Espaider em {timezone.localtime(c.cadastrado_espaider_em):%d/%m/%Y}" in ver.texto(_painel(cad.ana, p=c.pk))
    assert "15/03/2022" in ver.texto(cad.ana.get(reverse("juridico:processo", kwargs={"pk": p.pk})))


def test_painel_painel_de_detalhes_do_selecionado(cad, ver):
    """CAD-16 (selecionado = ?p=<pk>, padrão o 1º da lista; 'Marcar cadastrado no Espaider' e 'Editar') + CAD-25 (a coluna 3 agora é a ficha: grupos
    'Partes' e 'Processo'; antes: PARTES, PROCESSO, OPERAÇÕES VINCULADAS, CLASSIFICAÇÃO, PEDIDOS, VALIDAÇÃO NO CNJ, CONTROLE — os demais grupos seguem na conferência TEL-28)."""
    p1 = criar_processo(cad, numero=_num(1), adverso_nome="Primeiro", operacoes_vinculadas="OP-777", pedidos="Pedido Alfa", natureza="Cível Alfa")
    p2 = criar_processo(cad, numero=_num(2), adverso_nome="Segundo", pedidos="Pedido Beta", natureza="Cível Beta")
    r = _painel(cad.ana, p=p2.pk)
    t = ver.texto(r)
    for g in ("Partes", "Processo"):
        assert g in t, g
    assert "Marcar cadastrado no Espaider" in t and "Editar" in t
    assert r.context["selecionado"]["processo"].pk == p2.pk and "Pedido Alfa" not in t
    assert _painel(cad.ana).context["selecionado"]["processo"].pk == p2.pk  # padrão = 1º da lista (atualizado mais recente)
    assert reverse("juridico:processo", kwargs={"pk": p2.pk}) in ver.html(r) and p1.pk != p2.pk
    conf = ver.texto(cad.ana.get(reverse("juridico:processo", kwargs={"pk": p1.pk})))   # o que saiu da ficha continua na conferência
    for rotulo in ("Operações vinculadas", "Pedidos", "Controle"):
        assert rotulo.lower() in conf.lower(), rotulo
    assert "OP-777" in conf and "Pedido Alfa" in conf


def test_busca_por_numero_adverso_documento_comarca_e_empresa(cad, ver):
    """CAD-16: ?q= (número só dígitos, adverso, CPF/CNPJ, comarca, empresa)."""
    a = criar_processo(cad, numero=_num(1), adverso_nome="Zeferino Unico", adverso_cpf_cnpj="111.222.333-44", comarca="Ubatuba", empresa="Empresa Lunar")
    criar_processo(cad, numero=_num(2), adverso_nome="Outro Nome", adverso_cpf_cnpj="555.666.777-88", comarca="Santos", empresa="Empresa Solar")

    def n(q):
        return ver.pks(_painel(cad.ana, q=q).context["processos"])
    assert n(a.numero_digitos) == [a.pk] and n(a.numero) == [a.pk]
    assert n("zeferino") == [a.pk] and n("ZEFERINO UNICO") == [a.pk]
    assert n("111.222.333-44") == [a.pk] and n("11122233344") == [a.pk]
    assert n("ubatuba") == [a.pk] and n("lunar") == [a.pk] and n("inexistente-xyz") == []


def test_filtros_status_e_cnj_e_ordem(cad, ver):
    """CAD-16: ?status=, ?cnj=, ?ordem= (atualizado padrão, numero, distribuido)."""
    a = criar_processo(cad, numero=_num(3), status="CONFERIR", cnj_validacao="confere", distribuido_em="2020-01-01")
    b = criar_processo(cad, numero=_num(1), status="COM_PENDENCIAS", cnj_validacao="divergente", distribuido_em="2023-01-01")
    c = criar_processo(cad, numero=_num(2), status="CADASTRADO", cnj_validacao="nao_encontrado", distribuido_em="2021-01-01")

    def pks(**q):
        return ver.pks(_painel(cad.ana, **q).context["processos"])
    assert pks(status="COM_PENDENCIAS") == [b.pk] and pks(status="CADASTRADO") == [c.pk] and pks(status="CONFERIR") == [a.pk]
    assert pks(cnj="divergente") == [b.pk] and pks(cnj="confere") == [a.pk]
    assert pks(ordem="numero") == sorted([a.pk, b.pk, c.pk], key=lambda k: {a.pk: a.numero_digitos, b.pk: b.numero_digitos, c.pk: c.numero_digitos}[k])
    assert pks(ordem="distribuido") in ([b.pk, c.pk, a.pk], [a.pk, c.pk, b.pk])
    assert pks() == [x.pk for x in cad.Processo.objects.order_by("-atualizado_em")]


def test_paginacao_de_25_e_queries_constantes(cad):
    """CAD-16: paginação 25 e número de queries constante (não cresce com o volume)."""
    for i in range(30):
        criar_processo(cad, numero=_num(i))
    r = _painel(cad.ana)
    assert len(r.context["processos"]) == 25 and len(_painel(cad.ana, pagina=2).context["processos"]) == 5
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    with CaptureQueriesContext(connection) as q30:
        _painel(cad.ana)
    for i in range(30, 60):
        criar_processo(cad, numero=_num(i))
    with CaptureQueriesContext(connection) as q60:
        _painel(cad.ana)
    assert len(q60) == len(q30)


def test_excluidos_nao_aparecem_nem_contam(cad):
    """CAD-21: excluído some de todas as listas e contagens."""
    criar_processo(cad, numero=_num(1))
    criar_processo(cad, numero=_num(2), excluido_em=timezone.now(), excluido_por=cad.adm_u)
    ctx = _painel(cad.ana).context
    assert ctx["resumo"]["total"] == 1 and len(ctx["processos"]) == 1


def test_xss_texto_do_pdf_e_dado_escapado_em_tela(cad, ver):
    """CAD-18/SEG-13: texto vindo do PDF/IA é DADO — escapado no painel, no detalhe e na lista de audiências."""
    xss = "<script>alert('x')</script><img src=x onerror=alert(1)>"
    p = criar_processo(cad, adverso_nome=xss, comarca=xss, pedidos=xss, observacoes=xss, empresa=xss)
    for r in (_painel(cad.ana), cad.ana.get(reverse("juridico:processo", kwargs={"pk": p.pk})), _painel(cad.ana, p=p.pk)):
        h = ver.html(r)
        assert "<script>alert" not in h and "<img src=x" not in h and "&lt;script&gt;" in h


def test_painel_com_fila_atualiza_sozinho(cad, enviar, rodar, ver):
    """CAD-16/19: com itens do usuário na fila, atualizar_auto=True e url_status apontando para o JSON; sem fila, False."""
    from .conftest import pdf_processo
    assert _painel(cad.ana).context["atualizar_auto"] is False
    enviar(cad.ana, pdf_processo(cnj(1)[0]))
    r = _painel(cad.ana)
    assert r.context["atualizar_auto"] is True and r.context["resumo"]["na_fila"] == 1 and reverse("juridico:status") in ver.html(r)
    assert _painel(cad.bruno).context["atualizar_auto"] is False  # a fila é DO usuário
    rodar()
    assert _painel(cad.ana).context["atualizar_auto"] is False


def test_status_json_chaves_e_contagens(cad, enviar):
    """CAD-23 (8b): {total, com_pendencias, conferir, cadastrados, na_fila, erros, em_andamento}."""
    from .conftest import pdf_processo
    criar_processo(cad, numero=_num(1), status="CADASTRADO")
    criar_processo(cad, numero=_num(2), status="COM_PENDENCIAS", pendencias=["x"])
    enviar(cad.ana, pdf_processo(cnj(1)[0]))
    j = cad.ana.get(reverse("juridico:status")).json()
    assert {"total", "com_pendencias", "conferir", "cadastrados", "na_fila", "erros", "em_andamento"} <= set(j)
    assert j["total"] == 2 and j["cadastrados"] == 1 and j["com_pendencias"] == 1 and j["na_fila"] == 1 and j["em_andamento"] is True
    assert cad.bruno.get(reverse("juridico:status")).json()["em_andamento"] is False


# ---------------- audiências (CAD-20) ----------------

def _futuro(dias, hora="14:30"):
    d = timezone.localdate() + timedelta(days=dias)
    return d, hora


def test_audiencia_extraida_do_texto_do_pdf_sem_ia(cad, ingerir):
    """CAD-20: 'audiência ... (designada|marcada|redesignada) para DD/MM/AAAA[,] (às HH:MM | HHhMM)' → proxima_audiencia."""
    d1, _ = _futuro(10)
    d2, _ = _futuro(20)
    obs = (f"Audiência de conciliação designada para {d1:%d/%m/%Y} às 14:30. "
           f"Audiência de instrução redesignada para {d2:%d/%m/%Y}, 09h15.")
    _, p = ingerir(cad.ana, cnj(1)[0], campos={"observacoes": obs})
    esperado = timezone.make_aware(datetime(d1.year, d1.month, d1.day, 14, 30))
    assert p.proxima_audiencia == esperado


@pytest.mark.parametrize("trecho,hh,mm", [("audiência de instrução marcada para {d} às 08:05", 8, 5), ("Audiência redesignada para {d}, 16h40", 16, 40),
                                          ("AUDIÊNCIA una designada para {d} às 10:00", 10, 0)])
def test_variantes_do_padrao_de_audiencia(cad, ingerir, trecho, hh, mm):
    """CAD-20: designada/marcada/redesignada; 'às HH:MM' ou 'HHhMM'; vírgula opcional."""
    d, _ = _futuro(5)
    _, p = ingerir(cad.ana, cnj(50 + hh)[0], variante=str(hh), campos={"observacoes": trecho.format(d=f"{d:%d/%m/%Y}")})
    assert timezone.localtime(p.proxima_audiencia).replace(tzinfo=None) == datetime(d.year, d.month, d.day, hh, mm)


def test_audiencia_vale_a_futura_mais_proxima_e_ignora_passadas(cad, ingerir):
    """CAD-20: vale a data FUTURA mais próxima; as passadas não contam."""
    passada, _ = _futuro(-30)
    perto, _ = _futuro(7)
    longe, _ = _futuro(60)
    obs = (f"Audiência designada para {longe:%d/%m/%Y} às 10:00. Audiência marcada para {passada:%d/%m/%Y} às 09:00. "
           f"Audiência redesignada para {perto:%d/%m/%Y} às 11:00.")
    _, p = ingerir(cad.ana, cnj(2)[0], campos={"observacoes": obs})
    assert timezone.localtime(p.proxima_audiencia).date() == perto


def test_so_audiencias_passadas_ou_ausentes_ficam_sem_data(cad, ingerir):
    """CAD-20: nenhuma futura → proxima_audiencia vazia."""
    passada, _ = _futuro(-3)
    _, p = ingerir(cad.ana, cnj(3)[0], campos={"observacoes": f"Audiência designada para {passada:%d/%m/%Y} às 10:00."})
    assert p.proxima_audiencia is None
    _, q = ingerir(cad.ana, cnj(4)[0], campos={"observacoes": "Sem nada de audiência aqui."})
    assert q.proxima_audiencia is None


def test_audiencia_tambem_vem_dos_andamentos(cad, ingerir):
    """CAD-20: extração nas observações E nos andamentos (PDF/CNJ)."""
    d, _ = _futuro(12)
    movs = [{"data": "01/01/2023", "evento": f"Audiência designada para {d:%d/%m/%Y} às 13:00"}]
    _, p = ingerir(cad.ana, cnj(5)[0], campos={"ultimas_movimentacoes": movs})
    assert p.proxima_audiencia is not None and timezone.localtime(p.proxima_audiencia).date() == d


def test_audiencia_editavel_na_conferencia_vira_manual_e_pdf_nao_cala(cad):
    """CAD-20: editável na conferência (vira manual)."""
    p = criar_processo(cad)
    d, _ = _futuro(9)
    cad.ana.post(reverse("juridico:processo", kwargs={"pk": p.pk}), {"proxima_audiencia": f"{d:%Y-%m-%d}T15:45"})
    p.refresh_from_db()
    assert timezone.localtime(p.proxima_audiencia).replace(tzinfo=None) == datetime(d.year, d.month, d.day, 15, 45)
    assert p.origem_campos["proxima_audiencia"] == "manual"


def test_botao_audiencias_conta_de_hoje_em_diante(cad, ver):
    """CAD-20/16: 'Audiências (N)' = processos com audiência de hoje em diante (passadas não entram)."""
    criar_processo(cad, numero=_num(1), proxima_audiencia=timezone.now() + timedelta(days=3))
    criar_processo(cad, numero=_num(2), proxima_audiencia=timezone.now() + timedelta(days=30))
    criar_processo(cad, numero=_num(3), proxima_audiencia=timezone.now() - timedelta(days=3))
    criar_processo(cad, numero=_num(4), proxima_audiencia=None)
    assert "Audiências (2)" in ver.texto(_painel(cad.ana))


def test_botao_de_audiencias_fica_vermelho_nos_proximos_7_dias(cad, ver):
    """CAD-16 (botão 'Audiências (N)' vermelho) → CAD-24: agora é o filtro ?audiencia=1 (aria-pressed) e a lista TEL-34 fica no Menu. Antes: classe de alerta
    no botão com audiência em ≤ 7 dias; depois: href ?audiencia=1, aria-pressed false/true, contagem N e link 'Lista de audiências' no Menu."""
    criar_processo(cad, numero=_num(1), proxima_audiencia=timezone.now() + timedelta(days=30))
    criar_processo(cad, numero=_num(2), proxima_audiencia=timezone.now() + timedelta(days=2))
    criar_processo(cad, numero=_num(3), proxima_audiencia=timezone.now() - timedelta(days=2))

    def botao(h):
        m = re.search(r'<a\b[^>]*href="\?audiencia=1"[^>]*>', h)
        return m.group(0) if m else ""
    sem = ver.html(_painel(cad.ana))
    com_r = _painel(cad.ana, audiencia=1)
    assert botao(sem) and 'aria-pressed="false"' in botao(sem) and "Audiências (2)" in ver.texto(_painel(cad.ana))
    assert len(com_r.context["processos"]) == 2 and com_r.context["filtro_audiencia"] is True
    assert re.search(r'<(?:a|button)\b[^>]*aria-pressed="true"[^>]*>(?:(?!</(?:a|button)>).)*Audiências \(2\)', ver.html(com_r), re.S)
    assert reverse("juridico:audiencias") in sem and "Lista de audiências" in ver.texto(_painel(cad.ana))


def test_tela_de_audiencias_lista_ordenada_por_data_com_link(cad, ver):
    """TEL-34/CAD-20: número, adverso, comarca, data/hora e link, ordenada por data; passadas e excluídos fora."""
    agora = timezone.now()
    b = criar_processo(cad, numero=_num(2), adverso_nome="Segundo Adverso", comarca="Osasco", proxima_audiencia=agora + timedelta(days=9))
    a = criar_processo(cad, numero=_num(1), adverso_nome="Primeiro Adverso", comarca="Santos", proxima_audiencia=agora + timedelta(days=2))
    criar_processo(cad, numero=_num(3), adverso_nome="Passado Adverso", proxima_audiencia=agora - timedelta(days=2))
    criar_processo(cad, numero=_num(4), adverso_nome="Excluido Adverso", proxima_audiencia=agora + timedelta(days=1), excluido_em=agora, excluido_por=cad.adm_u)
    r = cad.ana.get(reverse("juridico:audiencias"))
    t = ver.texto(r)
    assert t.index("Primeiro Adverso") < t.index("Segundo Adverso") and "Passado Adverso" not in t and "Excluido Adverso" not in t
    for x in (a, b):
        assert x.numero in t and reverse("juridico:processo", kwargs={"pk": x.pk}) in ver.html(r)
    assert "Santos" in t and "Osasco" in t and f"{timezone.localtime(a.proxima_audiencia):%d/%m/%Y %H:%M}" in t


def test_tela_de_audiencias_vazia(cad, ver):
    """TEL-34: estado vazio sem erro."""
    r = cad.ana.get(reverse("juridico:audiencias"))
    assert r.status_code == 200 and "Audiências" in ver.texto(r)


def test_chip_de_audiencia_no_cartao(cad, ver):
    """CAD-16/20: chip de audiência (data e hora) no cartão do processo."""
    d = timezone.now() + timedelta(days=4)
    criar_processo(cad, numero=_num(1), proxima_audiencia=d)
    assert f"{timezone.localtime(d):%d/%m/%Y %H:%M}" in ver.texto(_painel(cad.ana))


# ---------------- exclusão (CAD-21) ----------------

def test_excluir_exige_post_confirma_texto_e_some(cad, ver):
    """CAD-21: POST → exclusão lógica, mensagem 'Processo excluído.'; texto de confirmação na tela; some do painel."""
    p = criar_processo(cad, numero=_num(1))
    assert f"Excluir o processo {p.numero}? Ele some do painel; o histórico fica guardado." in ver.html_cru(_painel(cad.ana))
    r = cad.ana.post(reverse("juridico:excluir", kwargs={"pk": p.pk}), follow=True)
    p.refresh_from_db()
    assert "Processo excluído." in ver.texto(r) and p.excluido_em is not None and p.excluido_por == cad.ana_u
    assert cad.Processo._base_manager.filter(pk=p.pk).exists() and p.numero not in ver.texto(_painel(cad.ana))


def test_excluidos_na_configuracao_e_restaurar_so_adm(cad, ver):
    """CAD-21: Adm vê os excluídos (juridico:excluidos) e restaura; o processo volta às listas."""
    p = criar_processo(cad, numero=_num(1))
    cad.ana.post(reverse("juridico:excluir", kwargs={"pk": p.pk}))
    assert p.numero in ver.texto(cad.adm.get(reverse("juridico:excluidos")))
    assert cad.ana.post(reverse("juridico:restaurar", kwargs={"pk": p.pk})).status_code == 403
    r = cad.adm.post(reverse("juridico:restaurar", kwargs={"pk": p.pk}))
    p.refresh_from_db()
    assert r.status_code == 302 and p.excluido_em is None and p.numero in ver.texto(_painel(cad.ana))


def test_excluir_processo_nao_apaga_o_historico_de_envios(cad, ingerir):
    """CAD-21: 'o histórico fica guardado' — o item do envio continua existindo."""
    item, p = ingerir(cad.ana, cnj(1)[0])
    cad.ana.post(reverse("juridico:excluir", kwargs={"pk": p.pk}))
    assert cad.ItemEnvio.objects.filter(pk=item.pk).exists() and cad.Processo._base_manager.filter(pk=p.pk).exists()


# ---------------- cadastro manual (CAD-21, TEL-35) ----------------

def test_cadastro_manual_valido(cad, ver):
    """CAD-21: criado_via=manual, criado_por=quem criou, numero formatado + digitos + válido, consulta o CNJ ao salvar, status recalculado."""
    n, d = cnj(4321)
    cad.datajud.fontes[d] = fonte_datajud(d)
    r = cad.ana.post(reverse("juridico:processo_novo"), {"numero": d, "carteira": cad.carteiras["Ativos"].pk, "adverso_nome": "Manual Adverso",
                                                         "tribunal": "TJSP", "comarca": "São Paulo", "juizo": "1ª Vara", "valor_causa": "10,00",
                                                         "distribuido_em": "2022-03-15"})
    p = cad.Processo.objects.get()
    assert r.status_code == 302 and (p.numero, p.numero_digitos, p.numero_valido) == (n, d, True)
    assert p.criado_via == "manual" and p.criado_por == cad.ana_u and p.origem_campos["adverso_nome"] == "manual"
    assert p.cnj_validacao == "confere" and len(cad.datajud.buscas) == 1 and p.status == "CONFERIR"
    assert r["Location"] == reverse("juridico:processo", kwargs={"pk": p.pk}) or r["Location"].startswith("/juridico/")


@pytest.mark.parametrize("numero", ["", "123", "abc", "0000000-00.0000.0.00.0000x"])
def test_cadastro_manual_numero_obrigatorio_e_valido(cad, ver, numero):
    """CAD-21: número obrigatório e válido (dígito verificador) → senão 'Número CNJ inválido.'; nada criado."""
    r = cad.ana.post(reverse("juridico:processo_novo"), {"numero": numero, "adverso_nome": "X"})
    assert r.status_code == 200 and cad.Processo.objects.count() == 0
    assert ("Número CNJ inválido." in ver.texto(r)) or ("Este campo é obrigatório." in ver.texto(r) and numero == "")


def test_cadastro_manual_dv_errado_e_recusado(cad, ver):
    """CAD-21/06c: número com DV errado → 'Número CNJ inválido.'"""
    r = cad.ana.post(reverse("juridico:processo_novo"), {"numero": cnj(1234, dv_errado=True)[0]})
    assert r.status_code == 200 and "Número CNJ inválido." in ver.texto(r) and cad.Processo.objects.count() == 0


def test_cadastro_manual_de_numero_existente_nao_cria_e_avisa_com_link(cad, ver):
    """CAD-21/06b: número que já existe → não cria; mostra 'Este processo já existia: cadastrado por <nome> (<e-mail>) em … via <origem>' + link."""
    existente = criar_processo(cad, numero=cnj(1234), usuario=cad.bruno_u, via="pdf")
    r = cad.ana.post(reverse("juridico:processo_novo"), {"numero": cnj(1234)[1], "adverso_nome": "Tentativa"})
    t = ver.texto(r)
    assert r.status_code == 200 and cad.Processo.objects.count() == 1
    assert "Este processo já existia: cadastrado por Bruno Lima (bruno.lima@exemplo.test) em" in t and "via PDF" in t
    assert reverse("juridico:processo", kwargs={"pk": existente.pk}) in ver.html(r)


def test_cadastro_manual_de_numero_excluido_avisa_sem_criar_duplicata(cad):
    """CAD-06d/21: número igual a processo excluído não cria segundo registro."""
    criar_processo(cad, numero=cnj(1234), excluido_em=timezone.now(), excluido_por=cad.adm_u)
    cad.ana.post(reverse("juridico:processo_novo"), {"numero": cnj(1234)[1], "adverso_nome": "Tentativa"})
    assert cad.Processo._base_manager.filter(numero_digitos=cnj(1234)[1]).count() == 1


def test_cadastro_manual_so_com_acesso(cad):
    """cadastro.editar: sem acesso → 403; anônimo → login."""
    assert cad.carla.post(reverse("juridico:processo_novo"), {"numero": cnj(1)[1]}).status_code == 403
    r = cad.anonimo.post(reverse("juridico:processo_novo"), {"numero": cnj(1)[1]})
    assert r.status_code == 302 and reverse("login") in r["Location"] and cad.Processo.objects.count() == 0
