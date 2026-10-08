"""Dados da Home (HOM-01..09): tudo por agregação no banco, número de queries constante.

`montar_painel(usuario, periodo)` devolve o contexto da Home. O escopo vem do motor
(`inicio.ver` para execuções, `fluxos.ver` para fluxos): nunca há número fora do escopo (SET-06).
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Max, Q
from django.db.models.functions import TruncDay, TruncHour, TruncMonth, TruncWeek
from django.urls import reverse
from django.utils import timezone

from apps.contas.models import Setor, Usuario
from apps.contas.permissoes import escopo, papel_de, pode
from apps.fluxos.models import Fluxo

from .apresentacao import ROTULOS_ERRO
from .models import Execucao, ExecucaoNo

logger = logging.getLogger(__name__)

FUSO = ZoneInfo("America/Sao_Paulo")
PERIODO_PADRAO = "7d"
PERIODOS = [
    ("24h", "24 horas", "Últimas 24 horas"),
    ("7d", "7 dias", "Últimos 7 dias"),
    ("30d", "30 dias", "Últimos 30 dias"),
    ("6m", "6 meses", "Últimos 6 meses"),
    ("1a", "1 ano", "Último ano"),
]
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
SEM_SETOR = "Sem setor"
MENOS = "−"


def periodo_valido(valor):
    return valor if valor in {p[0] for p in PERIODOS} else PERIODO_PADRAO


def _soma_meses(ano, mes, delta):
    indice = ano * 12 + (mes - 1) + delta
    return indice // 12, indice % 12 + 1


def intervalos(periodo, agora):
    """Intervalos [(inicio, rotulo)] terminando no atual (inclusive) e o fim da janela (exclusivo).

    Fuso America/Sao_Paulo. Também devolve o início do período anterior equivalente.
    """
    agora = agora.astimezone(FUSO)
    if periodo == "24h":
        hora = agora.replace(minute=0, second=0, microsecond=0)
        inicios = [hora - timedelta(hours=23 - i) for i in range(24)]
        rotulos = [f"{d:%H}:00" for d in inicios]
        fim = hora + timedelta(hours=1)
        anterior = inicios[0] - timedelta(hours=24)
    elif periodo in ("7d", "30d"):
        n = 7 if periodo == "7d" else 30
        hoje = agora.date()
        dias = [hoje - timedelta(days=n - 1 - i) for i in range(n)]
        inicios = [datetime(d.year, d.month, d.day, tzinfo=FUSO) for d in dias]
        rotulos = [f"{d:%d/%m}" for d in dias]
        fim = datetime.combine(hoje + timedelta(days=1), datetime.min.time(), tzinfo=FUSO)
        anterior = datetime.combine(dias[0] - timedelta(days=n), datetime.min.time(), tzinfo=FUSO)
    elif periodo == "6m":
        hoje = agora.date()
        segunda = hoje - timedelta(days=hoje.weekday())
        dias = [segunda - timedelta(weeks=25 - i) for i in range(26)]
        inicios = [datetime(d.year, d.month, d.day, tzinfo=FUSO) for d in dias]
        rotulos = [f"{d:%d/%m}" for d in dias]
        fim = datetime.combine(segunda + timedelta(weeks=1), datetime.min.time(), tzinfo=FUSO)
        anterior = datetime.combine(dias[0] - timedelta(weeks=26), datetime.min.time(), tzinfo=FUSO)
    else:  # 1a
        meses = [_soma_meses(agora.year, agora.month, -11 + i) for i in range(12)]
        inicios = [datetime(a, m, 1, tzinfo=FUSO) for a, m in meses]
        rotulos = [f"{MESES[m - 1]}/{a % 100:02d}" for a, m in meses]
        a, m = _soma_meses(agora.year, agora.month, 1)
        fim = datetime(a, m, 1, tzinfo=FUSO)
        a, m = _soma_meses(*meses[0], -12)
        anterior = datetime(a, m, 1, tzinfo=FUSO)
    return list(zip(inicios, rotulos, strict=True)), fim, anterior


_TRUNCADORES = {
    "24h": TruncHour,
    "7d": TruncDay,
    "30d": TruncDay,
    "6m": TruncWeek,
    "1a": TruncMonth,
}


def _taxa(sucesso, erro):
    finalizadas = sucesso + erro
    return None if finalizadas == 0 else round(sucesso * 100 / finalizadas)


def _variacao(atual, anterior, melhor="maior"):
    """{texto, valor, sentido, bom} comparando com o período anterior; 'novo' sem base (HOM-09)."""
    if anterior in (None, 0):
        sentido = "alta" if atual else "igual"
        return {"texto": "novo", "valor": "", "sentido": sentido, "bom": None}
    pct = round((atual - anterior) * 100 / anterior)
    sentido = "alta" if pct > 0 else "queda" if pct < 0 else "igual"
    bom = None
    if melhor and sentido != "igual":
        bom = (sentido == "alta") == (melhor == "maior")
    texto = f"+{pct}%" if pct > 0 else f"{MENOS}{abs(pct)}%" if pct < 0 else "0%"
    return {"texto": texto, "valor": pct, "sentido": sentido, "bom": bom}


def _indicador(chave, rotulo, valor, cru, variacao=None, dependente_periodo=True):
    return {
        "chave": chave,
        "rotulo": rotulo,
        "valor": valor,
        "valor_cru": cru,
        "variacao": variacao,
        "dependente_periodo": dependente_periodo,
    }


def _segundos(duracao):
    return duracao.total_seconds() if duracao is not None else 0.0


def _duracao_texto(segundos):
    return f"{segundos:.1f}".replace(".", ",") + " s"


def _url_do_fluxo(usuario, fluxo_id, setor_do_fluxo):
    visivel = papel_de(usuario) == "adm" or setor_do_fluxo == usuario.setor_id
    if fluxo_id and visivel and pode(usuario, "fluxos.editar"):
        return reverse("fluxos:editor", kwargs={"pk": fluxo_id})
    return reverse("fluxos:lista")


def _agregados(execucoes, inicio, fim, anterior):
    janela = Q(iniciada_em__gte=inicio, iniciada_em__lt=fim)
    antes = Q(iniciada_em__gte=anterior, iniciada_em__lt=inicio)
    duracao = ExpressionWrapper(F("finalizada_em") - F("iniciada_em"), output_field=DurationField())
    medida = Q(finalizada_em__isnull=False) & ~Q(status=Execucao.EXECUTANDO)
    sucesso, erro = Q(status=Execucao.SUCESSO), Q(status=Execucao.ERRO)
    return execucoes.aggregate(
        total=Count("pk", filter=janela),
        sucesso=Count("pk", filter=janela & sucesso),
        erro=Count("pk", filter=janela & erro),
        duracao=Avg(duracao, filter=janela & medida),
        total_ant=Count("pk", filter=antes),
        sucesso_ant=Count("pk", filter=antes & sucesso),
        erro_ant=Count("pk", filter=antes & erro),
        duracao_ant=Avg(duracao, filter=antes & medida),
    )


def _serie(execucoes, periodo, passos, inicio, fim):
    contagens = {}
    linhas = (
        execucoes.filter(iniciada_em__gte=inicio, iniciada_em__lt=fim)
        .annotate(bloco=_TRUNCADORES[periodo]("iniciada_em", tzinfo=FUSO))
        .values("bloco", "status")
        .annotate(n=Count("pk"))
    )
    for linha in linhas:
        contagens[(linha["bloco"].astimezone(FUSO), linha["status"])] = linha["n"]
    return [
        {
            "rotulo": rotulo,
            "inicio": comeco.isoformat(),
            "sucesso": contagens.get((comeco, Execucao.SUCESSO), 0),
            "erro": contagens.get((comeco, Execucao.ERRO), 0),
        }
        for comeco, rotulo in passos
    ]


def _top_fluxos(usuario, no_periodo):
    linhas = (
        no_periodo.filter(fluxo__isnull=False)
        .values("fluxo_id")
        .annotate(
            nome=Max("fluxo_nome"),
            setor_do_fluxo=Max("fluxo__setor_id"),
            total=Count("pk"),
            sucesso=Count("pk", filter=Q(status=Execucao.SUCESSO)),
            erro=Count("pk", filter=Q(status=Execucao.ERRO)),
        )
        .order_by("-total", "-fluxo_id")[:5]
    )
    resultado = []
    for linha in linhas:
        taxa = _taxa(linha["sucesso"], linha["erro"])
        resultado.append(
            {
                "pk": linha["fluxo_id"],
                "nome": linha["nome"],
                "execucoes": linha["total"],
                "taxa_sucesso": "—" if taxa is None else f"{taxa}%",
                "url": _url_do_fluxo(usuario, linha["fluxo_id"], linha["setor_do_fluxo"]),
            }
        )
    return resultado


def _ultimas(execucoes):
    linhas = execucoes.select_related("executado_por").order_by("-iniciada_em", "-pk")[:10]
    return [
        {
            "pk": e.pk,
            "fluxo_nome": e.fluxo_nome,
            "executado_por_nome": e.executado_por.nome,
            "status": e.status_efetivo,
            "status_rotulo": e.status_rotulo,
            "iniciada_em": e.iniciada_em,
            "url_detalhe": reverse("execucoes:detalhe", kwargs={"pk": e.pk}),
        }
        for e in linhas
    ]


def _erros_por_categoria(no_periodo):
    linhas = (
        ExecucaoNo.objects.filter(
            execucao__in=no_periodo.values("pk"),
            status=ExecucaoNo.ERRO,
            erro_categoria__isnull=False,
        )
        .values("erro_categoria")
        .annotate(total=Count("pk"))
        .order_by("-total", "erro_categoria")
    )
    return [
        {
            "categoria": linha["erro_categoria"],
            "rotulo": ROTULOS_ERRO.get(linha["erro_categoria"], linha["erro_categoria"]),
            "total": linha["total"],
        }
        for linha in linhas
    ]


def _por_setor(no_periodo):
    linhas = (
        no_periodo.values("setor__nome")
        .annotate(total=Count("pk"))
        .order_by("-total", "setor__nome")
    )
    return [
        {"setor": linha["setor__nome"] or SEM_SETOR, "total": linha["total"]} for linha in linhas
    ]


def montar_painel(usuario, periodo):
    periodo = periodo_valido(periodo)
    agora = timezone.now()
    passos, fim, anterior = intervalos(periodo, agora)
    inicio = passos[0][0]
    adm = papel_de(usuario) == "adm"
    base = papel_de(usuario) == "base"
    execucoes = escopo(usuario, Execucao.objects, "inicio.ver")
    no_periodo = execucoes.filter(iniciada_em__gte=inicio, iniciada_em__lt=fim)

    fluxos = escopo(usuario, Fluxo.objects, "fluxos.ver").aggregate(
        ativos=Count("pk", filter=Q(status=Fluxo.ATIVO)),
        rascunhos=Count("pk", filter=Q(status=Fluxo.RASCUNHO)),
    )
    ag = _agregados(execucoes, inicio, fim, anterior)
    tem_execucao = execucoes.exists()
    taxa, taxa_ant = _taxa(ag["sucesso"], ag["erro"]), _taxa(ag["sucesso_ant"], ag["erro_ant"])
    seg, seg_ant = _segundos(ag["duracao"]), _segundos(ag["duracao_ant"])

    indicadores = [
        _indicador(
            "fluxos_ativos",
            "Fluxos ativos",
            str(fluxos["ativos"]),
            str(fluxos["ativos"]),
            None,
            False,
        )
    ]
    if not base:
        indicadores.append(
            _indicador(
                "fluxos_rascunho",
                "Fluxos em rascunho",
                str(fluxos["rascunhos"]),
                str(fluxos["rascunhos"]),
                None,
                False,
            )
        )
    indicadores += [
        _indicador(
            "execucoes",
            "Execuções no período",
            str(ag["total"]),
            str(ag["total"]),
            _variacao(ag["total"], ag["total_ant"], None),
        ),
        _indicador(
            "taxa_sucesso",
            "Taxa de sucesso",
            "—" if taxa is None else f"{taxa}%",
            "" if taxa is None else str(taxa),
            _variacao(taxa or 0, taxa_ant),
        ),
        _indicador(
            "execucoes_erro",
            "Execuções com erro",
            str(ag["erro"]),
            str(ag["erro"]),
            _variacao(ag["erro"], ag["erro_ant"], "menor"),
        ),
        _indicador(
            "duracao_media",
            "Duração média",
            _duracao_texto(seg),
            f"{seg:.1f}",
            _variacao(seg, seg_ant, "menor"),
        ),
    ]
    if not base:
        usuarios = Usuario.objects.filter(is_active=True)
        if not adm:
            usuarios = (
                usuarios.filter(setor_id=usuario.setor_id) if usuario.setor_id else usuarios.none()
            )
        n = usuarios.count()
        indicadores.append(
            _indicador("usuarios_ativos", "Usuários ativos", str(n), str(n), None, False)
        )
    if adm:
        n = Setor.objects.filter(ativo=True).count()
        indicadores.append(
            _indicador("setores_ativos", "Setores ativos", str(n), str(n), None, False)
        )

    pode_criar = pode(usuario, "fluxos.criar")
    return {
        "periodo": periodo,
        "periodo_rotulo": next(p[2] for p in PERIODOS if p[0] == periodo),
        "periodos": [
            {"rotulo": rotulo, "url": f"?periodo={valor}", "ativo": valor == periodo}
            for valor, rotulo, _ in PERIODOS
        ],
        "sem_dados": fluxos["ativos"] + fluxos["rascunhos"] == 0 and not tem_execucao,
        "sem_dados_periodo": ag["total"] == 0,
        "erro_carregar": False,
        "indicadores": indicadores,
        "serie": _serie(execucoes, periodo, passos, inicio, fim),
        "erros": _erros_por_categoria(no_periodo),
        "por_setor": _por_setor(no_periodo) if adm else None,
        "top_fluxos": _top_fluxos(usuario, no_periodo),
        "ultimas": _ultimas(execucoes),
        "pode_criar_fluxo": pode_criar,
        "url_novo_fluxo": reverse("fluxos:lista") if pode_criar else "",
        "url_execucoes": reverse("execucoes:lista"),
    }


def painel_ou_erro(usuario, periodo):
    """Como `montar_painel`, mas uma falha vira o estado de erro (HOM-07), sem vazar o texto."""
    try:
        return montar_painel(usuario, periodo)
    except Exception as erro:
        logger.error("Falha ao montar a Home (%s)", type(erro).__name__)
        return {"erro_carregar": True, "periodo_rotulo": "", "periodos": []}
