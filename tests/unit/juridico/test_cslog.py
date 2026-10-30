"""D-064: exportação do processo.csv para o CSLOG (de-para, tela, gerar e baixar)."""

import csv
import io
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.urls import reverse

from apps.juridico import cnj, cslog
from apps.juridico.models import ConfigCadastro, ExportacaoCslog, Processo

pytestmark = pytest.mark.modulo("m8")

NUMERO = "0805704-94.2026.8.19.0211"  # exemplo do pedido (TJRJ)


def _fake(**campos):
    base = {
        "numero": NUMERO, "numero_valido": True, "tipo_acao": "", "condicao": "Réu",
        "pedidos": "", "assuntos_cnj": "", "adverso_cpf_cnpj": "202.659.317-54",
        "operacoes_vinculadas": "", "estado": "", "comarca": "Rio de Janeiro",
        "juizo": "25º Juizado Especial Cível", "distribuido_em": date(2026, 8, 25),
        "valor_causa": Decimal("12538.66"), "advogado_adverso_nome": "RONAN 241777/RJ",
    }  # fmt: skip
    base.update(campos)
    return SimpleNamespace(**base)


def _processo(seq=1, **campos):
    numero = cnj.numero_valido_de(seq, 2026, 8, 19, 211)
    dados = {
        "adverso_nome": "Fulana de Tal", "adverso_cpf_cnpj": "20265931754", "condicao": "Réu",
        "tipo_acao": "Ação Declaratória de Inexistência de Débito", "comarca": "Rio de Janeiro",
        "juizo": "2º Juizado", "distribuido_em": date(2026, 8, 25), "valor_causa": Decimal("10"),
    }  # fmt: skip
    dados.update(campos)
    return Processo.objects.create(
        numero=numero, numero_digitos=cnj.so_digitos(numero), numero_valido=True, **dados
    )


# ---------------------------------------------------------------- de-para (puro)
@pytest.mark.parametrize(
    ("classe", "condicao", "esperado"),
    [
        ("Ação Declaratória de Inexistência de Débito c/c Indenização", "Réu", "P258"),
        ("Ação de Indenização por Danos Morais", "Ré", "P8"),
        ("Apelação Cível", "Apelado", "S25"),
        ("Agravo de Instrumento", "Agravado", "S0"),
        ("Recurso Inominado", "", "S30"),
        ("Cumprimento de Sentença", "Executado", "P159"),
        ("Cumprimento de Sentença", "Exequente", "P158"),
        ("Execução de Título Extrajudicial", "Exequente", "P4"),
        ("Execução de Título Extrajudicial", "Executado", "P118"),
        ("Embargos à Execução", "Embargante", "P102"),
        ("Busca e Apreensão", "Autor", "P1"),
        ("Busca e Apreensão", "Réu", "P1"),  # só existe Pró: usa o que há
        ("Ação de Cobrança", "Réu", "P161"),
        ("Ação de Cobrança", "Autor", "P105"),
        ("Ação Revisional de Contrato", "Réu", "P7"),
        ("Superendividamento", "Requerido", "P195"),
        ("Coisa nenhuma", "Réu", "P161"),
        ("Coisa nenhuma", "Autor", "P160"),
    ],
)
def test_sugere_tipo_pela_classe_e_polo(classe, condicao, esperado):
    assert cslog.sugerir_tipo(_fake(tipo_acao=classe, condicao=condicao))[0] == esperado


def test_classe_generica_olha_os_pedidos_e_sem_polo_vale_contra():
    p = _fake(
        tipo_acao="Procedimento Comum Cível",
        condicao="",
        pedidos="declarar a inexistência do débito e condenar em danos morais; cobrança indevida",
    )
    chave, motivo = cslog.sugerir_tipo(p)
    assert chave == "P258" and "pedidos" in motivo and "polo não informado" in motivo


def test_polo_pela_condicao():
    assert cslog.polo("Réu") == cslog.CONTRA and cslog.polo("Requerida") == cslog.CONTRA
    assert cslog.polo("Autor") == cslog.PRO and cslog.polo("Exequente") == cslog.PRO
    assert cslog.polo("Terceiro interessado") is None and cslog.polo("") is None


def test_base_de_tipos_sem_chave_repetida_e_grupos_na_ordem():
    assert len(cslog.POR_CHAVE) == len(cslog.TIPOS) == 70
    assert [g for g, _ in cslog.grupos_para_select()] == ["Contra", "Outros", "Pró", "Subprocesso"]
    assert cslog.rotulo("S0") == "0 · Agravo de Instrumento" and cslog.rotulo("P0") == (
        "0 · Reint. de Posse"
    )


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("202.659.317-54", "202.659.317-54"),
        ("20265931754", "202.659.317-54"),
        ("12345678000190", "12.345.678/0001-90"),
        ("CPF 202.659.317-54 e 111.222.333-44", "202.659.317-54"),
        ("não informado", ""),
        ("", ""),
    ],
)
def test_documento_com_mascara(texto, esperado):
    assert cslog.documento(texto) == esperado


def test_linha_do_processo_csv_segue_o_de_para():
    p = _fake(operacoes_vinculadas="144812523, MP709766015246300066")
    linha = cslog.linha(p, "P258", "JOAO.VIEIRA")
    assert list(linha) == list(cslog.COLUNAS) and len(linha) == 25
    assert linha["CPF - AUTOR DA ACAO"] == "202.659.317-54"
    assert linha["CONTRATO"] == "144812523"
    assert linha["CONTRATOS"] == "144812523, MP709766015246300066"
    assert linha["NUM_PROCESSO_UNICA"] == NUMERO
    assert linha["VARA"] == linha["ESFERA"] == "25º Juizado Especial Cível"
    assert linha["COMARCA"] == linha["FORO"] == "Rio de Janeiro"
    assert linha["UF"] == "RJ"  # sem estado no cadastro: vem do número (8.19)
    assert linha["TIPO_ACAO"] == "258"
    assert linha["ADV_PARTE_CONTRARIA"] == "RONAN 241777/RJ"
    assert linha["ADVOGADO_LOGIN"] == "MAGDA.LOGIN" and linha["FILIAL"] == "Curitiba"
    assert linha["ESTAGIARIO_LOGIN"] == "JOAO.VIEIRA"
    assert linha["DATA_DISTRIBUICAO"] == "25/08/2026" and linha["VALOR_CAUSA"] == "12538,66"
    em_branco = (
        "OPERACAO", "NUM_PROCESSO", "NUMERO_PASTA", "LOCALIZADOR_CPF/CNPJ", "STATUS_FINALIZADO",
        "ID_JUIZ", "NOME_JUIZ", "VENC_PARC_AJUIZ", "PLATAFORMA",
    )  # fmt: skip
    assert all(linha[c] == "" for c in em_branco)


def test_sem_contrato_repete_o_cpf_e_contratos_fica_vazio():
    linha = cslog.linha(_fake(estado="pr"), "P8", "X")
    assert linha["CONTRATO"] == "202.659.317-54" and linha["CONTRATOS"] == ""
    assert linha["UF"] == "PR"


def test_csv_com_ponto_e_virgula_uma_linha_por_processo_e_sem_formula():
    p = _fake(advogado_adverso_nome="=HYPERLINK(1)\nlinha 2", juizo="Vara; Cível")
    texto = cslog.gerar_csv([cslog.linha(p, "P8", "X")])
    linhas = list(csv.reader(io.StringIO(texto), delimiter=";"))
    assert linhas[0] == list(cslog.COLUNAS) and len(linhas) == 2
    assert linhas[1][cslog.COLUNAS.index("ADV_PARTE_CONTRARIA")] == "HYPERLINK(1) linha 2"
    assert linhas[1][cslog.COLUNAS.index("VARA")] == "Vara; Cível"
    assert texto.endswith("\r\n")


def test_bloqueio_e_faltando():
    assert cslog.bloqueio(_fake()) == "" and cslog.faltando(_fake()) == []
    assert cslog.bloqueio(_fake(numero_valido=False)) == "Sem número CNJ válido"
    assert cslog.bloqueio(_fake(adverso_cpf_cnpj="")) == "Sem CPF/CNPJ do autor"
    assert cslog.faltando(_fake(comarca="", valor_causa=None)) == ["comarca", "valor da causa"]


# ---------------------------------------------------------------- tela, gerar e baixar
@pytest.mark.django_db
def test_tela_lista_sem_csv_com_tipo_sugerido(cliente_adm):
    p = _processo()
    _processo(seq=2, adverso_cpf_cnpj="")
    resposta = cliente_adm.get(reverse("juridico:cslog"))
    assert resposta.status_code == 200
    assert "juridico/cslog.html" in [t.name for t in resposta.templates]
    linhas = {i.pk: i for i in resposta.context["processos"]}
    assert linhas[p.pk].tipo == "P258" and linhas[p.pk].bloqueio == ""
    assert len(linhas) == 2 and resposta.context["pode_gerar"] is True
    html = resposta.content.decode()
    assert f'name="tipo_{p.pk}"' in html and "Sem CPF/CNPJ do autor" in html


@pytest.mark.django_db
def test_gerar_grava_exportacao_baixa_e_sai_de_sem_csv(cliente_adm, usuario_adm):
    p1, p2 = _processo(seq=1), _processo(seq=2, adverso_cpf_cnpj="")
    resposta = cliente_adm.post(
        reverse("juridico:cslog_gerar"), {"ids": [p1.pk, p2.pk], f"tipo_{p1.pk}": "S25"}
    )
    assert resposta.status_code == 302
    exportacao = ExportacaoCslog.objects.get()
    assert exportacao.quantidade == 1 and list(exportacao.processos.all()) == [p1]
    assert exportacao.gerado_por == usuario_adm
    p1.refresh_from_db()
    assert p1.cslog_tipo == "S25"
    linhas = list(csv.DictReader(io.StringIO(exportacao.conteudo), delimiter=";"))
    assert linhas[0]["TIPO_ACAO"] == "25"
    assert linhas[0]["ESTAGIARIO_LOGIN"] == usuario_adm.email.split("@")[0].upper()

    tela = cliente_adm.get(reverse("juridico:cslog"))
    assert tela.context["baixar_url"].endswith(f"/cslog/{exportacao.pk}/baixar/")
    assert [i.pk for i in tela.context["processos"]] == [p2.pk]  # p1 saiu de "Sem CSV"
    gerados = cliente_adm.get(reverse("juridico:cslog") + "?situacao=gerados").context
    assert [i.pk for i in gerados["processos"]] == [p1.pk] and gerados["processos"][0].tipo == "S25"
    assert cliente_adm.get(reverse("juridico:cslog")).context["baixar_url"] == ""  # uma vez só

    arquivo = cliente_adm.get(reverse("juridico:cslog_baixar", kwargs={"pk": exportacao.pk}))
    assert arquivo.status_code == 200 and "attachment" in arquivo["Content-Disposition"]
    assert arquivo.content.startswith("﻿".encode()) and b"NUM_PROCESSO_UNICA" in arquivo.content
    p1.refresh_from_db()
    assert p1.status == Processo.CONFERIR  # gerar o CSV não conclui nada


@pytest.mark.django_db
def test_gerar_sem_selecao_ou_so_bloqueados_nao_grava(cliente_adm):
    bloqueado = _processo(adverso_cpf_cnpj="")
    cliente_adm.post(reverse("juridico:cslog_gerar"), {})
    cliente_adm.post(reverse("juridico:cslog_gerar"), {"ids": [bloqueado.pk, "x", 999999]})
    assert not ExportacaoCslog.objects.exists()


@pytest.mark.django_db
def test_tipo_invalido_no_post_usa_o_sugerido(cliente_adm):
    p = _processo()
    cliente_adm.post(reverse("juridico:cslog_gerar"), {"ids": [p.pk], f"tipo_{p.pk}": "X9"})
    p.refresh_from_db()
    assert p.cslog_tipo == "P258"


@pytest.mark.django_db
def test_acesso_por_papel(cliente_anonimo, cliente_base, usuario_base, cliente_coordenador):
    _processo()
    assert cliente_anonimo.get(reverse("juridico:cslog")).status_code == 302
    assert cliente_base.get(reverse("juridico:cslog")).status_code == 403  # setor sem acesso
    assert cliente_base.post(reverse("juridico:cslog_gerar"), {}).status_code == 403
    ConfigCadastro.obter().setores_com_acesso.add(usuario_base.setor)
    resposta = cliente_base.get(reverse("juridico:cslog"))
    assert resposta.status_code == 200 and resposta.context["pode_gerar"] is True
    assert cliente_base.get(reverse("juridico:cslog_baixar", kwargs={"pk": 999})).status_code == 404
    assert (
        cliente_anonimo.get(reverse("juridico:cslog_baixar", kwargs={"pk": 1})).status_code == 302
    )


@pytest.mark.django_db
def test_menu_marca_so_o_item_cslog(cliente_adm):
    menu = cliente_adm.get(reverse("juridico:cslog")).context["menu"]
    ativos = [i["chave"] for i in menu if i["ativo"]]
    assert ativos == ["cslog"]
    menu = cliente_adm.get(reverse("juridico:painel")).context["menu"]
    assert [i["chave"] for i in menu if i["ativo"]] == ["juridico"]


@pytest.mark.django_db
def test_paginacao_e_busca_com_queries_constantes(cliente_adm, django_assert_max_num_queries):
    for seq in range(1, 56):
        _processo(seq=seq, adverso_nome=f"Pessoa {seq}")
    with django_assert_max_num_queries(20):
        contexto = cliente_adm.get(reverse("juridico:cslog")).context
    assert len(contexto["processos"]) == 50 and contexto["page_obj"].paginator.num_pages == 2
    busca = cliente_adm.get(reverse("juridico:cslog") + "?q=Pessoa 7").context
    assert {i.autor for i in busca["processos"]} == {"Pessoa 7"}
