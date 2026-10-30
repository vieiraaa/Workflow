"""Aprovações dos itens que chegaram do n8n (D-048, TEL-37) e a chave da API (Configuração)."""

import json
import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Max, Q, Sum
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.nucleo import listagem
from apps.nucleo.entrada import limpar_texto

from . import apresentacao, cnj, recebimentos
from .models import Carteira, ChamadaApi, Processo, Recebimento
from .views import CadastroMixin, Item, SoPost, _carteiras_choices

ABA = "aprovacoes"  # Aprovações é uma aba do painel (D-063, CAD-28)

STATUS_PADRAO = Recebimento.PENDENTE
TODOS = "todos"
ROTULOS_STATUS = {
    Recebimento.PENDENTE: "Pendentes",
    Recebimento.APROVADO: "Aprovados",
    Recebimento.DESCARTADO: "Descartados",
    TODOS: "Todos",
}


def _uuid(valor):
    try:
        return str(uuid.UUID(valor)) if valor else ""
    except ValueError:
        return ""


def _ids(request):
    return [int(v) for v in request.POST.getlist("ids") if v.isascii() and v.isdigit()][:500]


def url_aba(consulta=""):
    """Painel na aba Aprovações, com a querystring (só os parâmetros conhecidos da aba)."""
    pares = [("aba", ABA)] + [
        (k, v) for k, v in parse_qsl(consulta) if k in ("status", "q", "pagina", "lote")
    ]
    return f"{reverse('juridico:painel')}?{urlencode(pares)}"


def _voltar(request):
    """De volta à aba com os mesmos filtros."""
    return redirect(url_aba(request.POST.get("consulta", "")))


def _decisao(r):
    if r.status == Recebimento.PENDENTE:
        return ""
    verbo = "Aprovado" if r.status == Recebimento.APROVADO else "Descartado"
    quando = apresentacao.data_hora(r.decidido_em)
    return f"{verbo} por {apresentacao.quem(r.decidido_por)} em {quando}"


class AprovacoesView(CadastroMixin, View):
    """Endereço antigo da TEL-37: redireciona para a aba Aprovações do painel com a mesma
    querystring (D-063). `cadastro.aprovar`."""

    acao_requerida = "cadastro.aprovar"
    http_method_names = ["get", "head", "options"]

    def get(self, request):
        return redirect(url_aba(request.META.get("QUERY_STRING", "")))


class Aprovacoes:
    """Contexto da aba Aprovações do painel (TEL-37, D-048, D-063). Quem chama já exigiu
    `cadastro.aprovar`.

    Querystring: `status` (pendente|aprovado|descartado|todos; padrão pendente), `q` (número,
    cliente, tipo, remetente ou nº de controle), `lote` (uuid de uma chamada da API, D-049),
    `pagina` (25 por página).

    Contexto: `itens` (Page de dicts {pk, numero, numero_valido, tipo, remetente, origem, cliente,
    uf, quando, prazo, motivo, numero_controle, alertas [{rotulo, grave}], ja_cadastrado_url,
    aprovavel, recebido_em, decisao, motivo_descarte, processo_url, envio_url}), `page_obj`,
    `consulta` (querystring com "&" no fim, p/ a paginação), `consulta_atual` (sem "&", p/ voltar
    depois do POST), `q`, `status_atual`, `pendentes` (bool: mostra seleção e ações),
    `filtros_status` [{rotulo, url, ativo}], `total_pendentes`, `ultima_chegada` ("" ou
    DD/MM/AAAA HH:MM), `carteiras` [(pk, nome)] com "" = "Outra / não sei", `url_aprovar`,
    `url_descartar`, `url_config` ("" se não é Adm), `url_api_log`, `url_importar`; com `lote`:
    `lote_atual`, `lote_rotulo` ("envio de DD/MM/AAAA HH:MM") e `url_sem_lote`. As URLs já levam
    `aba=aprovacoes`.
    """

    def __init__(self, request, adm):
        self.request, self.adm = request, adm

    def _parametros(self):
        get = self.request.GET
        status = get.get("status", STATUS_PADRAO)
        return {
            "aba": ABA,
            "status": status if status in ROTULOS_STATUS else STATUS_PADRAO,
            "q": limpar_texto(get.get("q", ""))[:100],
            "lote": _uuid(get.get("lote", "")),
        }

    @staticmethod
    def _filtrar(qs, q):
        if not q:
            return qs
        condicao = (
            Q(cliente__icontains=q)
            | Q(tipo__icontains=q)
            | Q(remetente_sigla__icontains=q)
            | Q(numero_controle__icontains=q)
            | Q(numero__icontains=q)
        )
        digitos = cnj.so_digitos(q)
        if len(digitos) >= 4:
            condicao |= Q(numero_digitos__contains=digitos)
        return qs.filter(condicao)

    def contexto(self):
        contexto = {}
        parametros = self._parametros()
        padroes = {"status": STATUS_PADRAO}
        qs = Recebimento.objects.all()
        if parametros["status"] != TODOS:
            qs = qs.filter(status=parametros["status"])
        if parametros["lote"]:
            qs = qs.filter(lote=parametros["lote"])
        qs = self._filtrar(qs, parametros["q"]).select_related(
            "decidido_por", "item_envio__processo"
        )
        pagina = listagem.pagina_valida(
            Paginator(qs.order_by("-recebido_em", "pk"), listagem.POR_PAGINA),
            self.request.GET.get("pagina"),
        )
        recebidos = list(pagina.object_list)
        existentes = dict(
            Processo.objects.filter(
                numero_valido=True,
                numero_digitos__in={r.numero_digitos for r in recebidos if r.numero_valido},
            ).values_list("numero_digitos", "pk")
        )
        pagina.object_list = [self._linha(r, existentes) for r in recebidos]
        contagem = Recebimento.objects.aggregate(
            pendentes=Count("pk", filter=Q(status=Recebimento.PENDENTE)),
            ultima=Max("recebido_em"),
        )

        def url(**trocas):
            texto = listagem.consulta(parametros, padroes, **trocas)
            return f"?{texto}"

        consulta_atual = listagem.consulta(
            {**parametros, "pagina": str(pagina.number) if pagina.number > 1 else ""}, padroes
        )
        contexto.update(
            itens=pagina,
            page_obj=pagina,
            consulta=listagem.consulta(parametros, padroes) + "&",
            consulta_atual=consulta_atual,
            q=parametros["q"],
            status_atual=parametros["status"],
            pendentes=parametros["status"] == Recebimento.PENDENTE,
            filtros_status=[
                {"rotulo": rotulo, "url": url(status=valor), "ativo": parametros["status"] == valor}
                for valor, rotulo in ROTULOS_STATUS.items()
            ],
            total_pendentes=contagem["pendentes"],
            ultima_chegada=apresentacao.data_hora(contagem["ultima"]),
            carteiras=_carteiras_choices("Outra / não sei"),
            url_aprovar=reverse("juridico:aprovar"),
            url_descartar=reverse("juridico:descartar"),
            url_config=reverse("juridico:config") if self.adm else "",
            url_api_log=reverse("juridico:api_log"),
            url_importar=reverse("juridico:importar_carga"),
            lote_atual=parametros["lote"],
            lote_rotulo=self._rotulo_lote(parametros["lote"]),
            url_sem_lote=url(lote=""),
        )
        return contexto

    @staticmethod
    def _rotulo_lote(lote):
        if not lote:
            return ""
        chamada = ChamadaApi.objects.filter(lote=lote).only("recebido_em").first()
        return f"envio de {apresentacao.data_hora(chamada.recebido_em)}" if chamada else "um envio"

    @staticmethod
    def _linha(r, existentes):
        item_envio = r.item_envio
        processo = item_envio.processo if item_envio is not None else None
        existente = existentes.get(r.numero_digitos) if r.numero_valido else None
        return Item(
            {
                "pk": r.pk,
                "numero": r.numero,
                "numero_valido": r.numero_valido,
                "tipo": r.tipo,
                "remetente": r.remetente_sigla or r.remetente,
                "origem": r.origem,
                "cliente": r.cliente,
                "uf": r.uf,
                "quando": recebimentos.quando(r),
                "prazo": r.prazo,
                "motivo": r.motivo,
                "numero_controle": r.numero_controle,
                "alertas": [
                    {
                        "rotulo": recebimentos.rotulo_alerta(a),
                        "grave": a in recebimentos.ALERTAS_GRAVES,
                    }
                    for a in r.alertas
                ],
                "ja_cadastrado_url": reverse("juridico:processo", kwargs={"pk": existente})
                if existente
                else "",
                "aprovavel": r.status == Recebimento.PENDENTE and r.numero_valido,
                "recebido_em": apresentacao.data_hora(r.recebido_em),
                "decisao": _decisao(r),
                "motivo_descarte": r.motivo_descarte,
                "processo_url": reverse("juridico:processo", kwargs={"pk": processo.pk})
                if processo is not None
                else "",
                "envio_url": reverse("juridico:envio", kwargs={"pk": item_envio.envio_id})
                if item_envio is not None
                else "",
            }
        )


class AprovarView(SoPost):
    """POST `ids` (múltiplo), `carteira` (pk ou vazio), `consulta`: aprova os pendentes com número
    válido e manda para a fila do cadastro por CNJ; volta para a lista com os mesmos filtros."""

    acao_requerida = "cadastro.aprovar"

    def post(self, request):
        ids = _ids(request)
        if not ids:
            messages.error(request, "Selecione ao menos um item.")
            return _voltar(request)
        pk = request.POST.get("carteira", "")
        carteira = Carteira.objects.filter(pk=pk, ativa=True).first() if pk.isdigit() else None
        envio, na_fila, ignorados = recebimentos.aprovar(request.user, ids, carteira)
        if envio is None:
            messages.error(
                request,
                "Nada aprovado: os itens selecionados não têm número CNJ válido "
                "(descarte-os ou use o cadastro manual).",
            )
            return _voltar(request)
        texto = (
            f"{na_fila} processo{'s' if na_fila != 1 else ''} na fila do cadastro "
            f"(envio nº {envio.pk})."
        )
        if ignorados == 1:
            texto += " 1 item sem número válido continua pendente."
        elif ignorados:
            texto += f" {ignorados} itens sem número válido continuam pendentes."
        messages.success(request, texto)
        return _voltar(request)


class DescartarView(SoPost):
    """POST `ids` (múltiplo), `motivo` (opcional, até 300), `consulta`: descarta os pendentes."""

    acao_requerida = "cadastro.aprovar"

    def post(self, request):
        ids = _ids(request)
        if not ids:
            messages.error(request, "Selecione ao menos um item.")
            return _voltar(request)
        total = recebimentos.descartar(
            request.user, ids, limpar_texto(request.POST.get("motivo", ""))
        )
        messages.success(
            request,
            f"{total} ite{'ns' if total != 1 else 'm'} descartado{'s' if total != 1 else ''}.",
        )
        return _voltar(request)


class ImportarCargaView(SoPost):
    """POST (multipart) `arquivo` (.json) ou `texto` (JSON colado): a mesma carga que o n8n
    mandaria pela API (lista de itens, {"itens": [...]} ou o envelope com "registros", D-059),
    importada à mão quando o n8n não alcança o servidor (D-060). Vira itens pendentes e uma
    linha no log da API; volta para a aba Aprovações filtrada pelo lote importado."""

    acao_requerida = "cadastro.aprovar"

    def post(self, request):
        inicio = time.monotonic()
        arquivo = request.FILES.get("arquivo")
        if arquivo is not None and arquivo.size > recebimentos.MAX_BYTES:
            return self._erro(request, 413, "O arquivo passa de 2 MB: divida a carga.", inicio)
        bruto = arquivo.read() if arquivo is not None else request.POST.get("texto", "").encode()
        if not bruto.strip():
            return self._erro(
                request, 400, "Escolha o arquivo .json da carga ou cole o JSON.", inicio
            )
        if len(bruto) > recebimentos.MAX_BYTES:
            return self._erro(request, 413, "A carga passa de 2 MB: divida a carga.", inicio)
        try:
            itens = recebimentos.extrair_itens(json.loads(bruto.decode("utf-8-sig")))
        except ValueError:
            itens = None
        if itens is None:
            return self._erro(
                request,
                400,
                "Não é a carga do n8n: o conteúdo não é um JSON com os processos.",
                inicio,
            )
        if len(itens) > recebimentos.MAX_ITENS:
            return self._erro(
                request, 413, f"No máximo {recebimentos.MAX_ITENS} itens por importação.", inicio
            )
        resultado = recebimentos.registrar(itens)
        mensagem = (
            f"Importação manual: {resultado['novos']} novo(s), {resultado['repetidos']} "
            f"repetido(s), {len(resultado['invalidos'])} inválido(s)."
        )
        self._log(request, 200, mensagem, inicio, len(bruto), resultado)
        messages.success(request, mensagem)
        if not resultado["novos"]:
            return redirect(url_aba())
        return redirect(url_aba(f"status=todos&lote={resultado['lote']}"))

    def _erro(self, request, status, mensagem, inicio):
        self._log(request, status, f"Importação manual: {mensagem}", inicio, 0, {})
        messages.error(request, mensagem)
        return redirect(url_aba())

    @staticmethod
    def _log(request, status, mensagem, inicio, tamanho, resultado):
        ChamadaApi.objects.create(
            status_http=status,
            mensagem=mensagem[:300],
            ip=request.META.get("REMOTE_ADDR") or None,
            agente=f"Importação manual por {apresentacao.nome(request.user)}"[:200],
            tamanho=tamanho,
            duracao_ms=int((time.monotonic() - inicio) * 1000),
            lote=resultado.get("lote"),
            recebidos=resultado.get("recebidos", 0),
            novos=resultado.get("novos", 0),
            repetidos=resultado.get("repetidos", 0),
            invalidos=len(resultado.get("invalidos", [])),
        )


class GerarChaveApiView(SoPost):
    """POST: gera uma chave nova para a API do n8n (a anterior para de valer). Só Adm. A chave
    aparece uma única vez, na próxima abertura da Configuração."""

    acao_requerida = "cadastro.configurar"

    def post(self, request):
        request.session[recebimentos.SESSAO_CHAVE_NOVA] = recebimentos.gerar_chave()
        messages.success(request, "Chave nova gerada. Copie agora: ela não aparece de novo.")
        return redirect(reverse("juridico:config") + "#c-api")


def _tamanho_texto(tamanho):
    if tamanho >= 1024 * 1024:
        return f"{tamanho / 1024 / 1024:.1f} MB".replace(".", ",")
    if tamanho >= 1024:
        return f"{tamanho / 1024:.1f} KB".replace(".", ",")
    return f"{tamanho} B"


class ApiLogView(CadastroMixin, TemplateView):
    """Log da API do n8n (TEL-38, D-049). Template `juridico/api_log.html`. `cadastro.aprovar`.

    Uma linha por POST recebido, aceito ou recusado (o corpo e a chave nunca são guardados).
    Querystring: `resultado` (aceitas|recusadas; vazio = todas), `pagina` (25 por página).

    Contexto: `chamadas` (Page de dicts {pk, quando, aceita, status_http, status_rotulo, mensagem,
    ip, agente, tamanho, duracao, recebidos, novos, repetidos, invalidos, pendentes, aprovados,
    descartados, url_itens}), `page_obj`, `consulta`, `resultado_atual`, `filtros_resultado`
    [{rotulo, url, ativo}], `resumo_24h` {total, aceitas, recusadas, novos}, `ultima_chamada`
    ("" ou DD/MM/AAAA HH:MM), `url_aprovacoes`, `url_config` ("" se não é Adm).
    """

    acao_requerida = "cadastro.aprovar"
    template_name = "juridico/api_log.html"
    RESULTADOS = {"": "Todas", "aceitas": "Aceitas", "recusadas": "Recusadas"}
    ROTULOS_HTTP = {
        200: "Aceita",
        400: "Formato inválido",
        401: "Chave recusada",
        413: "Grande demais",
        503: "API sem chave",
    }

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        resultado = self.request.GET.get("resultado", "")
        resultado = resultado if resultado in self.RESULTADOS else ""
        qs = ChamadaApi.objects.all()
        if resultado == "aceitas":
            qs = qs.filter(status_http=200)
        elif resultado == "recusadas":
            qs = qs.exclude(status_http=200)
        pagina = listagem.pagina_valida(
            Paginator(qs.order_by("-recebido_em", "-pk"), listagem.POR_PAGINA),
            self.request.GET.get("pagina"),
        )
        chamadas = list(pagina.object_list)
        lotes = [c.lote for c in chamadas if c.lote]
        situacao = {
            linha["lote"]: linha
            for linha in Recebimento.objects.filter(lote__in=lotes)
            .values("lote")
            .annotate(
                pendentes=Count("pk", filter=Q(status=Recebimento.PENDENTE)),
                aprovados=Count("pk", filter=Q(status=Recebimento.APROVADO)),
                descartados=Count("pk", filter=Q(status=Recebimento.DESCARTADO)),
            )
        }
        pagina.object_list = [self._linha(c, situacao.get(c.lote, {})) for c in chamadas]
        resumo = ChamadaApi.objects.filter(
            recebido_em__gte=timezone.now() - timedelta(hours=24)
        ).aggregate(
            total=Count("pk"),
            aceitas=Count("pk", filter=Q(status_http=200)),
            novos=Sum("novos"),
            ultima=Max("recebido_em"),
        )
        ultima = resumo.pop("ultima") or ChamadaApi.objects.aggregate(u=Max("recebido_em"))["u"]
        resumo["recusadas"] = resumo["total"] - resumo["aceitas"]
        resumo["novos"] = resumo["novos"] or 0
        consulta = listagem.consulta({"resultado": resultado})
        contexto.update(
            chamadas=pagina,
            page_obj=pagina,
            consulta=f"{consulta}&" if consulta else "",
            resultado_atual=resultado,
            filtros_resultado=[
                {
                    "rotulo": rotulo,
                    "url": f"?{listagem.consulta({'resultado': valor})}" if valor else "?",
                    "ativo": resultado == valor,
                }
                for valor, rotulo in self.RESULTADOS.items()
            ],
            resumo_24h=resumo,
            ultima_chamada=apresentacao.data_hora(ultima),
            url_aprovacoes=url_aba(),
            url_config=reverse("juridico:config") if self.adm else "",
        )
        return contexto

    def _linha(self, c, situacao):
        url_itens = ""
        if c.lote and c.novos:
            url_itens = url_aba(f"status=todos&lote={c.lote}")
        return Item(
            {
                "pk": c.pk,
                "quando": apresentacao.data_hora(c.recebido_em),
                "aceita": c.aceita,
                "status_http": c.status_http,
                "status_rotulo": self.ROTULOS_HTTP.get(c.status_http, f"HTTP {c.status_http}"),
                "mensagem": c.mensagem,
                "ip": c.ip or "—",
                "agente": c.agente,
                "tamanho": _tamanho_texto(c.tamanho),
                "duracao": f"{c.duracao_ms} ms",
                "recebidos": c.recebidos,
                "novos": c.novos,
                "repetidos": c.repetidos,
                "invalidos": c.invalidos,
                "pendentes": situacao.get("pendentes", 0),
                "aprovados": situacao.get("aprovados", 0),
                "descartados": situacao.get("descartados", 0),
                "url_itens": url_itens,
            }
        )
