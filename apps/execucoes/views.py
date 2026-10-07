from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from apps.contas.permissoes import PermissaoMixin, escopo, pode
from apps.nucleo import listagem
from apps.nucleo.entrada import limpar_texto

from . import apresentacao
from .models import LIMITE_EXECUTANDO, Execucao

ORDENS = {"fluxo": "fluxo_nome", "iniciada_em": "iniciada_em"}
ORDEM_PADRAO = "-iniciada_em"
STATUS = {"executando": "Executando", "sucesso": "Sucesso", "erro": "Erro"}


def _ordem_valida(valor):
    valor = valor or ""
    return valor if valor.lstrip("-") in ORDENS and valor.count("-") <= 1 else ORDEM_PADRAO


def _filtro_status(status):
    """Filtro por status EFETIVO: 'executando' há mais de 5 min conta como erro (EXE-10)."""
    limite = timezone.now() - LIMITE_EXECUTANDO
    if status == "executando":
        return Q(status="executando", iniciada_em__gte=limite)
    if status == "erro":
        return Q(status="erro") | Q(status="executando", iniciada_em__lt=limite)
    return Q(status=status)


class ExecucaoListaView(PermissaoMixin, TemplateView):
    """Histórico de execuções (TEL-06; EXE-08, EXE-11). Template `execucoes/lista.html`.

    Querystring: `q` (nome do fluxo), `status` (executando|sucesso|erro — pelo status efetivo),
    `ordem` (fluxo|iniciada_em, `-` para decrescente; padrão -iniciada_em), `pagina`.
    Escopo pelo motor: Base só vê as próprias (nunca aparece, nem por busca/filtro/página).

    Contexto (além do shell):
    - `execucoes`: linhas da página, dicts {pk, fluxo_nome, executado_por_nome, status,
      status_rotulo, iniciada_em, duracao_texto ('1,2 s' ou ''), erro_resumo, url_detalhe}
      (`status` já é o efetivo: 'executando' por mais de 5 min vem como 'erro')
    - `page_obj` (25 por página) e `consulta` (querystring dos filtros com '&' no fim)
    - `q`, `ordem`, `status_atual` ("" = Todos), `filtros_status` [{rotulo, url, ativo}]
      (segmentado), `ordenacoes` {fluxo|iniciada_em: {url, sentido 'asc'|'desc'|''}}, `total`
    """

    acao_requerida = "execucoes.ver"
    template_name = "execucoes/lista.html"

    def _parametros(self):
        get = self.request.GET
        status = get.get("status", "")
        return {
            "q": limpar_texto(get.get("q", "")),
            "status": status if status in STATUS else "",
            "ordem": _ordem_valida(get.get("ordem", ORDEM_PADRAO)),
        }

    def _queryset(self, parametros):
        qs = escopo(self.request.user, Execucao.objects, "execucoes.ver").select_related(
            "executado_por"
        )
        if parametros["q"]:
            qs = qs.filter(fluxo_nome__icontains=parametros["q"])
        if parametros["status"]:
            qs = qs.filter(_filtro_status(parametros["status"]))
        ordem = parametros["ordem"]
        campo = ORDENS[ordem.lstrip("-")]
        return qs.order_by(("-" if ordem.startswith("-") else "") + campo, "-pk")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        parametros = self._parametros()
        paginator = Paginator(self._queryset(parametros), listagem.POR_PAGINA)
        pagina = listagem.pagina_valida(paginator, self.request.GET.get("pagina", 1))
        padroes = {"ordem": ORDEM_PADRAO}

        def url(**trocas):
            return "?" + listagem.consulta(parametros, padroes, **trocas)

        ordenacoes = {}
        for campo in ORDENS:
            atual, sentido = parametros["ordem"], ""
            if atual.lstrip("-") == campo:
                sentido = "desc" if atual.startswith("-") else "asc"
            proxima = f"-{campo}" if sentido == "asc" else campo
            ordenacoes[campo] = {"url": url(ordem=proxima), "sentido": sentido}
        filtros = [{"rotulo": "Todos", "url": url(status=""), "ativo": not parametros["status"]}]
        filtros += [
            {"rotulo": rotulo, "url": url(status=valor), "ativo": parametros["status"] == valor}
            for valor, rotulo in STATUS.items()
        ]
        base_consulta = listagem.consulta(parametros, padroes, pagina="")
        linhas = [
            {
                "pk": e.pk,
                "fluxo_nome": e.fluxo_nome,
                "executado_por_nome": e.executado_por.nome,
                "status": e.status_efetivo,
                "status_rotulo": e.status_rotulo,
                "iniciada_em": e.iniciada_em,
                "duracao_texto": apresentacao.duracao_texto(e.duracao_ms),
                "erro_resumo": e.erro_resumo_efetivo,
                "url_detalhe": reverse("execucoes:detalhe", kwargs={"pk": e.pk}),
            }
            for e in pagina.object_list
        ]
        contexto.update(
            execucoes=linhas,
            page_obj=pagina,
            consulta=base_consulta + "&" if base_consulta else "",
            q=parametros["q"],
            ordem=parametros["ordem"],
            status_atual=parametros["status"],
            filtros_status=filtros,
            ordenacoes=ordenacoes,
            total=paginator.count,
        )
        return contexto


class ExecucaoDetalheView(PermissaoMixin, TemplateView):
    """Detalhe da execução (TEL-07; EXE-07, EXE-09, SEG-09/13). Template `execucoes/detalhe.html`.
    Fora do escopo (ex.: Base e execução de outra pessoa) → 404.

    Contexto (além do shell), tudo texto puro (o template escapa):
    - `execucao`: {pk, fluxo_nome, status, status_rotulo, executado_por_nome, iniciada_em,
      finalizada_em, duracao_texto, erro_resumo} (status efetivo; EXE-10)
    - `nos`: lista em ordem, cada um {ordem, no_id, tipo, titulo, status ('sucesso'|'erro'|
      'nao_executado'), status_rotulo, duracao_texto, erro_categoria, erro_rotulo, erro_mensagem,
      entrada_json (indentado, mascarado), saida_json, http_status (int|None),
      headers_saida [{nome, valor}], corpo_texto (JSON indentado ou texto), truncado (bool)}
    - `resultado_json`: saída do nó saída (EXE-07); '' se ele não rodou
    - `url_lista`; `url_fluxo` (editor do fluxo; '' se o fluxo foi excluído ou sem permissão)
    """

    acao_requerida = "execucoes.ver"
    template_name = "execucoes/detalhe.html"

    def _no(self, no):
        saida = no.saida if isinstance(no.saida, dict) else {}
        headers = saida.get("headers") if isinstance(saida.get("headers"), dict) else {}
        return {
            "ordem": no.ordem,
            "no_id": no.no_id,
            "tipo": no.no_tipo,
            "titulo": no.no_titulo,
            "status": no.status,
            "status_rotulo": apresentacao.ROTULOS_NO.get(no.status, no.status),
            "duracao_texto": apresentacao.duracao_texto(no.duracao_ms)
            if no.status != "nao_executado"
            else "",
            "erro_categoria": no.erro_categoria or "",
            "erro_rotulo": apresentacao.ROTULOS_ERRO.get(no.erro_categoria or "", ""),
            "erro_mensagem": no.erro_mensagem,
            "entrada_json": apresentacao.json_formatado(no.entrada),
            "saida_json": apresentacao.json_formatado(no.saida),
            "http_status": saida.get("status") if isinstance(saida.get("status"), int) else None,
            "headers_saida": [{"nome": n, "valor": v} for n, v in headers.items()],
            "corpo_texto": apresentacao.corpo_texto(saida.get("corpo")),
            "truncado": bool(saida.get("truncado")),
        }

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        usuario = self.request.user
        execucao = get_object_or_404(
            escopo(usuario, Execucao.objects, "execucoes.ver").select_related("executado_por"),
            pk=self.kwargs["pk"],
        )
        nos = [self._no(no) for no in execucao.nos.all()]
        resultado = next(
            (n for n in nos if n["tipo"] == "saida" and n["status"] == "sucesso"), None
        )
        pode_ir_ao_fluxo = execucao.fluxo_id is not None and pode(usuario, "fluxos.editar")
        contexto.update(
            execucao={
                "pk": execucao.pk,
                "fluxo_nome": execucao.fluxo_nome,
                "status": execucao.status_efetivo,
                "status_rotulo": execucao.status_rotulo,
                "executado_por_nome": execucao.executado_por.nome,
                "iniciada_em": execucao.iniciada_em,
                "finalizada_em": execucao.finalizada_em,
                "duracao_texto": apresentacao.duracao_texto(execucao.duracao_ms),
                "erro_resumo": execucao.erro_resumo_efetivo,
            },
            nos=nos,
            resultado_json=resultado["saida_json"] if resultado else "",
            url_lista=reverse("execucoes:lista"),
            url_fluxo=reverse("fluxos:editor", kwargs={"pk": execucao.fluxo_id})
            if pode_ir_ao_fluxo
            else "",
        )
        return contexto
