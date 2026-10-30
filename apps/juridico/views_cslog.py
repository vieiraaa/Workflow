"""Exportação para o CSLOG (D-064, TEL-39): escolher processos e gerar o `processo.csv`.

O CSLOG não tem API de importação: o arquivo é gerado aqui e importado lá. Gerar só REGISTRA o
arquivo (ExportacaoCslog); o "lançado no CSLOG" que conta para concluído virá com a importação
oficial (ProcessoQuerySet.q_concluido).
"""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Max, Q
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.contas.permissoes import pode
from apps.nucleo import listagem
from apps.nucleo.entrada import limpar_texto

from . import apresentacao, cslog
from .models import ExportacaoCslog, Processo
from .views import CadastroMixin, Item, SoPost

POR_PAGINA = 50  # lote de exportação: mais que as 25 das listagens comuns (D-064)
MAX_POR_ARQUIVO = 500
SITUACOES = {"": "Sem CSV", "gerados": "CSV gerado", "todos": "Todos"}
SESSAO_BAIXAR = "cslog_baixar"


def _ids(request):
    return [int(v) for v in request.POST.getlist("ids") if v.isascii() and v.isdigit()]


def _linha(p):
    sugerida, motivo = cslog.sugerir_tipo(p)
    escolhida = p.cslog_tipo if p.cslog_tipo in cslog.POR_CHAVE else sugerida
    return Item(
        {
            "pk": p.pk,
            "numero": p.numero,
            "autor": p.adverso_nome,
            "cpf": cslog.documento(p.adverso_cpf_cnpj),
            "comarca": p.comarca,
            "uf": cslog.uf(p),
            "classe": p.tipo_acao,
            "tipo": escolhida,
            "tipo_motivo": "escolhido na última exportação" if escolhida != sugerida else motivo,
            "faltando": cslog.faltando(p),
            "bloqueio": cslog.bloqueio(p),
            "ultimo_csv": apresentacao.data_hora(p.ultimo_csv) if p.ultimo_csv else "",
            "url_detalhe": reverse("juridico:processo", kwargs={"pk": p.pk}),
        }
    )


class CslogView(CadastroMixin, TemplateView):
    """CSLOG (TEL-39; D-064). Template `juridico/cslog.html`. Contexto:
    `processos` [{pk, numero, autor, cpf, comarca, uf, classe, tipo (chave de cslog.TIPOS),
    tipo_motivo, faltando [rótulos], bloqueio ('' = pode entrar no CSV), ultimo_csv
    ('DD/MM/AAAA HH:MM' ou ''), url_detalhe}], `page_obj`, `consulta`, `q`, `situacao`
    (''|gerados|todos), `filtros_situacao` [{rotulo, url, ativo}], `tipos_grupos`
    [(grupo, [(chave, rótulo)])], `pode_gerar`, `url_gerar`, `arquivos` [{pk, quando, por,
    quantidade, url}] (os 10 últimos), `baixar_url` (o arquivo recém-gerado, baixado sozinho),
    `colunas` (cabeçalho do processo.csv). Queries constantes."""

    template_name = "juridico/cslog.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        get = self.request.GET
        q = limpar_texto(get.get("q", ""))[:100]
        situacao = get.get("situacao", "")
        situacao = situacao if situacao in SITUACOES else ""
        qs = Processo.objects.annotate(ultimo_csv=Max("exportacoes_cslog__gerado_em"))
        if q:
            digitos = "".join(c for c in q if c.isdigit())
            filtro = Q(numero__icontains=q) | Q(adverso_nome__icontains=q)
            if len(digitos) >= 4:  # parte do número CNJ, não um dígito solto
                filtro |= Q(numero_digitos__contains=digitos)
            qs = qs.filter(filtro)
        if situacao == "":
            qs = qs.filter(ultimo_csv__isnull=True)
        elif situacao == "gerados":
            qs = qs.filter(ultimo_csv__isnull=False)
        qs = qs.order_by("-criado_em", "-pk")
        page_obj = listagem.pagina_valida(Paginator(qs, POR_PAGINA), get.get("pagina"))
        parametros = {"q": q, "situacao": situacao}
        base = reverse("juridico:cslog")
        contexto.update(
            processos=[_linha(p) for p in page_obj.object_list],
            page_obj=page_obj,
            consulta=(listagem.consulta(parametros) + "&") if any(parametros.values()) else "",
            q=q,
            situacao=situacao,
            filtros_situacao=[
                {
                    "rotulo": rotulo,
                    "url": f"{base}?{listagem.consulta(parametros, situacao=chave)}",
                    "ativo": chave == situacao,
                }
                for chave, rotulo in SITUACOES.items()
            ],
            tipos_grupos=cslog.grupos_para_select(),
            pode_gerar=pode(self.request.user, "cadastro.editar"),
            url_gerar=reverse("juridico:cslog_gerar"),
            arquivos=[
                Item(
                    {
                        "pk": e.pk,
                        "quando": apresentacao.data_hora(e.gerado_em),
                        "por": (e.gerado_por.nome or e.gerado_por.email)
                        if e.gerado_por_id
                        else "um usuário removido",
                        "quantidade": e.quantidade,
                        "url": reverse("juridico:cslog_baixar", kwargs={"pk": e.pk}),
                    }
                )
                for e in ExportacaoCslog.objects.select_related("gerado_por")[:10]
            ],
            baixar_url=self._baixar_url(),
            colunas=cslog.COLUNAS,
        )
        return contexto

    def _baixar_url(self):
        pk = self.request.session.pop(SESSAO_BAIXAR, None)
        return reverse("juridico:cslog_baixar", kwargs={"pk": pk}) if pk else ""


class CslogGerarView(SoPost):
    """POST `ids` (processos marcados) + `tipo_<pk>` (chave do tipo de ação no CSLOG) → grava a
    ExportacaoCslog e volta para a tela, que baixa o arquivo sozinha. Exige `cadastro.editar`.
    Processo sem número válido ou sem CPF/CNPJ do autor fica fora (com aviso)."""

    acao_requerida = "cadastro.editar"

    def post(self, request):
        voltar = redirect(f"{reverse('juridico:cslog')}?{request.POST.get('consulta', '')}")
        ids = _ids(request)
        if not ids:
            messages.error(request, "Selecione pelo menos um processo.")
            return voltar
        if len(ids) > MAX_POR_ARQUIVO:
            messages.error(request, f"Selecione no máximo {MAX_POR_ARQUIVO} processos por arquivo.")
            return voltar
        login = cslog.login_do_usuario(request.user)
        linhas, incluidos, fora = [], [], []
        for p in Processo.objects.filter(pk__in=ids).order_by("pk"):
            if cslog.bloqueio(p):
                fora.append(p.numero or f"#{p.pk}")
                continue
            tipo = request.POST.get(f"tipo_{p.pk}", "")
            if tipo not in cslog.POR_CHAVE:
                tipo = cslog.sugerir_tipo(p)[0]
            p.cslog_tipo = tipo
            linhas.append(cslog.linha(p, tipo, login))
            incluidos.append(p)
        if not incluidos:
            messages.error(
                request, "Nenhum processo selecionado tem número CNJ válido e CPF/CNPJ do autor."
            )
            return voltar
        with transaction.atomic():
            Processo.objects.bulk_update(incluidos, ["cslog_tipo"])
            exportacao = ExportacaoCslog.objects.create(
                arquivo=cslog.ARQUIVO_PROCESSO,
                gerado_por=request.user,
                quantidade=len(incluidos),
                conteudo=cslog.gerar_csv(linhas),
            )
            exportacao.processos.set(incluidos)
        request.session[SESSAO_BAIXAR] = exportacao.pk
        texto = f"{cslog.ARQUIVO_PROCESSO} gerado com {len(incluidos)} processo"
        texto += "s." if len(incluidos) != 1 else "."
        if fora:
            texto += f" Ficaram fora (sem número válido ou CPF/CNPJ): {', '.join(fora[:5])}"
            texto += "…" if len(fora) > 5 else "."
        messages.success(request, texto)
        return voltar


class CslogBaixarView(CadastroMixin, View):
    """GET: o arquivo de uma ExportacaoCslog, como foi gerado (anexo, UTF-8 com BOM)."""

    def get(self, request, pk):
        exportacao = ExportacaoCslog.objects.filter(pk=pk).first()
        if exportacao is None:
            raise Http404
        resposta = HttpResponse(
            exportacao.conteudo.encode(cslog.CODIFICACAO), content_type="text/csv; charset=utf-8"
        )
        nome = f"{timezone.localtime(exportacao.gerado_em):%Y%m%d-%H%M}-{exportacao.arquivo}"
        resposta["Content-Disposition"] = f'attachment; filename="{nome}"'
        resposta["Cache-Control"] = "no-store"
        return resposta
