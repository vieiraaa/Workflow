"""T-091: contexto do painel v2 (CAD-24..27) e tipo da audiência (CAD-26)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.juridico import apresentacao, cnj, mescla
from apps.juridico.models import (
    Carteira,
    ConfigCadastro,
    Envio,
    ItemEnvio,
    Processo,
)
from apps.juridico.views import _pct

pytestmark = pytest.mark.modulo("m8")


def _numero(seq=1234, j=8, tr=26):
    return cnj.numero_valido_de(seq, 2022, j, tr, 100)


def _processo(seq=1, carteira=None, status="CONFERIR", **campos):
    numero = _numero(seq)
    dados = {
        "tribunal": "TJSP", "comarca": "São Paulo", "juizo": "1ª Vara", "adverso_nome": "Fulano",
        "valor_causa": Decimal("1234.56"), "distribuido_em": "2022-03-15",
    }  # fmt: skip
    dados.update(campos)
    return Processo.objects.create(
        numero=numero, numero_digitos=cnj.so_digitos(numero), numero_valido=True,
        status=status, carteira=carteira, origem_campos={}, **dados,
    )  # fmt: skip


# ---------------------------------------------------------------- CNJ decomposto
def test_cnj_decomposto_valido_com_legendas():
    numero = cnj.numero_valido_de(1234567, 2024, 8, 26, 1)
    saida = cnj.decompor(numero)
    assert saida["valido"] and saida["sigla"] == "TJSP"
    assert [(p["valor"], p["legenda"]) for p in saida["partes"]] == [
        ("1234567", "sequencial"), (numero[8:10], "dígito"), ("2024", "ano"),
        ("8", "estadual"), ("26", "TJSP"), ("0001", "origem"),
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("j", "tr", "justica", "sigla"),
    [
        (8, 7, "estadual", "TJDFT"), (4, 3, "federal", "TRF3"), (5, 2, "trabalho", "TRT2"),
        (6, 26, "eleitoral", "TRE-SP"), (6, 7, "eleitoral", "TRE-DF"),
        (1, 0, "STF", "—"), (3, 0, "STJ", "—"), (7, 0, "militar da União", "—"),
        (9, 13, "militar estadual", "—"), (8, 99, "estadual", "—"),
    ],
)  # fmt: skip
def test_justica_e_sigla_pelo_mapa(j, tr, justica, sigla):
    saida = cnj.decompor(cnj.numero_valido_de(10, 2022, j, tr, 100))
    assert saida["partes"][3]["legenda"] == justica
    assert saida["sigla"] == sigla and saida["partes"][4]["legenda"] == sigla


def test_cnj_invalido_sem_partes():
    assert cnj.decompor("123") == {"valido": False, "partes": [], "sigla": ""}
    ruim = _numero()[:-1] + "9"
    assert cnj.decompor(ruim) == {"valido": False, "partes": [], "sigla": ""}


def test_pct_half_up():
    assert [_pct(1, 8), _pct(1, 3), _pct(2, 3), _pct(0, 0), _pct(5, 8), _pct(8, 8)] == [
        13, 33, 67, 0, 63, 100,
    ]  # fmt: skip


# ---------------------------------------------------------------- tipo da audiência
@pytest.mark.parametrize(
    ("frase", "tipo"),
    [
        ("Audiência de conciliação designada para {d}, às 14:30.", "conciliação"),
        (
            "Audiência de Instrução e   Julgamento redesignada para {d} às 9h15.",
            "instrução e julgamento",
        ),
        ("audiência una marcada para {d}, às 10:00", "una"),
        ("Audiência de mediação foi designada para {d}, às 11:00", "mediação"),
        ("Audiência designada para {d}, às 11:00", ""),
    ],
)  # fmt: skip
def test_tipo_gravado_so_o_complemento_em_minusculas(frase, tipo):
    futura = (timezone.now() + timedelta(days=5)).astimezone()
    processo = Processo(observacoes=frase.format(d=f"{futura:%d/%m/%Y}"), origem_campos={})
    mescla.atualizar_audiencia(processo)
    assert processo.proxima_audiencia is not None
    assert processo.proxima_audiencia_tipo == tipo


def test_tipo_manual_nao_e_sobrescrito_pela_extracao():
    futura = (timezone.now() + timedelta(days=5)).astimezone()
    processo = Processo(
        observacoes=f"Audiência de conciliação designada para {futura:%d/%m/%Y}, às 14:00.",
        origem_campos={"proxima_audiencia_tipo": "manual"},
        proxima_audiencia_tipo="una",
    )
    mescla.atualizar_audiencia(processo)
    assert processo.proxima_audiencia_tipo == "una" and processo.proxima_audiencia is not None


# ---------------------------------------------------------------- contexto do painel
@pytest.mark.django_db
def test_contexto_do_painel_v2(cliente_adm, usuario_adm):
    ConfigCadastro.obter()
    ativos = Carteira.objects.get(nome="Ativos")
    ailos = Carteira.objects.get(nome="Ailos")
    Carteira.objects.filter(nome="Volvo").update(ativa=False)
    _processo(1, ativos, "CADASTRADO")
    _processo(2, ativos, "CONFERIR")
    _processo(3, ailos, "COM_PENDENCIAS", juizo="")
    _processo(4, None, "CONFERIR")
    excluido = _processo(5, ativos)
    Processo.objects.filter(pk=excluido.pk).update(excluido_em=timezone.now())
    envio = Envio.objects.create(origem="pdf", enviado_por=usuario_adm)
    for status, etapa, resolvido in (
        ("na_fila", None, False),
        ("processando", None, False),
        ("erro", "Leitura do PDF", False),
        ("erro", "Envio do PDF", False),
        ("erro", "Leitura do PDF", True),
        ("concluido", "IA (Dify)", False),
    ):
        ItemEnvio.objects.create(envio=envio, status=status, etapa_erro=etapa, resolvido=resolvido)

    contexto = cliente_adm.get(reverse("juridico:painel")).context
    fluxo = contexto["fluxo"]
    assert fluxo == {
        "em_leitura": 2, "erros_leitura": 2, "url_erros": reverse("juridico:erros"),
        "com_pendencias": 1, "conferir": 2, "cadastrados": 1, "total": 4, "pct_cadastrados": 25,
    }  # fmt: skip
    nomes = [c["nome"] for c in contexto["clientes"]]
    assert nomes[0] == "Todos" and nomes[-1] == "Outros" and "Volvo" not in nomes
    por_nome = {c["nome"]: c for c in contexto["clientes"]}
    assert por_nome["Todos"]["pk"] is None and por_nome["Todos"]["ativo"] is True
    assert (por_nome["Ativos"]["total"], por_nome["Ativos"]["cadastrados"]) == (2, 1)
    assert por_nome["Ativos"]["pct"] == 50 and por_nome["Ailos"]["pct"] == 0
    assert por_nome["Outros"]["pk"] == "outros" and por_nome["Outros"]["total"] == 1
    assert por_nome["Outros"]["url"] == "?carteira=outros"
    assert por_nome["Ativos"]["url"] == f"?carteira={ativos.pk}"
    assert contexto["filtro_audiencia"] is False and len(contexto["atualizado_em"]) == 5


@pytest.mark.django_db
def test_urls_dos_clientes_preservam_status_e_audiencia_e_ativo(cliente_adm):
    ativos = Carteira.objects.get(nome="Ativos")
    _processo(1, ativos)
    contexto = cliente_adm.get(
        reverse("juridico:painel"),
        {"status": "CONFERIR", "audiencia": "1", "carteira": str(ativos.pk), "p": "9", "page": "2"},
    ).context
    por_nome = {c["nome"]: c for c in contexto["clientes"]}
    assert por_nome["Ativos"]["ativo"] and not por_nome["Todos"]["ativo"]
    for c in contexto["clientes"]:
        assert "status=CONFERIR" in c["url"] and "audiencia=1" in c["url"]
        assert "p=" not in c["url"] and "page=" not in c["url"]
    assert contexto["filtro_audiencia"] is True


@pytest.mark.django_db
def test_filtro_audiencia_combina_em_and(cliente_adm):
    agora = timezone.now()
    com = _processo(1, proxima_audiencia=agora + timedelta(days=3), status="CONFERIR")
    _processo(2, proxima_audiencia=agora - timedelta(days=3))
    _processo(3)
    url = reverse("juridico:painel")
    pks = lambda **q: [p.pk for p in cliente_adm.get(url, q).context["processos"]]  # noqa: E731
    assert pks(audiencia="1") == [com.pk]
    assert pks(audiencia="1", aba="cadastrados") == []
    assert len(pks()) == 3


@pytest.mark.django_db
def test_ficha_selecionada(cliente_adm, usuario_adm):
    agora = timezone.now()
    p = _processo(
        1, Carteira.objects.get(nome="Ativos"), "COM_PENDENCIAS", juizo="", valor_causa=None,
        proxima_audiencia=agora + timedelta(days=3), proxima_audiencia_tipo="conciliação",
        adverso_cpf_cnpj="529.982.247-25", fase_atual="RECURSAL",
    )  # fmt: skip
    envio = Envio.objects.create(origem="pdf", enviado_por=usuario_adm)
    ItemEnvio.objects.create(envio=envio, processo=p, status="concluido", numero_informado="x")
    sem_arquivo = ItemEnvio.objects.get(processo=p)
    ficha = cliente_adm.get(reverse("juridico:painel"), {"p": p.pk}).context["selecionado"]
    assert ficha["acao"] == "pendencias" and ficha["url_pdf"] is None  # item CNJ não conta
    assert ficha["obrig_ok"] == 5
    assert [(o["campo"], o["ok"]) for o in ficha["obrigatorios"]] == [
        ("numero", True), ("tribunal", True), ("comarca", True), ("juizo", False),
        ("adverso_nome", True), ("valor_causa", False), ("distribuido_em", True),
    ]  # fmt: skip
    assert ficha["cnj"]["valido"] and ficha["cnj"]["sigla"] == "TJSP"
    audiencia = ficha["audiencia"]
    futura = timezone.localtime(p.proxima_audiencia)
    assert audiencia["dia"] == f"{futura:%d}" and audiencia["hora"] == f"{futura:%H:%M}"
    assert audiencia["tipo"] == "Audiência de conciliação" and audiencia["local"] == "São Paulo"
    assert audiencia["mes_ano"].split(" ")[1] == str(futura.year)
    assert ficha["processo"]["cpf_cnpj_mascarado"] == "***.982.247-**"
    assert ficha["processo"]["fase"] == "Recursal" and ficha["cnj_situacao"] == "nao_consultado"
    # PDF: o item mais recente COM arquivo
    for indice in (1, 2):
        ItemEnvio.objects.create(
            envio=envio, processo=p, status="concluido", arquivo=f"juridico/2026/10/{indice}.pdf"
        )
    ultimo = ItemEnvio.objects.exclude(arquivo="").order_by("-pk").first()
    ItemEnvio.objects.create(envio=envio, processo=p, status="concluido", numero_informado="y")
    ficha = cliente_adm.get(reverse("juridico:painel"), {"p": p.pk}).context["selecionado"]
    assert ficha["url_pdf"] == reverse("juridico:pdf", kwargs={"pk": ultimo.pk})
    assert sem_arquivo.pk != ultimo.pk


@pytest.mark.django_db
def test_ficha_sem_audiencia_passada_e_acao_por_status(cliente_adm):
    passada = timezone.now() - timedelta(days=1)
    p = _processo(1, status="CADASTRADO", proxima_audiencia=passada)
    painel = reverse("juridico:painel")
    ficha = cliente_adm.get(painel, {"p": p.pk, "aba": "cadastrados"}).context["selecionado"]
    assert ficha["audiencia"] is None and ficha["acao"] == "cadastrado"
    # D-063: ?p= de processo de outra aba não abre a ficha
    assert cliente_adm.get(painel, {"p": p.pk}).context["selecionado"] is None
    q = _processo(2, status="CONFERIR")
    assert (
        cliente_adm.get(reverse("juridico:painel"), {"p": q.pk}).context["selecionado"]["acao"]
        == "conferir"
    )


@pytest.mark.django_db
def test_painel_queries_constantes(cliente_adm, django_assert_max_num_queries):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    _processo(1)
    cliente_adm.get(reverse("juridico:painel"))  # aquece (cria a config, sessão...)
    with CaptureQueriesContext(connection) as poucos:
        cliente_adm.get(reverse("juridico:painel"))
    for i in range(2, 30):
        _processo(i, Carteira.objects.get(nome="Ativos"))
    with CaptureQueriesContext(connection) as muitos:
        cliente_adm.get(reverse("juridico:painel"))
    assert len(muitos) == len(poucos)


@pytest.mark.django_db
def test_tipo_da_audiencia_editavel_na_conferencia_vira_manual(cliente_adm):
    p = _processo(1)
    url = reverse("juridico:processo", kwargs={"pk": p.pk})
    cliente_adm.post(url, {"proxima_audiencia_tipo": "  Mediação  "})
    p.refresh_from_db()
    assert p.proxima_audiencia_tipo == "mediação"
    assert p.origem_campos["proxima_audiencia_tipo"] == "manual"
    resposta = cliente_adm.post(url, {"proxima_audiencia_tipo": "x" * 81})
    assert resposta.status_code == 200 and "Máximo de 80 caracteres." in resposta.content.decode()


def test_tipo_sem_audiencia_no_texto_nao_e_zerado_pela_recalculo():
    processo = Processo(origem_campos={}, proxima_audiencia_tipo="mediação")
    mescla.atualizar_audiencia(processo)  # nada no texto e sem data antes
    assert processo.proxima_audiencia_tipo == "mediação"
    processo.proxima_audiencia = timezone.now() + timedelta(days=2)  # data de extração antiga
    mescla.atualizar_audiencia(processo)  # a audiência saiu do texto: tipo sai junto
    assert processo.proxima_audiencia is None and processo.proxima_audiencia_tipo == ""


@pytest.mark.django_db
def test_post_sem_o_campo_do_tipo_nao_o_altera(cliente_adm):
    p = _processo(1)
    Processo.objects.filter(pk=p.pk).update(proxima_audiencia_tipo="mediação")
    url = reverse("juridico:processo", kwargs={"pk": p.pk})
    cliente_adm.post(url, {"comarca": "Outra"})
    p.refresh_from_db()
    assert p.proxima_audiencia_tipo == "mediação" and p.comarca == "Outra"
    cliente_adm.post(url, {"proxima_audiencia_tipo": ""})
    p.refresh_from_db()
    assert p.proxima_audiencia_tipo == ""


# ---------------------------------------------------------------- selos e filtro CNJ (D-052)
@pytest.mark.parametrize(
    ("cnj_validacao", "status", "esperado"),
    [
        ("confere", "CONFERIR", [("ok", "✓ DataJud")]),
        ("divergente", "CONFERIR", [("conf", "! DataJud diverge")]),  # D-056: vale o PDF
        ("nao_encontrado", "CONFERIR", [("neutro", "? DataJud não encontrou")]),
        ("falhou", "CONFERIR", [("erro", "× DataJud falhou")]),
        ("nao_consultado", "CONFERIR", [("vazio", "DataJud não consultado")]),
        ("confere", "CADASTRADO", [("ok", "✓ DataJud"), ("ok", "✓ Espaider")]),
        (
            "nao_consultado",
            "CADASTRADO",
            [("vazio", "DataJud não consultado"), ("ok", "✓ Espaider")],
        ),
    ],
)
def test_selos_de_integracao(cnj_validacao, status, esperado):
    """D-052/D-054 (opção C): texto por extenso; DataJud sempre, Espaider só quando lançado."""
    p = Processo(cnj_validacao=cnj_validacao, status=status)
    selos = apresentacao.selos_integracao(p)
    assert [(s["estado"], s["texto"]) for s in selos] == esperado
    assert all(s["titulo"] for s in selos)


@pytest.mark.django_db
def test_cartao_mostra_os_selos_e_o_filtro_cnj_conta_e_filtra(cliente_adm):
    _processo(1, cnj_validacao="confere")
    _processo(2, cnj_validacao="confere", status="CADASTRADO")
    _processo(3, cnj_validacao="divergente", status="COM_PENDENCIAS")
    _processo(4)  # não consultado: "DataJud não consultado" em cinza
    resposta = cliente_adm.get(reverse("juridico:painel"))
    # D-063: a contagem do CNJ é da aba (Em processamento; o cadastrado está na outra aba)
    filtros = {f["valor"]: f for f in resposta.context["filtros_cnj"]}
    assert filtros[""]["total"] == 3 and filtros[""]["ativo"]
    assert (filtros["confere"]["total"], filtros["divergente"]["total"]) == (1, 1)
    assert filtros["nao_consultado"]["total"] == 1 and filtros["falhou"]["total"] == 0
    corpo = resposta.content.decode()
    assert "CNJ: confere (DataJud)" in corpo
    assert "! DataJud diverge" in corpo and "DataJud não consultado" in corpo
    assert "✓ DataJud" in corpo
    cadastrados = cliente_adm.get(reverse("juridico:painel"), {"aba": "cadastrados"})
    filtros_cad = {f["valor"]: f for f in cadastrados.context["filtros_cnj"]}
    assert filtros_cad[""]["total"] == 1 and filtros_cad["confere"]["total"] == 1
    corpo = cadastrados.content.decode()
    assert "Espaider: cadastrado" in corpo and "✓ Espaider" in corpo
    filtrada = cliente_adm.get(reverse("juridico:painel") + filtros["confere"]["url"])
    assert {p["cnj_situacao"] for p in filtrada.context["processos"]} == {"confere"}
    assert filtrada.context["titulo_lista"].endswith("· Confere")
    ativo = next(f for f in filtrada.context["filtros_cnj"] if f["ativo"])
    assert ativo["valor"] == "confere"


@pytest.mark.django_db
def test_filtro_cnj_respeita_o_status_escolhido(cliente_adm):
    _processo(1, cnj_validacao="confere")
    _processo(2, cnj_validacao="confere", status="CADASTRADO")
    _processo(3, cnj_validacao="confere", status="COM_PENDENCIAS")
    resposta = cliente_adm.get(reverse("juridico:painel"), {"status": "COM_PENDENCIAS"})
    filtros = {f["valor"]: f for f in resposta.context["filtros_cnj"]}
    assert filtros["confere"]["total"] == 1 and "status=COM_PENDENCIAS" in filtros["confere"]["url"]
    # ...e a aba escolhida (D-063)
    resposta = cliente_adm.get(reverse("juridico:painel"), {"aba": "cadastrados"})
    filtros = {f["valor"]: f for f in resposta.context["filtros_cnj"]}
    assert filtros["confere"]["total"] == 1 and "aba=cadastrados" in filtros["confere"]["url"]


# ---------------------------------------------------------------- filtro "Entrada" (D-061)
def _entrou_ha(processo, dias):
    quando = timezone.now() - timedelta(days=dias)
    Processo.objects.filter(pk=processo.pk).update(criado_em=quando)
    return timezone.localdate(quando)


@pytest.mark.django_db
def test_filtro_entrada_lista_os_dias_e_filtra(cliente_adm):
    hoje = [_processo(seq=10 + i) for i in range(3)]
    ontem = _processo(seq=20)
    antigo = _processo(seq=21)
    dia_ontem, dia_antigo = _entrou_ha(ontem, 1), _entrou_ha(antigo, 5)
    url = reverse("juridico:painel")

    contexto = cliente_adm.get(url).context
    opcoes = contexto["opcoes_entrada"]
    assert [(o["rotulo"].split(" ·")[0], o["total"]) for o in opcoes] == [
        ("Todas", 5), ("Hoje", 3), ("Ontem", 1), (apresentacao.data(dia_antigo), 1)
    ]  # fmt: skip
    assert contexto["entrada_rotulo"] == "Todas" and opcoes[0]["ativo"]

    filtrado = cliente_adm.get(url, {"entrada": timezone.localdate().isoformat()}).context
    assert {p["pk"] for p in filtrado["processos"]} == {p.pk for p in hoje}
    assert filtrado["entrada_rotulo"].startswith("Hoje") and "entrada" in filtrado["titulo_lista"]
    so_ontem = cliente_adm.get(url, {"entrada": dia_ontem.isoformat()}).context["processos"]
    assert [p["pk"] for p in so_ontem] == [ontem.pk]


@pytest.mark.django_db
def test_filtro_entrada_combina_com_status_e_aceita_dia_sem_processo(cliente_adm):
    _processo(seq=30, status="CONFERIR")
    _processo(seq=31, status="CADASTRADO")
    url = reverse("juridico:painel")
    hoje = timezone.localdate().isoformat()
    contexto = cliente_adm.get(url, {"entrada": hoje, "status": "CADASTRADO"}).context
    assert contexto["processos"].paginator.count == 1
    assert next(o for o in contexto["opcoes_entrada"] if o["valor"] == hoje)["total"] == 1
    vazio = cliente_adm.get(url, {"entrada": "2020-01-02"})
    assert vazio.context["processos"].paginator.count == 0
    assert vazio.context["entrada_rotulo"] == "02/01/2020"
    assert 'data-estado="filtrado"' in vazio.content.decode()


@pytest.mark.django_db
@pytest.mark.parametrize("valor", ["ontem", "2026-13-40", "<script>", "9" * 50])
def test_filtro_entrada_invalido_e_ignorado(cliente_adm, valor):
    _processo(seq=40)
    contexto = cliente_adm.get(reverse("juridico:painel"), {"entrada": valor}).context
    assert contexto["filtros"]["entrada"] == "" and contexto["processos"].paginator.count == 1


@pytest.mark.django_db
def test_ficha_mostra_quando_o_processo_entrou(cliente_adm):
    p = _processo(seq=50)
    resposta = cliente_adm.get(reverse("juridico:painel"), {"p": p.pk})
    entrada = apresentacao.data_hora(Processo.objects.get(pk=p.pk).criado_em)
    assert resposta.context["selecionado"]["processo"]["entrada"] == entrada
    assert f"entrou em {entrada}" in resposta.content.decode()


@pytest.mark.django_db
def test_etapas_e_busca_mantem_o_filtro_de_entrada(cliente_adm):
    _processo(seq=60)
    hoje = timezone.localdate().isoformat()
    resposta = cliente_adm.get(reverse("juridico:painel"), {"entrada": hoje})
    html = resposta.content.decode()
    # D-063: a busca leva o dia num campo oculto; as etapas (chips) e as abas, na URL
    assert html.count(f'<input type="hidden" name="entrada" value="{hoje}">') == 1
    assert all(f"entrada={hoje}" in e["url"] for e in resposta.context["etapas"])
    assert all(
        f"entrada={hoje}" in a["url"]
        for a in resposta.context["abas"]
        if a["chave"] != "aprovacoes"
    )
