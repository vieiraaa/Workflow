import copy
import json
from urllib.parse import urlencode

from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.contas.models import Setor
from apps.contas.permissoes import PermissaoMixin, escopo, pode
from apps.execucoes import apresentacao as apres_exec
from apps.execucoes.models import LIMITE_EXECUTANDO, Execucao, ExecucaoNo
from apps.fluxos.models import Fluxo
from apps.motor import executor
from apps.motor.erros import FluxoComPendencias
from apps.nucleo.entrada import limpar_texto

from . import apresentacao
from . import entradas as ent
from .forms import FuncaoForm
from .models import ICONES, PAPEIS_LIBERAVEIS, Funcao


class CatalogoView(PermissaoMixin, TemplateView):
    """Catálogo de Funções (TEL-23; FUN-01, FUN-02). Template `funcoes/catalogo.html`.

    Querystring: `q` (nome ou descrição). Escopo `liberadas` pelo motor, aplicado no banco; queries
    constantes. "Sua última execução" é sempre a do próprio usuário (modo para_mim, FUN-10).

    Contexto (além do shell):
    - `funcoes`: lista de dicts {pk, nome, descricao, icone, rascunho (versao 0), inativa,
      tem_entradas, ultima {quando ('há 3 h'), status, rotulo, url} | None, url_executar,
      url_editar, url_publicar, url_alternar}. `url_executar` é '' para rascunho/inativa (o botão
      não deve aparecer); `url_editar/publicar/alternar` só vêm preenchidas para o Adm.
    - `pode_gerenciar` (bool: Adm), `url_nova` ('' sem permissão), `q`
    """

    acao_requerida = "funcoes.ver"
    template_name = "funcoes/catalogo.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        usuario = self.request.user
        pode_gerenciar = pode(usuario, "funcoes.gerenciar")
        q = limpar_texto(self.request.GET.get("q", ""))
        qs = escopo(usuario, Funcao.objects, "funcoes.ver")
        if q:
            qs = qs.filter(Q(nome__icontains=q) | Q(descricao__icontains=q))
        funcoes = list(qs.order_by("nome", "pk"))
        ultimas = {
            e.funcao_id: e
            for e in Execucao.objects.filter(
                funcao__in=[f.pk for f in funcoes], executado_por=usuario, modo=Execucao.PARA_MIM
            )
            .order_by("funcao_id", "-iniciada_em", "-pk")
            .distinct("funcao_id")
        }
        agora = timezone.now()
        linhas = []
        for f in funcoes:
            e = ultimas.get(f.pk)
            executavel = f.publicada and f.ativa
            linhas.append(
                {
                    "pk": f.pk,
                    "nome": f.nome,
                    "descricao": f.descricao,
                    "icone": f.icone,
                    "rascunho": not f.publicada,
                    "inativa": not f.ativa,
                    "tem_entradas": bool(f.entradas),
                    "ultima": {
                        "quando": apresentacao.quando_relativo(e.iniciada_em, agora),
                        "status": e.status_efetivo,
                        "rotulo": e.status_rotulo,
                        "url": reverse("funcoes:resultado", kwargs={"pk": e.pk}),
                    }
                    if e
                    else None,
                    "url_executar": reverse("funcoes:executar", kwargs={"pk": f.pk})
                    if executavel
                    else "",
                    "url_editar": reverse("funcoes:editar", kwargs={"pk": f.pk})
                    if pode_gerenciar
                    else "",
                    "url_publicar": reverse("funcoes:publicar", kwargs={"pk": f.pk})
                    if pode_gerenciar
                    else "",
                    "url_alternar": reverse("funcoes:alternar", kwargs={"pk": f.pk})
                    if pode_gerenciar
                    else "",
                }
            )
        contexto.update(
            funcoes=linhas,
            pode_gerenciar=pode_gerenciar,
            url_nova=reverse("funcoes:nova") if pode_gerenciar else "",
            q=q,
        )
        return contexto


class _FormularioFuncaoView(PermissaoMixin, TemplateView):
    acao_requerida = "funcoes.gerenciar"
    template_name = "funcoes/form.html"
    funcao = None

    def _contexto_form(self, form):
        if form.is_bound:
            marcados = {str(v) for v in form.data.getlist("setores")}
            papeis = set(form.data.getlist("papeis"))
            entradas_json = form.data.get("entradas", "[]")
        else:
            marcados = {str(v) for v in form.initial.get("setores", [])}
            papeis = set(form.initial.get("papeis", []))
            entradas_json = form.initial.get("entradas", "[]")
        return {
            "form": form,
            "funcao": self.funcao,
            "entradas_json": entradas_json,
            "setores": [
                {"pk": s.pk, "nome": s.nome, "marcado": str(s.pk) in marcados}
                for s in Setor.objects.order_by("nome")
            ],
            "papeis": [
                {"valor": v, "rotulo": r, "marcado": v in papeis} for v, r in PAPEIS_LIBERAVEIS
            ],
            "icones": ICONES,
            "fluxos": Fluxo.objects.order_by("nome", "pk"),
        }

    def _bad_request(self, dados):
        for chave in dados:
            for valor in dados.getlist(chave):
                if "\x00" in valor or _surrogate(valor):
                    return True
        return False

    def get(self, request, *args, **kwargs):
        form = FuncaoForm(instance=self.funcao)
        return self.render_to_response(self.get_context_data(**self._contexto_form(form)))

    def post(self, request, *args, **kwargs):
        if self._bad_request(request.POST):
            return HttpResponseBadRequest("Requisição inválida.")
        form = FuncaoForm(request.POST, instance=self.funcao)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(**self._contexto_form(form)))
        form.salvar(request.user)
        messages.success(request, "Função salva.")
        return redirect("funcoes:catalogo")


def _surrogate(texto):
    try:
        texto.encode("utf-8")
    except UnicodeEncodeError:
        return True
    return False


class FuncaoNovaView(_FormularioFuncaoView):
    """Nova função (TEL-24; FUN-03). Só Adm (`funcoes.gerenciar`); salvar NÃO publica.

    Contexto (além do shell): `form` (nome, descricao, icone, fluxo, liberar_para, setores,
    papeis, entradas, ativa; erros por campo), `entradas_json` (str; JSON da lista de entradas),
    `setores` [{pk, nome, marcado}], `papeis` [{valor, rotulo, marcado}], `icones` (lista de str),
    `funcao` (None). POST válido → redirect para `funcoes:catalogo` com "Função salva.";
    inválido → 200 com os erros.
    """


class FuncaoEditarView(_FormularioFuncaoView):
    """Editar função (TEL-24; FUN-03). Mesmo contexto de `FuncaoNovaView`, com `funcao` preenchida
    (objeto Funcao). Trocar o fluxo mantém a versão publicada até a próxima publicação."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and pode(request.user, "funcoes.gerenciar"):
            self.funcao = get_object_or_404(Funcao, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)


class _AcaoNaFuncaoView(PermissaoMixin, View):
    acao_requerida = "funcoes.gerenciar"
    http_method_names = ["post", "options"]

    def post(self, request, pk):
        funcao = get_object_or_404(Funcao, pk=pk)
        self.aplicar(request, funcao)
        return redirect("funcoes:catalogo")


class FuncaoPublicarView(_AcaoNaFuncaoView):
    """Publicar nova versão (FUN-04). Só POST + CSRF, só Adm. Valida o grafo ATUAL do fluxo; com
    pendência nada muda ("Não dá para publicar: o fluxo tem pendências. Corrija no editor.").
    Ok: grafo_publicado = cópia do grafo, versao += 1 ("Versão N publicada."). Sempre redirect
    para `funcoes:catalogo`."""

    def aplicar(self, request, funcao):
        grafo = copy.deepcopy(funcao.fluxo.grafo)
        if executor.pendencias_do_grafo(grafo):
            messages.error(
                request, "Não dá para publicar: o fluxo tem pendências. Corrija no editor."
            )
            return
        funcao.grafo_publicado = grafo
        funcao.versao += 1
        funcao.publicada_em = timezone.now()
        funcao.publicada_por = request.user
        funcao.save(
            update_fields=[
                "grafo_publicado",
                "versao",
                "publicada_em",
                "publicada_por",
                "atualizada_em",
            ]
        )
        messages.success(request, f"Versão {funcao.versao} publicada.")


class FuncaoAlternarView(_AcaoNaFuncaoView):
    """Ativar/desativar (FUN-04). Só POST + CSRF, só Adm. Redirect para `funcoes:catalogo`."""

    def aplicar(self, request, funcao):
        funcao.ativa = not funcao.ativa
        funcao.save(update_fields=["ativa", "atualizada_em"])
        messages.success(request, "Função ativada." if funcao.ativa else "Função desativada.")


def _ruim(valor):
    return "\x00" in valor or _surrogate(valor)


def _em_andamento(funcao, usuario):
    return Execucao.objects.filter(
        funcao=funcao,
        executado_por=usuario,
        modo=Execucao.PARA_MIM,
        status=Execucao.EXECUTANDO,
        iniciada_em__gte=timezone.now() - LIMITE_EXECUTANDO,
    ).exists()


class FuncaoExecutarView(PermissaoMixin, TemplateView):
    """Executar função (TEL-25; FUN-06, FUN-07, FUN-12). Template `funcoes/executar.html`.

    404 se a função está fora do escopo (liberadas), inativa ou nunca publicada (vale para o Adm).
    GET mostra o formulário; `?<nome>=<valor>` pré-preenche (usado por "Executar de novo"). POST
    valida (FUN-07) e executa de forma síncrona (grafo publicado, modo para_mim); sucesso ou
    erro → redirect para `funcoes:resultado`. Já em execução para o mesmo usuário → redirect ao
    catálogo com aviso. Pendência no grafo → redirect ao catálogo com mensagem de erro.

    Contexto (além do shell): `funcao` (objeto Funcao), `campos` [{nome, rotulo, tipo
    (texto|numero|data|booleano|lista), valor (o que a pessoa digitou; booleano True/False; data
    'AAAA-MM-DD'), opcoes, obrigatoria, erro ('' sem erro)}], `erros_gerais` (lista de str).
    Erro de validação → 200 com o formulário, sem execução. NUL/surrogate → 400.
    """

    acao_requerida = "funcoes.executar"
    template_name = "funcoes/executar.html"

    def _funcao(self, pk):
        funcao = get_object_or_404(self.escopo_queryset(Funcao.objects), pk=pk)
        if not (funcao.ativa and funcao.publicada):
            raise Http404
        return funcao

    @staticmethod
    def _campos(funcao, valores=None, erros=None):
        valores, erros = valores or {}, erros or {}
        campos = []
        for e in funcao.entradas:
            nome = e["nome"]
            valor = valores[nome] if nome in valores else ent.padrao_resolvido(e)
            if e["tipo"] == "booleano":
                valor = valor is True or str(valor).lower() in ("true", "on", "1", "sim")
            elif valor is None:
                valor = ""
            campos.append(
                {
                    "nome": nome,
                    "rotulo": e["rotulo"],
                    "tipo": e["tipo"],
                    "valor": valor,
                    "opcoes": e.get("opcoes", []),
                    "obrigatoria": e["obrigatoria"],
                    "erro": erros.get(nome, ""),
                }
            )
        return campos

    def get(self, request, pk):
        funcao = self._funcao(pk)
        nomes = {e["nome"] for e in funcao.entradas}
        enviados = {k: v for k, v in request.GET.items() if k in nomes and not _ruim(v)}
        campos = self._campos(funcao, enviados)
        return self.render_to_response(
            self.get_context_data(funcao=funcao, campos=campos, erros_gerais=[])
        )

    def post(self, request, pk):
        funcao = self._funcao(pk)
        if any(_ruim(v) for k in request.POST for v in request.POST.getlist(k)):
            return HttpResponseBadRequest("Requisição inválida.")
        valores, erros = ent.validar_valores(funcao.entradas, request.POST)
        if erros:
            digitados = {e["nome"]: request.POST.get(e["nome"], "") for e in funcao.entradas}
            return self.render_to_response(
                self.get_context_data(
                    funcao=funcao,
                    campos=self._campos(funcao, digitados, erros),
                    erros_gerais=list(erros.values()),
                )
            )
        if _em_andamento(funcao, request.user):
            messages.error(request, "Esta função já está em execução para você. Aguarde terminar.")
            return redirect("funcoes:catalogo")
        try:
            execucao = executor.executar_funcao(funcao, request.user, valores)
        except FluxoComPendencias:
            messages.error(request, "Não foi possível executar: a função tem pendências.")
            return redirect("funcoes:catalogo")
        if execucao.status == Execucao.SUCESSO:
            messages.success(request, "Execução concluída.")
        else:
            messages.error(request, "A execução terminou com erro.")
        return redirect("funcoes:resultado", pk=execucao.pk)


def _celula(valor):
    if isinstance(valor, dict | list):
        return json.dumps(valor, ensure_ascii=False)
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    return str(valor)


def _valor_parametro(valor):
    if valor is None or valor == "":
        return "—"
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    return str(valor)


class FuncaoResultadoView(PermissaoMixin, TemplateView):
    """Resultado de execução de função (TEL-26; FUN-09, FUN-10). Template `funcoes/resultado.html`.

    404 se a execução não é de função (modo para_mim) ou não é do usuário (só o executor e o
    Adm). Nada de canvas, grafo, requisições, logs ou nós intermediários.

    Contexto (além do shell):
    - `funcao`: {nome, icone}
    - `execucao`: {pk, status (efetivo), status_rotulo, iniciada_em, duracao_texto, funcao_versao}
    - `parametros`: [{rotulo, valor}] (texto; "Sim"/"Não", "—" quando vazio)
    - `colunas` (chaves do 1º nível do resultado, máx. 20), `linhas` (lista de listas de str, máx.
      200), `total_itens` (itens da saída do último nó executado com sucesso)
    - `erro`: {categoria (rótulo), mensagem} ou None
    - `url_detalhe`: execução técnica, só para o Adm ('' para os demais)
    - `url_executar_de_novo`: formulário com os mesmos parâmetros ('' se a função não pode mais
      ser executada por este usuário)
    """

    acao_requerida = "funcoes.ver"
    template_name = "funcoes/resultado.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        usuario = self.request.user
        execucao = get_object_or_404(
            escopo(usuario, Execucao.objects, "execucoes.ver").filter(
                modo=Execucao.PARA_MIM, teste=False
            ),
            pk=self.kwargs["pk"],
        )
        funcao = execucao.funcao
        rotulos = {e["nome"]: e["rotulo"] for e in (funcao.entradas if funcao else [])}
        parametros = [
            {"rotulo": rotulos.get(nome, nome), "valor": _valor_parametro(valor)}
            for nome, valor in (execucao.parametros or {}).items()
        ]
        nos = sorted(execucao.nos.all(), key=lambda n: n.ordem, reverse=True)
        colunas, linhas, total, erro = [], [], 0, None
        if execucao.status_efetivo == Execucao.ERRO:
            falho = next((n for n in nos if n.status == ExecucaoNo.ERRO), None)
            erro = {
                "categoria": apres_exec.ROTULOS_ERRO.get(
                    getattr(falho, "erro_categoria", "") or "", "Erro"
                ),
                "mensagem": falho.erro_mensagem if falho else execucao.erro_resumo_efetivo,
            }
        else:
            ultimo = next(
                (
                    n
                    for n in nos
                    if n.status in (ExecucaoNo.SUCESSO, ExecucaoNo.FIXO, ExecucaoNo.DESATIVADO)
                ),
                None,
            )
            if ultimo is not None and isinstance(ultimo.saida, list):
                itens = [i.get("json") for i in ultimo.saida if isinstance(i, dict)]
                itens = [i if isinstance(i, dict) else {} for i in itens][:200]
                total = ultimo.itens_saida
                for dados in itens:
                    for chave in dados:
                        if chave not in colunas and len(colunas) < 20:
                            colunas.append(chave)
                linhas = [[_celula(d.get(c)) for c in colunas] for d in itens]
        consulta = urlencode(
            {
                k: "on" if v is True else v
                for k, v in (execucao.parametros or {}).items()
                if v is not None and v is not False
            }
        )
        url_de_novo = ""
        if (
            funcao
            and funcao.ativa
            and funcao.publicada
            and pode(usuario, "funcoes.executar", funcao)
        ):
            url_de_novo = reverse("funcoes:executar", kwargs={"pk": funcao.pk})
            url_de_novo += f"?{consulta}" if consulta else ""
        contexto.update(
            funcao={"nome": execucao.funcao_nome, "icone": funcao.icone if funcao else "zap"},
            execucao={
                "pk": execucao.pk,
                "status": execucao.status_efetivo,
                "status_rotulo": execucao.status_rotulo,
                "iniciada_em": execucao.iniciada_em,
                "duracao_texto": apres_exec.duracao_texto(execucao.duracao_ms),
                "funcao_versao": execucao.funcao_versao,
            },
            parametros=parametros,
            colunas=colunas,
            linhas=linhas,
            total_itens=total,
            erro=erro,
            url_detalhe=reverse("execucoes:detalhe", kwargs={"pk": execucao.pk})
            if pode(usuario, "funcoes.gerenciar")
            else "",
            url_executar_de_novo=url_de_novo,
        )
        return contexto
