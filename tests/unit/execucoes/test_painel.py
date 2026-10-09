from datetime import datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.execucoes import demo as demo_exec
from apps.execucoes import painel
from apps.execucoes.models import Execucao
from apps.fluxos import demo

pytestmark = [pytest.mark.modulo("m4"), pytest.mark.django_db]


def _agora(*args):
    return datetime(*args, tzinfo=painel.FUSO)


@pytest.mark.parametrize(
    ("periodo", "n"), [("24h", 24), ("7d", 7), ("30d", 30), ("6m", 26), ("1a", 12)]
)
def test_intervalos_quantidade_e_ultimo_contem_agora(periodo, n):
    agora = _agora(2026, 10, 8, 14, 35)
    passos, fim, anterior = painel.intervalos(periodo, agora)
    assert len(passos) == n
    assert passos[-1][0] <= agora < fim
    assert anterior < passos[0][0]


def test_rotulos_e_semana_na_segunda():
    agora = _agora(2026, 10, 8, 14, 35)  # quinta
    assert painel.intervalos("24h", agora)[0][-1][1] == "14:00"
    assert painel.intervalos("7d", agora)[0][-1][1] == "08/10"
    semanas = painel.intervalos("6m", agora)[0]
    assert semanas[-1][1] == "05/10" and all(p[0].weekday() == 0 for p in semanas)
    assert painel.intervalos("1a", agora)[0][-1][1] == "out/26"
    assert painel.intervalos("1a", agora)[0][0][1] == "nov/25"


def test_variacao_sinais_e_novo():
    assert painel._variacao(20, 10, None)["texto"] == "+100%"
    queda = painel._variacao(2, 10, "menor")
    assert queda["texto"] == "−80%" and queda["bom"] is True and queda["sentido"] == "queda"
    assert painel._variacao(5, 0) == {"texto": "novo", "valor": "", "sentido": "alta", "bom": None}


def test_periodo_invalido_vira_padrao():
    assert painel.periodo_valido("x") == "7d" and painel.periodo_valido("1a") == "1a"


def test_serie_no_fuso_de_sao_paulo(usuario_coordenador):
    agora = timezone.now().astimezone(painel.FUSO)
    ontem_23h30 = (agora - timedelta(days=1)).replace(hour=23, minute=30, second=0, microsecond=0)
    demo_exec.criar_execucao(usuario_coordenador, minutos_atras=0)
    Execucao.objects.update(iniciada_em=ontem_23h30)  # 02:30 UTC do dia seguinte
    dados = painel.montar_painel(usuario_coordenador, "7d")
    com_dado = [x for x in dados["serie"] if x["sucesso"] + x["erro"]]
    assert [x["rotulo"] for x in com_dado] == [f"{ontem_23h30:%d/%m}"]
    assert [i["valor_cru"] for i in dados["indicadores"] if i["chave"] == "execucoes"] == ["1"]


def test_execucao_agora_cai_na_ultima_barra_e_executando_fora_da_taxa(usuario_coordenador):
    demo_exec.criar_execucao(usuario_coordenador, "sucesso", minutos_atras=0)
    demo_exec.criar_execucao(usuario_coordenador, "erro_http", minutos_atras=0)
    em_andamento = demo_exec.criar_execucao(usuario_coordenador, minutos_atras=0)
    Execucao.objects.filter(pk=em_andamento.pk).update(status="executando", finalizada_em=None)
    for periodo in ("24h", "7d", "30d", "6m", "1a"):
        dados = painel.montar_painel(usuario_coordenador, periodo)
        assert dados["serie"][-1]["sucesso"] == 1 and dados["serie"][-1]["erro"] == 1
    valores = {i["chave"]: i for i in dados["indicadores"]}
    assert valores["execucoes"]["valor"] == "3"
    assert valores["taxa_sucesso"]["valor"] == "50%"
    assert valores["execucoes_erro"]["valor"] == "1"


def test_home_vazia_sem_divisao_por_zero(cliente_coordenador):
    r = cliente_coordenador.get(reverse("inicio"))
    assert r.status_code == 200
    assert r.context["sem_dados"] and r.context["sem_dados_periodo"]
    assert {i["chave"]: i["valor"] for i in r.context["indicadores"]}["taxa_sucesso"] == "—"
    assert len(r.context["serie"]) == 7


def test_ranking_e_ultimas_no_escopo(usuario_coordenador, usuario_base, outro_setor):
    from tests.conftest import criar_usuario

    alheio = criar_usuario("c2@exemplo.test", "C2", "Coordenador", setor=outro_setor)
    f1 = demo.criar_fluxo(usuario_coordenador, "F1", "ativo", demo.grafo_exemplo())
    f2 = demo.criar_fluxo(alheio, "F2", "ativo", demo.grafo_exemplo())
    for _ in range(3):
        demo_exec.criar_execucao(usuario_base, fluxo=f1)
    demo_exec.criar_execucao(alheio, fluxo=f2)
    dados = painel.montar_painel(usuario_coordenador, "7d")
    assert [t["pk"] for t in dados["top_fluxos"]] == [f1.pk]
    assert dados["top_fluxos"][0]["url"] == reverse("fluxos:editor", kwargs={"pk": f1.pk})
    assert len(dados["ultimas"]) == 3
    assert dados["por_setor"] is None
    assert all(i["chave"] != "setores_ativos" for i in dados["indicadores"])


def test_falha_vira_estado_de_erro(monkeypatch, usuario_adm):
    def quebrar(*args):
        raise RuntimeError("segredo-do-driver")

    monkeypatch.setattr(painel, "montar_painel", quebrar)
    assert painel.painel_ou_erro(usuario_adm, "7d")["erro_carregar"] is True
