import json
import math

from django.contrib import messages
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_datetime
from django.views import View
from django.views.generic import TemplateView

from apps.contas.forms_setores import escolhas_setor
from apps.contas.permissoes import PermissaoMixin, escopo, papel_de, pode
from apps.credenciais.models import Credencial
from apps.execucoes.models import Execucao
from apps.motor import executor, mascarar
from apps.motor.expressoes import ErroExpressao, Escopo, resolver_texto, resolver_valor
from apps.nucleo import listagem
from apps.nucleo.entrada import limpar_texto

from . import exportacao, importacao
from .forms import FluxoForm
from .grafo import mexeu_no_codigo, normalizar, validar
from .models import Fluxo, grafo_inicial

ORDENS = {"nome": "nome", "atualizado_em": "atualizado_em"}
ORDEM_PADRAO = "-atualizado_em"
STATUS = {"rascunho": "Rascunho", "ativo": "Ativo"}
LIMITE_GRAFO_BYTES = 2 * 1024 * 1024
MSG_SO_ADM_CODIGO = "Só o administrador pode criar ou editar o nó Código."
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


def pode_mover_setor(usuario):
    """SET-04: só o Adm (escopo 'todos' em fluxos.editar) muda o setor de um fluxo."""
    return papel_de(usuario) == "adm"


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
      pode); `pode_importar` e `url_importar` (POST multipart `arquivo`; '' se não pode); cada
      linha traz `url_exportar` (GET, download .json)
    - modais: `form_novo` (FluxoForm; com erros se o POST de fluxos:novo falhou), `form_editar`
      (FluxoForm ou None), `modal_aberto` ('', 'novo' ou 'editar'), `fluxo_editando` (dict com pk,
      nome e url_editar do fluxo em edição, ou None)
    - SET-04: cada linha traz `setor_id` e `setor_nome`; `pode_mover_setor` (só Adm) e
      `opcoes_setor` [{id, nome}] (setores ativos) para o select `setor` do modal de edição
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
        qs = escopo(self.request.user, Fluxo.objects, "fluxos.ver").select_related("dono", "setor")
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
            "setor_id": fluxo.setor_id,
            "setor_nome": fluxo.setor.nome if fluxo.setor_id else "",
            "status": fluxo.status,
            "status_rotulo": STATUS[fluxo.status],
            "atualizado_em": fluxo.atualizado_em,
            "pode_executar": pode_executar,
            "url_editor": reverse("fluxos:editor", kwargs=pk) if pode_editar else "",
            "url_editar": reverse("fluxos:editar", kwargs=pk) if pode_editar else "",
            "url_status": reverse("fluxos:status", kwargs=pk) if pode_editar else "",
            "url_excluir": reverse("fluxos:excluir", kwargs=pk) if pode_excluir else "",
            "url_executar": reverse("fluxos:executar", kwargs=pk) if pode_executar else "",
            "url_exportar": reverse("fluxos:exportar", kwargs=pk),
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
            pode_mover_setor=pode_mover_setor(usuario),
            opcoes_setor=(
                [{"id": valor, "nome": nome} for valor, nome in escolhas_setor("")[1:]]
                if pode_mover_setor(usuario)
                else []
            ),
            url_novo=reverse("fluxos:novo") if pode_criar else "",
            pode_importar=pode_criar,
            url_importar=reverse("fluxos:importar") if pode_criar else "",
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
            setor_id=request.user.setor_id,
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
        fluxo = get_object_or_404(self.escopo_queryset(Fluxo.objects), pk=pk)
        form = FluxoForm(
            request.POST, com_setor=pode_mover_setor(request.user), setor_atual_id=fluxo.setor_id
        )
        if not form.is_valid():
            visao = FluxoListaView(
                request=request,
                modal_aberto="editar",
                form_editar=form,
                fluxo_editando={
                    "pk": fluxo.pk,
                    "nome": fluxo.nome,
                    "setor_id": fluxo.setor_id,
                    "url_editar": reverse("fluxos:editar", kwargs={"pk": fluxo.pk}),
                },
            )
            visao.kwargs = {}
            return visao.render_to_response(visao.get_context_data(), status=200)
        fluxo.nome = form.cleaned_data["nome"]
        fluxo.descricao = form.cleaned_data["descricao"]
        campos = ["nome", "descricao", "atualizado_em"]
        novo_setor = form.setor_novo()
        if novo_setor is not None:
            fluxo.setor = novo_setor
            campos.append("setor")
        fluxo.save(update_fields=campos)
        messages.success(request, "Fluxo atualizado.")
        return redirect("fluxos:editor", pk=fluxo.pk)


class FluxoExcluirView(PermissaoMixin, View):
    """Excluir fluxo (FLX-03/06). Só POST; fluxos.excluir; a confirmação é um modal do front.

    Sucesso → redirect `fluxos:lista` + toast "Fluxo <nome> excluído.".
    """

    acao_requerida = "fluxos.excluir"
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        fluxo = get_object_or_404(self.escopo_queryset(Fluxo.objects), pk=pk)
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
        fluxo = get_object_or_404(self.escopo_queryset(Fluxo.objects), pk=pk)
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
    """Executar fluxo (EXE-01, EXE-02, EXE-11, EXE-13). Só POST + CSRF; fluxos.executar.

    Fluxo fora do escopo (ex.: Base e rascunho) → 404. Execução síncrona; ao fim, redirect para
    `execucoes:detalhe` com toast "Execução concluída." (sucesso) ou "A execução terminou com
    erro." (erro). Com pendências nenhuma execução é criada: redirect de volta (editor para quem
    edita, lista para os demais) com toast de erro "Este fluxo tem pendências. Corrija no editor
    antes de executar.".
    """

    acao_requerida = "fluxos.executar"
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        fluxo = self.obter(pk)
        try:
            execucao = executor.executar(fluxo, request.user)
        except executor.FluxoComPendencias:
            messages.error(
                request, "Este fluxo tem pendências. Corrija no editor antes de executar."
            )
            if pode(request.user, "fluxos.editar"):
                return redirect("fluxos:editor", pk=fluxo.pk)
            return redirect("fluxos:lista")
        if execucao.status == "sucesso":
            messages.success(request, "Execução concluída.")
        else:
            messages.error(request, "A execução terminou com erro.")
        return redirect("execucoes:detalhe", pk=execucao.pk)


class FluxoExecutarNoView(_FluxoEscopoView):
    """Executar até este nó (MV2-06, MV2-12 L7, MV2-14). Só POST; fluxos.editar.

    Campos: `no_id` (obrigatório) e, opcional, `grafo` (JSON do editor ainda não salvo; sem ele
    usa o grafo gravado). Cria uma `Execucao` de teste (`teste=True`): visível só para quem
    rodou, fora da lista oficial e da Home. Com `Accept: application/json`: 200
    {"ok": true, "execucao": pk, "url_detalhe", "status", "nos": {<id>: {status, itens_entrada,
    itens_saida, saida (até 50), erro, logs}}, "arestas": [{de, saida, para, entrada, itens}]};
    sem: redirect para `execucoes:detalhe`. Pendências → 400 {"ok": false, "pendencias": [...]}
    (JSON) ou toast + redirect ao editor. `no_id` desconhecido → 400.
    """

    acao_requerida = "fluxos.editar"
    http_method_names = ["post", "options"]

    def _entrada(self, request):
        if "application/json" in request.content_type:
            try:
                dados = json.loads(request.body or b"{}")
            except ValueError, RecursionError:
                return None
            return dados if isinstance(dados, dict) else None
        dados = request.POST.dict()
        if dados.get("grafo"):
            try:
                dados["grafo"] = json.loads(dados["grafo"])
            except ValueError, RecursionError:
                return None
        return dados

    def post(self, request, pk):
        fluxo = self.obter(pk)
        if len(request.body) > LIMITE_GRAFO_BYTES:
            return _json_erro("O grafo é grande demais (máximo de 2 MB).", 400)
        dados = self._entrada(request)
        no_id = (dados or {}).get("no_id") or (dados or {}).get("no")
        grafo = (dados or {}).get("grafo")
        if not isinstance(no_id, str) or (grafo is not None and not isinstance(grafo, dict)):
            return _json_erro("Envie no_id (e, se quiser, o grafo do editor).", 400, "no_id")
        try:
            execucao = executor.executar_teste(fluxo, request.user, no_id, grafo)
        except KeyError:
            return _json_erro("Nó desconhecido.", 400, "no_id")
        except executor.FluxoComPendencias as erro:
            if _quer_json(request):
                return JsonResponse({"ok": False, "pendencias": erro.pendencias}, status=400)
            messages.error(request, "Este fluxo tem pendências. Corrija antes de executar o nó.")
            return redirect("fluxos:editor", pk=fluxo.pk)
        url = reverse("execucoes:detalhe", kwargs={"pk": execucao.pk})
        if not _quer_json(request):
            return redirect(url)
        nos = {
            n.no_id: {
                "status": n.status,
                "itens_entrada": n.itens_entrada,
                "itens_saida": n.itens_saida,
                "saida": n.saida,
                "erro": {"categoria": n.erro_categoria, "mensagem": n.erro_mensagem}
                if n.erro_categoria
                else None,
                "logs": n.logs,
            }
            for n in execucao.nos.all()
        }
        return JsonResponse(
            {
                "ok": True,
                "execucao": execucao.pk,
                "url_detalhe": url,
                "status": execucao.status,
                "nos": nos,
                "arestas": execucao.arestas,
            }
        )


def _credenciais_visiveis(fluxo):
    """Credenciais que o nó HTTP deste fluxo pode usar (CRD-02): globais ou do setor do fluxo."""
    filtro = Q(setor__isnull=True)
    if fluxo.setor_id:
        filtro |= Q(setor_id=fluxo.setor_id)
    qs = Credencial.objects.filter(filtro).order_by("nome").values("id", "nome", "tipo")
    return list(qs)


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
    - `url_executar_no`; `url_previa` (POST JSON, MV2-23);
      `url_credenciais` ('' sem credenciais.gerenciar); `pode_codigo` (codigo.editar);
      `pode_importar`, `url_importar`; `url_exportar`, `url_exportar_n8n` (GET, download .json)
    - `credenciais`: [{id, nome, tipo}] do setor do fluxo ou globais (nunca valor)
    - `relatorio_importacao`: dict gravado na importação (MV2-18 C6) ou None
    """

    acao_requerida = "fluxos.editar"
    http_method_names = ["get", "head", "options"]

    def get(self, request, pk):
        fluxo = get_object_or_404(self.escopo_queryset(Fluxo.objects), pk=pk)
        erros, pendencias = validar(fluxo.grafo)
        if erros:
            pendencias = [
                {"no": None, "campo": e["campo"], "mensagem": e["mensagem"]} for e in erros
            ]
        chave = {"pk": fluxo.pk}
        contexto = {
            "fluxo": fluxo,
            "status_rotulo": STATUS[fluxo.status],
            "grafo": normalizar(fluxo.grafo),
            "atualizado_em": fluxo.atualizado_em.isoformat(),
            "pendencias": pendencias,
            "url_salvar": reverse("fluxos:salvar_grafo", kwargs=chave),
            "url_status": reverse("fluxos:status", kwargs=chave),
            "url_lista": reverse("fluxos:lista"),
            "url_editar": reverse("fluxos:editar", kwargs=chave),
            "url_excluir": reverse("fluxos:excluir", kwargs=chave),
            "url_executar": reverse("fluxos:executar", kwargs=chave),
            "url_executar_no": reverse("fluxos:executar_no", kwargs=chave),
            "url_previa": reverse("fluxos:previa_expressao", kwargs=chave),
            "url_credenciais": (
                reverse("credenciais:lista") if pode(request.user, "credenciais.gerenciar") else ""
            ),
            "form_meta": FluxoForm(initial={"nome": fluxo.nome, "descricao": fluxo.descricao}),
            "pode_excluir": pode(request.user, "fluxos.excluir"),
            "pode_executar": pode(request.user, "fluxos.executar", fluxo),
            "pode_codigo": pode(request.user, "codigo.editar"),
            "pode_importar": pode(request.user, "fluxos.criar"),
            "url_importar": reverse("fluxos:importar"),
            "url_exportar": reverse("fluxos:exportar", kwargs=chave),
            "url_exportar_n8n": reverse("fluxos:exportar_n8n", kwargs=chave),
            "credenciais": _credenciais_visiveis(fluxo),
            "relatorio_importacao": fluxo.relatorio_importacao,
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
        get_object_or_404(self.escopo_queryset(Fluxo.objects), pk=pk)
        if len(request.body) > LIMITE_GRAFO_BYTES:
            return _json_erro("O grafo é grande demais (máximo de 2 MB).", 400)
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
            fluxo = get_object_or_404(
                self.escopo_queryset(Fluxo.objects).select_for_update(), pk=pk
            )
            if fluxo.atualizado_em != lido:
                return _json_erro(MSG_CONFLITO, 409)
            if not pode(request.user, "codigo.editar") and mexeu_no_codigo(
                fluxo.grafo, normalizar(grafo)
            ):
                return _json_erro(MSG_SO_ADM_CODIGO, 403)
            voltou = bool(pendencias) and fluxo.status == Fluxo.ATIVO
            fluxo.grafo = normalizar(grafo)
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


class FluxoImportarView(PermissaoMixin, View):
    """Importar fluxo (IMP-02, SEG-19, MV2-18 C6). Só POST multipart (campo `arquivo`, até 2 MB);
    fluxos.criar (Base 403). Formatos: nativo e n8n. Cria um fluxo NOVO em rascunho: dono e setor
    são de quem importa; nada do arquivo escolhe dono, setor, id ou status.

    Sucesso → redirect `fluxos:editor` + toast "Fluxo importado com N avisos." (JSON: 200
    {"ok": true, "pk", "url_editor"}). Arquivo recusado → nada criado; JSON: 400 {"ok": false,
    "erros": [...]}; senão redirect `fluxos:lista` + toast "Não foi possível importar: <motivo>.".
    """

    acao_requerida = "fluxos.criar"
    http_method_names = ["post", "options"]

    def _recusar(self, request, motivo):
        if _quer_json(request):
            return _json_erro(f"Não foi possível importar: {motivo}.", 400, "arquivo")
        messages.error(request, f"Não foi possível importar: {motivo}.")
        return redirect("fluxos:lista")

    def post(self, request):
        arquivo = request.FILES.get("arquivo")
        if arquivo is None:
            return self._recusar(request, "envie um arquivo .json")
        if arquivo.size > importacao.LIMITE_BYTES:
            return self._recusar(request, "o arquivo passa de 2 MB")
        try:
            nome, descricao, grafo, relatorio = importacao.importar(
                arquivo.read(importacao.LIMITE_BYTES + 1)
            )
        except importacao.ErroImportacao as erro:
            return self._recusar(request, erro.mensagem)
        fluxo = Fluxo.objects.create(
            nome=nome,
            descricao=descricao,
            dono=request.user,
            setor_id=request.user.setor_id,
            grafo=grafo,
            relatorio_importacao=relatorio,
        )
        avisos = importacao.total_de_avisos(relatorio)
        messages.success(request, f"Fluxo importado com {avisos} avisos.")
        url = reverse("fluxos:editor", kwargs={"pk": fluxo.pk})
        if _quer_json(request):
            return JsonResponse({"ok": True, "pk": fluxo.pk, "url_editor": url})
        return redirect(url)


class _FluxoExportarBase(PermissaoMixin, View):
    """Base dos downloads: fluxos.ver (quem vê o fluxo exporta); fora do escopo → 404. Só GET."""

    acao_requerida = "fluxos.ver"
    http_method_names = ["get", "head", "options"]

    def montar(self, fluxo):
        raise NotImplementedError

    def get(self, request, pk):
        fluxo = get_object_or_404(self.escopo_queryset(Fluxo.objects), pk=pk)
        resposta = HttpResponse(
            json.dumps(self.montar(fluxo), ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )
        sufixo = self.sufixo
        resposta["Content-Disposition"] = (
            f'attachment; filename="{exportacao.slug(fluxo.nome)}{sufixo}.json"'
        )
        return resposta


class FluxoExportarView(_FluxoExportarBase):
    """Exportar no formato nativo (IMP-01, C9): {formato, versao, fluxo, grafo,
    credenciais_usadas} — nunca valores de credencial. Download `<slug>.json`."""

    sufixo = ""

    def montar(self, fluxo):
        return exportacao.exportar_nativo(fluxo)


class FluxoExportarN8nView(_FluxoExportarBase):
    """Exportar para o n8n, melhor esforço (IMP-05, C9): {name, nodes, connections, pinData,
    construtor_relatorio: {fora: [{no, tipo, motivo}]}}. Download `<slug>-n8n.json`."""

    sufixo = "-n8n"

    def montar(self, fluxo):
        return exportacao.exportar_n8n(fluxo)


PREVIAS_POR_MINUTO = 30
MAX_EXPRESSAO_PREVIA = 2000
MSG_SEM_TESTE = "Execute o fluxo em teste para ver a prévia."


class FluxoPreviaExpressaoView(_FluxoEscopoView):
    """Prévia de expressão no editor (MV2-23, EDV-02). Só POST JSON com X-CSRFToken; fluxos.editar.

    Corpo: {"no_id", "campo", "expressao"}. Avalia com o interpretador do motor sobre os dados
    gravados da ÚLTIMA execução de teste deste fluxo feita por quem pede (item 0 da entrada do
    nó; `$('Título')` lê a saída gravada dos outros nós). Nunca executa nó, faz requisição nem
    roda Código. Saída mascarada (SEG-09/18/21). 200 {"ok": true, "valor", "texto",
    "itens_usados"} ou {"ok": false, "erro"}; mais de 30 prévias por minuto → 429.
    """

    acao_requerida = "fluxos.editar"
    http_method_names = ["post", "options"]

    def _limitar(self, usuario):
        chave = f"previa_expressao:{usuario.pk}"
        cache.add(chave, 0, timeout=60)
        try:
            return cache.incr(chave) <= PREVIAS_POR_MINUTO
        except ValueError:
            cache.set(chave, 1, timeout=60)
            return True

    def post(self, request, pk):
        fluxo = self.obter(pk)
        if not self._limitar(request.user):
            return JsonResponse(
                {"ok": False, "erro": "Muitas prévias seguidas. Aguarde um minuto."}, status=429
            )
        try:
            corpo = json.loads(request.body or b"{}")
        except ValueError, RecursionError:
            corpo = None
        if not (
            isinstance(corpo, dict)
            and isinstance(corpo.get("no_id"), str)
            and isinstance(corpo.get("campo"), str)
            and isinstance(corpo.get("expressao"), str)
        ):
            return JsonResponse(
                {"ok": False, "erro": "Envie no_id, campo e expressao em texto."}, status=400
            )
        expressao = corpo["expressao"]
        if len(expressao) > MAX_EXPRESSAO_PREVIA:
            return JsonResponse({"ok": False, "erro": "A expressão passa de 2.000 caracteres."})
        execucao = (
            Execucao.objects.filter(fluxo=fluxo, executado_por=request.user, teste=True)
            .order_by("-iniciada_em", "-pk")
            .first()
        )
        if execucao is None:
            return JsonResponse({"ok": False, "erro": MSG_SEM_TESTE})
        nos = list(execucao.nos.all())
        alvo = next((n for n in nos if n.no_id == corpo["no_id"]), None)
        if alvo is None:
            return JsonResponse({"ok": False, "erro": MSG_SEM_TESTE})
        entrada = alvo.entrada if isinstance(alvo.entrada, list) else []
        item = entrada[0] if entrada and isinstance(entrada[0], dict) else {"json": {}}
        escopo = Escopo(
            item=item,
            indice=0,
            entrada=entrada,
            resultados={n.no_titulo: n.saida for n in nos if isinstance(n.saida, list)},
            agora=execucao.iniciada_em,
            execucao_id=execucao.pk,
            fluxo_nome=fluxo.nome,
            usuario_email=request.user.email,
            parametros={},
        )
        try:
            valor = resolver_valor(expressao, escopo)
            texto = resolver_texto(expressao, escopo)
        except ErroExpressao as erro:
            return JsonResponse({"ok": False, "erro": erro.mensagem})
        return JsonResponse(
            {
                "ok": True,
                "valor": mascarar.mascarar_itens(valor),
                "texto": mascarar.mascarar_itens(texto),
                "itens_usados": len(entrada),
            }
        )
