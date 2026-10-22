"""T-091: contexto do painel v2 (CAD-24..27) e tipo da audiência (CAD-26)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.juridico import cnj, mescla
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
    assert pks(audiencia="1", status="CADASTRADO") == []
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
    ficha = cliente_adm.get(reverse("juridico:painel"), {"p": p.pk}).context["selecionado"]
    assert ficha["audiencia"] is None and ficha["acao"] == "cadastrado"
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
