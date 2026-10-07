import json
import math

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django.views import View
from django.views.generic import TemplateView

from apps.contas.permissoes import PermissaoMixin, escopo, pode
from apps.nucleo import listagem
from apps.nucleo.entrada import limpar_texto

from .forms import FluxoForm
from .grafo import validar
from .models import Fluxo, grafo_inicial

ORDENS = {"nome": "nome", "atualizado_em": "atualizado_em"}
ORDEM_PADRAO = "-atualizado_em"
STATUS = {"rascunho": "Rascunho", "ativo": "Ativo"}
LIMITE_GRAFO_BYTES = 256 * 1024
MSG_CONFLITO = "Este fluxo foi alterado por outra pessoa. Recarregue para continuar."


def _ordem_valida(valor):
    return (
        valor
        if (valor or "").lstrip("-") in ORDENS and (valor or "").count("-") <= 1
        else ORDEM_PADRAO
    )


def _recusar_constante(nome):
    raise ValueError(f"constante JSON não permitida: {nome}")


def _float_finito(texto):
    valor = float(texto)
    if not math.isfinite(valor):
        raise ValueError("número fora do intervalo")
    return valor


def _quer_json(request):
    return "application/json" in request.headers.get("Accept", "")


def _json_erro(mensagem, status, campo=None, **extra):
    corpo = {"ok": False, "erros": [{"campo": campo, "mensagem": mensagem}], **extra}
    return JsonResponse(corpo, status=status)


class FluxoListaView(PermissaoMixin, TemplateView):
    """Lista de fluxos (TEL-04, TEL-12; FLX-01/05). Template `fluxos/lista.html`.

    Querystring: `q` (nome), `status` (rascunho|ativo), `ordem` (nome|atualizado_em, `-` para
    decrescente; padrão -atualizado_em), `pagina`. Valor inválido é ignorado.

    Contexto (além do shell):
    - `fluxos`: linhas da página, dicts {pk, nome, descricao, dono_nome, status, status_rotulo,
      atualizado_em, pode_executar, url_editor, url_editar, url_excluir, url_status,
      url_executar}; as URLs que o papel não pode usar vêm vazias ('').
    - `page_obj` (25 por página; `componentes/paginacao.html`) e `consulta` (querystring dos
      filtros com '&' no fim)
    - `q`, `ordem`, `status_atual` ("" = Todos), `filtros_status` [{rotulo, url, ativo}]
      (segmentado), `ordenacoes` {nome|atualizado_em: {url, sentido}}, `total`
    - flags: `pode_criar`, `pode_editar`, `pode_excluir`, `pode_executar`; `url_novo` ('' se não
      pode)
    - modais: `form_novo` (FluxoForm; com erros se o POST de fluxos:novo falhou), `form_editar`
      (FluxoForm ou None), `modal_aberto` ('', 'novo' ou 'editar'), `fluxo_editando` (dict com pk,
      nome e url_editar do fluxo em edição, ou None)
    """

    acao_requerida = "fluxos.ver"
    template_name = "fluxos/lista.html"
    modal_aberto = ""
    form_novo = None
    form_editar = None
    fluxo_editando = None

    def _parametros(self):
        get = self.request.GET
        status = get.get("status", "")
        return {
            "q": limpar_texto(get.get("q", "")),
            "status": status if status in STATUS else "",
            "ordem": _ordem_valida(get.get("ordem", ORDEM_PADRAO)),
        }

    def _queryset(self, parametros):
        qs = escopo(self.request.user, Fluxo.objects, "fluxos.ver").select_related("dono")
        if parametros["q"]:
            qs = qs.filter(Q(nome__icontains=parametros["q"]))
        if parametros["status"]:
            qs = qs.filter(status=parametros["status"])
        ordem = parametros["ordem"]
        campo = ORDENS[ordem.lstrip("-")]
        return qs.order_by(("-" if ordem.startswith("-") else "") + campo, "-pk")

    def _linha(self, fluxo, pode_editar, pode_excluir):
        pk = {"pk": fluxo.pk}
        pode_executar = pode(self.request.user, "fluxos.executar", fluxo)
        return {
            "pk": fluxo.pk,
            "nome": fluxo.nome,
            "descricao": fluxo.descricao,
            "dono_nome": fluxo.dono.nome,
            "status": fluxo.status,
            "status_rotulo": STATUS[fluxo.status],
            "atualizado_em": fluxo.atualizado_em,
            "pode_executar": pode_executar,
            "url_editor": reverse("fluxos:editor", kwargs=pk) if pode_editar else "",
            "url_editar": reverse("fluxos:editar", kwargs=pk) if pode_editar else "",
            "url_status": reverse("fluxos:status", kwargs=pk) if pode_editar else "",
            "url_excluir": reverse("fluxos:excluir", kwargs=pk) if pode_excluir else "",
            "url_executar": reverse("fluxos:executar", kwargs=pk) if pode_executar else "",
        }

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        usuario = self.request.user
        parametros = self._parametros()
        pode_criar = pode(usuario, "fluxos.criar")
        pode_editar = pode(usuario, "fluxos.editar")
        pode_excluir = pode(usuario, "fluxos.excluir")
        paginator = Paginator(self._queryset(parametros), listagem.POR_PAGINA)
        pagina = listagem.pagina_valida(paginator, self.request.GET.get("pagina", 1))
        padroes = {"ordem": ORDEM_PADRAO}

        def url(**trocas):
            return "?" + listagem.consulta(parametros, padroes, **trocas)

        ordenacoes = {}
        for campo in ORDENS:
            atual = parametros["ordem"]
            sentido = (
                ("desc" if atual.startswith("-") else "asc") if atual.lstrip("-") == campo else ""
            )
            ordenacoes[campo] = {
                "url": url(ordem=f"-{campo}" if sentido == "asc" else campo),
                "sentido": sentido,
            }
        status_visiveis = STATUS if pode_editar else {"ativo": STATUS["ativo"]}
        filtros = [{"rotulo": "Todos", "url": url(status=""), "ativo": not parametros["status"]}]
        filtros += [
            {"rotulo": rotulo, "url": url(status=valor), "ativo": parametros["status"] == valor}
            for valor, rotulo in status_visiveis.items()
        ]
        base_consulta = listagem.consulta(parametros, padroes, pagina="")
        contexto.update(
            fluxos=[self._linha(f, pode_editar, pode_excluir) for f in pagina.object_list],
            page_obj=pagina,
            consulta=base_consulta + "&" if base_consulta else "",
            q=parametros["q"],
            ordem=parametros["ordem"],
            status_atual=parametros["status"],
            filtros_status=filtros,
            ordenacoes=ordenacoes,
            total=paginator.count,
            pode_criar=pode_criar,
            pode_editar=pode_editar,
            pode_excluir=pode_excluir,
            pode_executar=pode(usuario, "fluxos.executar"),
            url_novo=reverse("fluxos:novo") if pode_criar else "",
            form_novo=self.form_novo or FluxoForm(),
            form_editar=self.form_editar,
            modal_aberto=self.modal_aberto,
            fluxo_editando=self.fluxo_editando,
        )
        return contexto


class FluxoNovoView(PermissaoMixin, View):
    """Criar fluxo (FLX-02/06). Só POST (`nome`, `descricao`); fluxos.criar.

    Sucesso → redirect `fluxos:editor` + toast "Fluxo <nome> criado.". Erro → re-renderiza
    `fluxos/lista.html` (200) com `form_novo` com erros e `modal_aberto='novo'`.
    """

    acao_requerida = "fluxos.criar"
    http_method_names = ["post", "options"]

    def post(self, request):
        form = FluxoForm(request.POST)
        if not form.is_valid():
            visao = FluxoListaView(request=request, modal_aberto="novo", form_novo=form)
            visao.kwargs = {}
            return visao.render_to_response(visao.get_context_data(), status=200)
        fluxo = Fluxo.objects.create(
            nome=form.cleaned_data["nome"],
            descricao=form.cleaned_data["descricao"],
            dono=request.user,
            grafo=grafo_inicial(),
        )
        messages.success(request, f"Fluxo {fluxo.nome} criado.")
        return redirect("fluxos:editor", pk=fluxo.pk)


class _FluxoEscopoView(PermissaoMixin, View):
    """Base das mutações sobre um fluxo existente (404 se não existir no escopo da ação)."""

    def obter(self, pk):
        return get_object_or_404(self.escopo_queryset(Fluxo.objects), pk=pk)


class FluxoEditarView(_FluxoEscopoView):
    """Editar nome e descrição (FLX-03/06). Só POST (`nome`, `descricao`); fluxos.editar.

    Sucesso → redirect `fluxos:editor` + toast "Fluxo atualizado.". Erro → re-renderiza
    `fluxos/lista.html` (200) com `form_editar` com erros, `modal_aberto='editar'` e
    `fluxo_editando`. Dono, status e grafo nunca mudam por aqui.
    """

    acao_requerida = "fluxos.editar"
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        fluxo = get_object_or_404(Fluxo, pk=pk)
        form = FluxoForm(request.POST)
        if not form.is_valid():
            visao = FluxoListaView(
                request=request,
                modal_aberto="editar",
                form_editar=form,
                fluxo_editando={
                    "pk": fluxo.pk,
                    "nome": fluxo.nome,
                    "url_editar": reverse("fluxos:editar", kwargs={"pk": fluxo.pk}),
                },
            )
            visao.kwargs = {}
            return visao.render_to_response(visao.get_context_data(), status=200)
        fluxo.nome = form.cleaned_data["nome"]
        fluxo.descricao = form.cleaned_data["descricao"]
        fluxo.save(update_fields=["nome", "descricao", "atualizado_em"])
        messages.success(request, "Fluxo atualizado.")
        return redirect("fluxos:editor", pk=fluxo.pk)


class FluxoExcluirView(PermissaoMixin, View):
    """Excluir fluxo (FLX-03/06). Só POST; fluxos.excluir; a confirmação é um modal do front.

    Sucesso → redirect `fluxos:lista` + toast "Fluxo <nome> excluído.".
    """

    acao_requerida = "fluxos.excluir"
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        fluxo = get_object_or_404(Fluxo, pk=pk)
        nome = fluxo.nome
        fluxo.delete()
        messages.success(request, f"Fluxo {nome} excluído.")
        return redirect("fluxos:lista")


class FluxoStatusView(PermissaoMixin, View):
    """Ativar ou voltar a rascunho (FLX-04/06, EST-01). Só POST (`status`); fluxos.editar.

    `status` fora de rascunho|ativo → 400 (JSON ou texto) sem alterar. Ativar com pendências →
    400 JSON
    {"ok": false, "pendencias": [...]} (Accept: application/json) ou redirect para o editor com
    toast de erro. Sucesso: JSON {"ok": true, "status"} ou redirect para o editor (ou para a lista
    se o POST traz `voltar=lista`) com toast.
    """

    acao_requerida = "fluxos.editar"
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        fluxo = get_object_or_404(Fluxo, pk=pk)
        novo = request.POST.get("status", "")
        destino = "fluxos:lista" if request.POST.get("voltar") == "lista" else None
        if novo not in STATUS:
            if _quer_json(request):
                return _json_erro("Status inválido.", 400, "status")
            return HttpResponseBadRequest("Status inválido.")
        if novo == Fluxo.ATIVO:
            erros, pendencias = validar(fluxo.grafo)
            if erros:
                pendencias = [
                    {"no": None, "campo": e["campo"], "mensagem": e["mensagem"]} for e in erros
                ]
            if pendencias:
                if _quer_json(request):
                    return JsonResponse({"ok": False, "pendencias": pendencias}, status=400)
                messages.error(
                    request,
                    "Não foi possível ativar: o fluxo tem pendências. Corrija-as no editor.",
                )
                return redirect("fluxos:editor", pk=fluxo.pk)
        fluxo.status = novo
        fluxo.save(update_fields=["status", "atualizado_em"])
        if _quer_json(request):
            return JsonResponse({"ok": True, "status": fluxo.status})
        messages.success(
            request, "Fluxo ativado." if novo == Fluxo.ATIVO else "Fluxo voltou para rascunho."
        )
        return redirect(destino or "fluxos:editor", **({} if destino else {"pk": fluxo.pk}))


class FluxoExecutarView(_FluxoEscopoView):
    """Executar fluxo (EXE-01). PLACEHOLDER do M2: a execução real chega no M3.

    Só POST; fluxos.executar; fluxo fora do escopo (ex.: Base e rascunho) → 404. Hoje só avisa.
    """

    acao_requerida = "fluxos.executar"
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        self.obter(pk)
        messages.info(request, "A execução de fluxos será liberada em breve.")
        return redirect("fluxos:lista")


class FluxoEditorView(PermissaoMixin, View):
    """Editor de canvas (TEL-05; GRF-06/08). fluxos.editar; pk inexistente → 404.
    Template `fluxos/editor.html`.

    Contexto (além do shell):
    - `fluxo`: Fluxo (pk, nome, descricao, status); `status_rotulo`
    - `grafo` (dict canônico: o template emite `{{ grafo|json_script:"grafo-inicial" }}`)
    - `atualizado_em` (isoformat do banco; vai em `data-atualizado-em` no elemento raiz)
    - `pendencias`: lista [{no, campo, mensagem}] do grafo atual (já ao abrir)
    - `url_salvar` (POST JSON), `url_status` (POST `status`), `url_lista`, `url_editar` (POST meta),
      `url_excluir`, `url_executar`; `form_meta` (FluxoForm com nome/descricao atuais)
    - flags: `pode_excluir`, `pode_executar` (False enquanto o M3 não chega: `executar_ativo`)
    """

    acao_requerida = "fluxos.editar"
    http_method_names = ["get", "head", "options"]

    def get(self, request, pk):
        fluxo = get_object_or_404(Fluxo, pk=pk)
        erros, pendencias = validar(fluxo.grafo)
        if erros:
            pendencias = [
                {"no": None, "campo": e["campo"], "mensagem": e["mensagem"]} for e in erros
            ]
        chave = {"pk": fluxo.pk}
        contexto = {
            "fluxo": fluxo,
            "status_rotulo": STATUS[fluxo.status],
            "grafo": fluxo.grafo,
            "atualizado_em": fluxo.atualizado_em.isoformat(),
            "pendencias": pendencias,
            "url_salvar": reverse("fluxos:salvar_grafo", kwargs=chave),
            "url_status": reverse("fluxos:status", kwargs=chave),
            "url_lista": reverse("fluxos:lista"),
            "url_editar": reverse("fluxos:editar", kwargs=chave),
            "url_excluir": reverse("fluxos:excluir", kwargs=chave),
            "url_executar": reverse("fluxos:executar", kwargs=chave),
            "form_meta": FluxoForm(initial={"nome": fluxo.nome, "descricao": fluxo.descricao}),
            "pode_excluir": pode(request.user, "fluxos.excluir"),
            "pode_executar": pode(request.user, "fluxos.executar", fluxo),
        }
        return render(request, "fluxos/editor.html", contexto)


class SalvarGrafoView(PermissaoMixin, View):
    """Salvar o grafo (GRF-01/02/03/07/08, EST-01, SEG-14). Só POST JSON com X-CSRFToken:
    {"grafo": {...}, "atualizado_em": "<iso lido ao abrir>"}; fluxos.editar.

    - 400 (nada gravado): corpo > 256 KB, JSON/estrutura inválidos ou erro de formato do grafo →
      {"ok": false, "erros": [{"campo", "mensagem"}], "pendencias": []}
    - 409 (nada gravado): fluxo alterado depois de `atualizado_em` → {"ok": false, "erros":
      [{"campo": null, "mensagem": MSG_CONFLITO}]} ("Este fluxo foi alterado por outra pessoa.
      Recarregue para continuar.")
    - 200: {"ok": true, "pendencias": [{no, campo, mensagem}], "atualizado_em": <novo iso>,
      "status": "rascunho"|"ativo", "voltou_para_rascunho": bool}. Pendências não impedem salvar;
      um fluxo ativo salvo com pendências volta para rascunho (EST-01).
    """

    acao_requerida = "fluxos.editar"
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        get_object_or_404(Fluxo, pk=pk)
        if len(request.body) > LIMITE_GRAFO_BYTES:
            return _json_erro("O grafo é grande demais (máximo de 256 KB).", 400)
        try:
            corpo = json.loads(
                request.body, parse_constant=_recusar_constante, parse_float=_float_finito
            )
        except ValueError, RecursionError:  # inclui NaN/Infinity, 1e999 e aninhamento extremo
            return _json_erro("JSON inválido ou fora dos limites do grafo.", 400)
        if not (
            isinstance(corpo, dict)
            and isinstance(corpo.get("grafo"), dict)
            and isinstance(corpo.get("atualizado_em"), str)
        ):
            return _json_erro("Envie {grafo, atualizado_em}.", 400)
        grafo = corpo["grafo"]
        erros, pendencias = validar(grafo)
        if erros:
            return JsonResponse({"ok": False, "erros": erros, "pendencias": []}, status=400)
        try:
            lido = parse_datetime(corpo["atualizado_em"])
        except ValueError:
            lido = None
        if lido is None:
            return _json_erro("atualizado_em inválido.", 400, "atualizado_em")
        with transaction.atomic():
            fluxo = get_object_or_404(Fluxo.objects.select_for_update(), pk=pk)
            if fluxo.atualizado_em != lido:
                return _json_erro(MSG_CONFLITO, 409)
            voltou = bool(pendencias) and fluxo.status == Fluxo.ATIVO
            fluxo.grafo = grafo
            if voltou:
                fluxo.status = Fluxo.RASCUNHO
            fluxo.save(update_fields=["grafo", "status", "atualizado_em"])
        return JsonResponse(
            {
                "ok": True,
                "pendencias": pendencias,
                "atualizado_em": fluxo.atualizado_em.isoformat(),
                "status": fluxo.status,
                "voltou_para_rascunho": voltou,
            }
        )
