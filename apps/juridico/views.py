"""Views do cadastro de processos (M8, CAD-01..23). Cada view documenta o CONTEXTO que o template
recebe (contrato Back↔Front). Mutação só por POST + CSRF → redirect + messages.

Escopo (CAD-02): `cadastro.*` com escopo `setor_com_acesso`; sem acesso → 403. O cadastro é do
escritório (todos os processos aparecem a quem tem acesso); o detalhe de Envio/Item é só de quem
enviou e do Adm (outro usuário → 404).
"""

from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, F, Q, Value
from django.db.models.functions import Replace, TruncDate
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.contas.models import Setor
from apps.contas.permissoes import PermissaoMixin, pode
from apps.credenciais.models import Credencial
from apps.nucleo import listagem
from apps.nucleo.entrada import limpar_texto

from . import apresentacao, cnj, mescla, servico
from .clientes import DataJud, Dify, ErroCliente
from .forms import GRUPOS, CarteiraForm, ConfigForm, ProcessoForm
from .models import Carteira, ConfigCadastro, Envio, ItemEnvio, Processo
from .processamento import aviso_existente, consultar_cnj, procurar_existente, travar_numero

ORDENS = {"": "-atualizado_em", "numero": "numero_digitos", "distribuido": "-distribuido_em"}
ROTULOS_ORIGEM = {"pdf": "PDF", "cnj": "CNJ"}


def _so_digitos_sql(campo):
    """Expressão SQL: o campo sem pontuação (busca de CPF/CNPJ só por dígitos)."""
    expressao = F(campo)
    for caractere in ".-/ ":
        expressao = Replace(expressao, Value(caractere), Value(""))
    return expressao


def _pct(parte, total):
    """Percentual inteiro com arredondamento half up (CAD-23 §9); total 0 → 0."""
    return (parte * 200 + total) // (2 * total) if total else 0


MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")
CAMPOS_OBRIGATORIOS = (
    ("numero", "Número"),
    ("tribunal", "Tribunal"),
    ("comarca", "Comarca"),
    ("juizo", "Juízo"),
    ("adverso_nome", "Adverso"),
    ("valor_causa", "Valor da causa"),
    ("distribuido_em", "Distribuído em"),
)
ACOES = {
    Processo.CONFERIR: "conferir",
    Processo.COM_PENDENCIAS: "pendencias",
    Processo.CADASTRADO: "cadastrado",
}


def _audiencia_da_ficha(p, agora):
    if not p.proxima_audiencia or p.proxima_audiencia < agora:
        return None
    quando = timezone.localtime(p.proxima_audiencia)
    return {
        "dia": f"{quando:%d}",
        "mes_ano": f"{MESES[quando.month - 1]} {quando.year}",
        "hora": f"{quando:%H:%M}",
        "tipo": f"Audiência de {p.proxima_audiencia_tipo}"
        if p.proxima_audiencia_tipo
        else "Audiência",
        "local": " · ".join(x for x in (p.comarca, p.juizo) if x),
    }


def _obrigatorios(p):
    """Os 7 campos obrigatórios com `ok` (numero ok = número válido; demais = preenchido)."""
    lista = []
    for campo, rotulo in CAMPOS_OBRIGATORIOS:
        valor = getattr(p, campo)
        ok = p.numero_valido if campo == "numero" else valor not in (None, "", [])
        lista.append({"campo": campo, "rotulo": rotulo, "ok": bool(ok)})
    return lista


def _ficha(p, agora, pode_editar):
    """`selecionado` do painel v2 (CAD-25/27, CAD-23 §9): tudo calculado no servidor."""
    obrigatorios = _obrigatorios(p)
    item_pdf = (
        p.itens.filter(arquivo__isnull=False).exclude(arquivo="").order_by("-pk").only("pk").first()
    )
    processo = Item(
        {
            "pk": p.pk,
            "numero": p.numero,
            "status": p.status,
            "status_rotulo": p.status_rotulo,
            "carteira": p.carteira.nome if p.carteira_id else "",
            "tribunal": p.tribunal,
            "fase": p.get_fase_atual_display() if p.fase_atual else "",
            "empresa": p.empresa,
            "condicao": p.condicao,
            "adverso_nome": p.adverso_nome,
            "cpf_cnpj_mascarado": apresentacao.mascarar_documento(p.adverso_cpf_cnpj),
            "comarca": p.comarca,
            "juizo": p.juizo,
            "distribuido_em": apresentacao.data(p.distribuido_em),
            "valor_texto": apresentacao.valor_texto(p.valor_causa),
            "cadastrado_em": apresentacao.data(
                timezone.localtime(p.cadastrado_espaider_em) if p.cadastrado_espaider_em else None
            ),
            "pendencias": p.pendencias,
        }
    )
    chave = {"pk": p.pk}
    return Item(
        {
            "processo": processo,
            "cnj": cnj.decompor(p.numero),
            "obrigatorios": obrigatorios,
            "obrig_ok": sum(o["ok"] for o in obrigatorios),
            "acao": ACOES[p.status],
            "url_editar": reverse("juridico:processo", kwargs=chave),
            "url_pdf": reverse("juridico:pdf", kwargs={"pk": item_pdf.pk}) if item_pdf else None,
            "url_marcar": reverse("juridico:marcar_cadastrado", kwargs=chave),
            "audiencia": _audiencia_da_ficha(p, agora),
            "cnj_situacao": p.cnj_validacao,
            "cnj_info": {
                "situacao": p.cnj_validacao,
                "rotulo": p.get_cnj_validacao_display(),
                "divergencias": p.cnj_divergencias,
                "mensagem": p.cnj_mensagem,
                "consultado_em": apresentacao.data_hora(p.cnj_consultado_em),
            },
            "pode_editar": pode_editar,
            "pode_marcar": pode_editar and p.status == Processo.CONFERIR,
        }
    )


class Item(dict):
    """Dict que também responde por atributo (`item.pk`): o template usa as chaves e os testes e
    a docstring (contrato) usam `item.pk`."""

    def __getattr__(self, nome):
        try:
            return self[nome]
        except KeyError:
            raise AttributeError(nome) from None


def _plural(n, singular, plural):
    return f"{n} {singular if n == 1 else plural}"


def duracao_texto(segundos):
    if segundos is None:
        return ""
    total = int(round(segundos))
    if total < 60:
        return f"{total} s"
    return f"{total // 60} min {total % 60} s"


class CadastroMixin(PermissaoMixin):
    """Base: login + `cadastro.ver` por padrão (`acao_requerida`)."""

    acao_requerida = "cadastro.ver"

    def exigir(self, acao):
        if not pode(self.request.user, acao):
            raise PermissionDenied

    @property
    def adm(self):
        return pode(self.request.user, "cadastro.configurar")


class SoPost(CadastroMixin, View):
    http_method_names = ["post", "options"]


def _envios_visiveis(request):
    qs = Envio.objects.select_related("enviado_por", "carteira")
    return qs if pode(request.user, "cadastro.configurar") else qs.filter(enviado_por=request.user)


def _itens_visiveis(request):
    qs = ItemEnvio.objects.select_related("envio", "envio__enviado_por", "processo")
    if pode(request.user, "cadastro.configurar"):
        return qs
    return qs.filter(envio__enviado_por=request.user)


def _resumo(usuario):
    c = Processo.objects.aggregate(
        total=Count("pk"),
        com_pendencias=Count("pk", filter=Q(status=Processo.COM_PENDENCIAS)),
        conferir=Count("pk", filter=Q(status=Processo.CONFERIR)),
        cadastrados=Count("pk", filter=Q(status=Processo.CADASTRADO)),
    )
    pendentes = Q(status__in=[ItemEnvio.NA_FILA, ItemEnvio.PROCESSANDO])
    i = ItemEnvio.objects.aggregate(
        na_fila=Count("pk", filter=pendentes),
        erros=Count("pk", filter=Q(etapa_erro__isnull=False, resolvido=False)),
        em_andamento=Count("pk", filter=pendentes & Q(envio__enviado_por=usuario)),
    )
    c.update(na_fila=i["na_fila"], erros=i["erros"])
    return c, i["em_andamento"] > 0


def _url_envio(pk):
    return reverse("juridico:envio", kwargs={"pk": pk})


def _linha_envio(e):
    return Item(
        {
            "pk": e.pk,
            "quando": apresentacao.data_hora(e.criado_em),
            "origem": ROTULOS_ORIGEM.get(e.origem, e.origem),
            "casos": e.casos,
            "erros": e.erros,
            "duracao_texto": duracao_texto(e.duracao_s),
            "motivo": getattr(e, "motivo_resumo", "") or "",
            "url": _url_envio(e.pk),
        }
    )


def _envios_anotados(qs):
    return qs.annotate(
        casos=Count("itens"),
        erros=Count(
            "itens", filter=Q(itens__status=ItemEnvio.ERRO) | Q(itens__etapa_erro__isnull=False)
        ),
    )


def _com_motivo(envios):
    """Anexa o motivo do primeiro item com problema (uma consulta para a lista toda)."""
    envios = list(envios)
    motivos = {}
    for envio_id, motivo in (
        ItemEnvio.objects.filter(envio__in=envios, etapa_erro__isnull=False)
        .order_by("-pk")
        .values_list("envio_id", "motivo")
    ):
        motivos[envio_id] = motivo
    for e in envios:
        e.motivo_resumo = motivos.get(e.pk, "")
    return envios


# ---------------------------------------------------------------- painel (TEL-27)
class PainelView(CadastroMixin, TemplateView):
    """Painel de processos (TEL-27; CAD-16). Template `juridico/painel.html`. `cadastro.ver`.

    Querystring: `status` (COM_PENDENCIAS|CONFERIR|CADASTRADO), `carteira` (pk | 'outros'),
    `tribunal`, `cnj` (confere|divergente|nao_encontrado|falhou), `q` (número só dígitos, adverso,
    CPF/CNPJ, comarca, empresa), `ordem` ('' = atualizado | numero | distribuido), `p` (pk do
    processo selecionado; padrão o 1º da página), `pagina` (25 por página).

    Contexto (além do shell):
    - `resumo` {total, com_pendencias, conferir, cadastrados, na_fila, erros}
    - `carteiras` [{chave:'todos'|'outros'|<pk>, nome, total, ativa, ativo, url}]
    - `filtros` {status, carteira, tribunal, cnj, q, ordem}; `titulo_lista`
    - `processos`: Page de dicts {pk, numero, adverso, cpf_cnpj_mascarado, carteira, comarca,
      valor_texto, status, status_rotulo, cnj_situacao, audiencia_texto, audiencia_proxima,
      selecionado, url_painel, url_detalhe, url_excluir, pode_excluir}; `consulta`
    - `processo_sel`: {pk, numero, status, status_rotulo, carteira, tribunal, pendencias[],
      grupos[{titulo, campos[{rotulo, valor}]}] (CPF/CNPJ completo), andamentos[{data, evento,
      fonte}], url_detalhe, url_marcar, pode_marcar, pode_editar} ou None
    - `ultimos_envios` [{pk, quando, origem, casos, erros, duracao_texto, motivo, url}]
    - PAINEL v2 (CAD-24..27, acrescenta; nada removido): `fluxo` {em_leitura, erros_leitura,
      url_erros, com_pendencias, conferir, cadastrados, total, pct_cadastrados}; `clientes`
      [{pk (None=Todos, 'outros'=Outros), nome, total, cadastrados, pct, url, ativo}];
      `filtro_audiencia` (?audiencia=1); `atualizado_em` ('HH:MM'); `selecionado` (ficha: processo,
      cnj {valido, partes[{valor, legenda}], sigla}, obrigatorios[{campo, rotulo, ok}], obrig_ok,
      acao conferir|pendencias|cadastrado, url_editar, url_pdf|None, url_marcar, audiencia {dia,
      mes_ano, hora, tipo, local}|None, cnj_situacao, cnj_info); cada item de `processos` ganha
      `faltando`, `numero_sequencial`, `numero_resto`
    - `aviso_datajud` ('' ou texto, só Adm), `atualizar_auto` (bool), `url_status`
    - `audiencias_n`, `audiencias_urgente`; flags `pode_enviar`, `pode_editar`, `pode_configurar`;
      `url_enviar_pdfs`, `url_enviar_cnj`, `url_processo_novo`, `url_erros`, `url_envios`,
      `url_config`, `url_audiencias`
    """

    template_name = "juridico/painel.html"

    def _filtrar(self, qs, filtros):
        if filtros["status"] in dict(Processo.STATUS):
            qs = qs.filter(status=filtros["status"])
        carteira = filtros["carteira"]
        if carteira == "outros":
            qs = qs.filter(carteira__isnull=True)
        elif carteira.isascii() and carteira.isdigit():
            qs = qs.filter(carteira_id=int(carteira))
        if filtros["audiencia"]:
            qs = qs.filter(proxima_audiencia__gte=timezone.now())
        if filtros["tribunal"]:
            qs = qs.filter(tribunal__iexact=filtros["tribunal"])
        if filtros["cnj"] in dict(Processo.CNJ):
            qs = qs.filter(cnj_validacao=filtros["cnj"])
        q = filtros["q"]
        if q:
            condicao = (
                Q(adverso_nome__icontains=q)
                | Q(comarca__icontains=q)
                | Q(empresa__icontains=q)
                | Q(numero__icontains=q)
            )
            digitos = cnj.so_digitos(q)
            if digitos:
                qs = qs.annotate(doc_digitos=_so_digitos_sql("adverso_cpf_cnpj"))
                condicao |= Q(numero_digitos__icontains=digitos) | Q(doc_digitos__icontains=digitos)
            qs = qs.filter(condicao)
        return qs

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        request = self.request
        usuario = request.user
        pede = request.GET
        filtros = {
            "status": pede.get("status", "")
            if pede.get("status", "") in dict(Processo.STATUS)
            else "",
            "carteira": limpar_texto(pede.get("carteira", ""), 20),
            "tribunal": limpar_texto(pede.get("tribunal", ""), 20),
            "cnj": limpar_texto(pede.get("cnj", ""), 20),
            "q": limpar_texto(pede.get("q", "")),
            "ordem": pede.get("ordem", "") if pede.get("ordem", "") in ORDENS else "",
            "audiencia": "1" if pede.get("audiencia") == "1" else "",
        }
        resumo, atualizar = _resumo(usuario)

        def url(**trocas):
            return "?" + listagem.consulta({**filtros, "p": ""}, {}, **trocas)

        cadastrado = Q(status=Processo.CADASTRADO)
        por_carteira_cad = {
            c: (n, cad)
            for c, n, cad in Processo.objects.filter(carteira__isnull=False)
            .values_list("carteira_id")
            .annotate(n=Count("pk"), cad=Count("pk", filter=cadastrado))
            .values_list("carteira_id", "n", "cad")
        }
        por_carteira = {c: n for c, (n, _) in por_carteira_cad.items()}
        sem_carteira_agregado = Processo.objects.filter(carteira__isnull=True).aggregate(
            n=Count("pk"), cad=Count("pk", filter=cadastrado)
        )
        carteiras = [
            {"chave": "todos", "nome": "Todos", "total": resumo["total"], "ativa": True,
             "ativo": not filtros["carteira"], "url": url(carteira="")}
        ]  # fmt: skip
        nomes = {}
        for c in Carteira.objects.filter(ativa=True).order_by("nome"):
            nomes[str(c.pk)] = c.nome
            carteiras.append(
                {"chave": c.pk, "nome": c.nome, "total": por_carteira.get(c.pk, 0), "ativa": True,
                 "ativo": filtros["carteira"] == str(c.pk), "url": url(carteira=c.pk)}
            )  # fmt: skip
        sem_carteira = sem_carteira_agregado["n"]
        carteiras.append(
            {"chave": "outros", "nome": "Outros", "total": sem_carteira, "ativa": True,
             "ativo": filtros["carteira"] == "outros", "url": url(carteira="outros")}
        )  # fmt: skip
        nome_carteira = (
            "Outros" if filtros["carteira"] == "outros" else nomes.get(filtros["carteira"], "Todos")
        )

        qs = self._filtrar(
            Processo.objects.select_related("carteira").order_by(ORDENS[filtros["ordem"]], "-pk"),
            filtros,
        )
        paginator = Paginator(qs, listagem.POR_PAGINA)
        pagina = listagem.pagina_valida(paginator, pede.get("pagina") or pede.get("page") or 1)
        pode_editar = pode(usuario, "cadastro.editar")
        objetos = list(pagina.object_list)
        escolhido = next((o for o in objetos if str(o.pk) == pede.get("p", "")), None)
        if escolhido is None and (pede.get("p", "").isascii() and pede.get("p", "").isdigit()):
            escolhido = qs.filter(pk=int(pede["p"])).first()
        escolhido = escolhido or (objetos[0] if objetos else None)
        agora = timezone.now()
        linhas = []
        for o in objetos:
            linhas.append(
                Item(
                    {
                        "pk": o.pk,
                        "numero": o.numero,
                        "numero_sequencial": o.numero[:7] if o.numero_valido else "",
                        "numero_resto": o.numero[7:] if o.numero_valido else o.numero,
                        "faltando": sum(not x["ok"] for x in _obrigatorios(o)),
                        "adverso": o.adverso_nome,
                        "cpf_cnpj_mascarado": apresentacao.mascarar_documento(o.adverso_cpf_cnpj),
                        "carteira": o.carteira.nome if o.carteira_id else "",
                        "comarca": o.comarca,
                        "valor_texto": apresentacao.valor_texto(o.valor_causa),
                        "status": o.status,
                        "status_rotulo": o.status_rotulo,
                        "cnj_situacao": o.cnj_validacao,
                        "audiencia_texto": apresentacao.data_hora(o.proxima_audiencia)
                        if o.proxima_audiencia and o.proxima_audiencia >= agora
                        else "",
                        "audiencia_proxima": bool(
                            o.proxima_audiencia
                            and agora <= o.proxima_audiencia <= agora + timedelta(days=7)
                        ),
                        "selecionado": escolhido is not None and o.pk == escolhido.pk,
                        "url_painel": url(p=o.pk, pagina=pede.get("pagina", "")),
                        "url_detalhe": reverse("juridico:processo", kwargs={"pk": o.pk}),
                        "url_excluir": reverse("juridico:excluir", kwargs={"pk": o.pk}),
                        "pode_excluir": pode_editar,
                    }
                )
            )
        pagina.object_list = linhas
        audiencias = Processo.objects.filter(proxima_audiencia__gte=agora)
        proximas = audiencias.filter(proxima_audiencia__lte=agora + timedelta(days=7)).exists()
        ultimos = _com_motivo(
            _envios_anotados(_envios_visiveis(request)).order_by("-criado_em")[:5]
        )
        config = ConfigCadastro.obter()

        def url_cliente(carteira):
            base = {"status": filtros["status"], "audiencia": filtros["audiencia"]}
            return "?" + listagem.consulta({**base, "carteira": carteira}, {})

        clientes = [
            {"pk": None, "nome": "Todos", "total": resumo["total"],
             "cadastrados": resumo["cadastrados"],
             "pct": _pct(resumo["cadastrados"], resumo["total"]),
             "url": url_cliente(""), "ativo": not filtros["carteira"]}
        ]  # fmt: skip
        for c in Carteira.objects.filter(ativa=True).order_by("nome"):
            total_c, cad_c = por_carteira_cad.get(c.pk, (0, 0))
            clientes.append(
                {"pk": c.pk, "nome": c.nome, "total": total_c, "cadastrados": cad_c,
                 "pct": _pct(cad_c, total_c), "url": url_cliente(c.pk),
                 "ativo": filtros["carteira"] == str(c.pk)}
            )  # fmt: skip
        clientes.append(
            {"pk": "outros", "nome": "Outros", "total": sem_carteira_agregado["n"],
             "cadastrados": sem_carteira_agregado["cad"],
             "pct": _pct(sem_carteira_agregado["cad"], sem_carteira_agregado["n"]),
             "url": url_cliente("outros"), "ativo": filtros["carteira"] == "outros"}
        )  # fmt: skip
        erros_leitura = ItemEnvio.objects.filter(
            etapa_erro__in=("Leitura do PDF", "Envio do PDF"), resolvido=False
        ).count()
        fluxo = {
            "em_leitura": resumo["na_fila"],
            "erros_leitura": erros_leitura,
            "url_erros": reverse("juridico:erros"),
            "com_pendencias": resumo["com_pendencias"],
            "conferir": resumo["conferir"],
            "cadastrados": resumo["cadastrados"],
            "total": resumo["total"],
            "pct_cadastrados": _pct(resumo["cadastrados"], resumo["total"]),
        }
        contexto.update(
            fluxo=fluxo,
            clientes=clientes,
            filtro_audiencia=bool(filtros["audiencia"]),
            atualizado_em=timezone.localtime(agora).strftime("%H:%M"),
            selecionado=_ficha(escolhido, agora, pode_editar) if escolhido else None,
            resumo=resumo,
            carteiras=carteiras,
            filtros=filtros,
            titulo_lista=f"Processos · {nome_carteira}",
            processos=pagina,
            page_obj=pagina,
            consulta=listagem.consulta(filtros, {}),
            processo_sel=self._selecionado(escolhido, pode_editar) if escolhido else None,
            ultimos_envios=[_linha_envio(e) for e in ultimos],
            aviso_datajud=(
                "Chave do DataJud recusada: atualize a credencial em Configuração."
                if self.adm and config.datajud_recusado_em
                else ""
            ),
            atualizar_auto=atualizar,
            url_status=reverse("juridico:status"),
            audiencias_n=audiencias.count(),
            audiencias_urgente=proximas,
            pode_enviar=pode(usuario, "cadastro.enviar"),
            pode_editar=pode_editar,
            pode_configurar=self.adm,
            url_enviar_pdfs=reverse("juridico:enviar_pdfs"),
            url_enviar_cnj=reverse("juridico:enviar_cnj"),
            url_processo_novo=reverse("juridico:processo_novo"),
            url_erros=reverse("juridico:erros"),
            url_envios=reverse("juridico:envios"),
            url_config=reverse("juridico:config"),
            url_audiencias=reverse("juridico:audiencias"),
        )
        return contexto

    def _selecionado(self, p, pode_editar):
        carteira = p.carteira.nome if p.carteira_id else ""
        grupos = grupos_leitura(p)
        return {
            "pk": p.pk,
            "numero": p.numero,
            "status": p.status,
            "status_rotulo": p.status_rotulo,
            "carteira": carteira,
            "tribunal": p.tribunal,
            "pendencias": p.pendencias,
            "grupos": grupos,
            "andamentos": _andamentos_texto(p),
            "url_detalhe": reverse("juridico:processo", kwargs={"pk": p.pk}),
            "url_marcar": reverse("juridico:marcar_cadastrado", kwargs={"pk": p.pk}),
            "pode_marcar": pode_editar and p.status == Processo.CONFERIR,
            "pode_editar": pode_editar,
        }


def grupos_leitura(p, completo=False):
    """Grupos só de leitura (painel e resumo do detalhe). `completo` mostra o CPF/CNPJ inteiro
    (só no detalhe, CAD-18)."""

    def linha(rotulo, valor):
        return {"rotulo": rotulo, "valor": valor or ""}

    documento = (
        p.adverso_cpf_cnpj if completo else apresentacao.mascarar_documento(p.adverso_cpf_cnpj)
    )
    advogado_adverso = " · ".join(x for x in (p.advogado_adverso_nome, p.advogado_adverso_oab) if x)
    fase = p.get_fase_atual_display() if p.fase_atual else ""
    cadastrado_por = (
        f"{apresentacao.quem(p.criado_por)} via {apresentacao.origem_rotulo(p.criado_via)}"
    )

    grupos = [
        {"titulo": "Partes", "campos": [
            linha("Empresa", p.empresa), linha("Adverso", p.adverso_nome),
            linha("CPF/CNPJ do adverso", documento),
            linha("Condição", p.condicao),
            linha("Advogado da empresa", p.advogado_empresa),
            linha("Advogado do adverso", advogado_adverso),
        ]},
        {"titulo": "Processo", "campos": [
            linha("Tribunal", p.tribunal), linha("Comarca", p.comarca), linha("Juízo", p.juizo),
            linha("Instância", p.instancia), linha("Rito", p.rito),
            linha("Distribuído em", apresentacao.data(p.distribuido_em)),
            linha("Data de citação", apresentacao.data(p.data_citacao)),
            linha("Valor da causa", apresentacao.valor_texto(p.valor_causa)),
        ]},
        {"titulo": "Operações vinculadas", "campos": [linha("Operações", p.operacoes_vinculadas)]},
        {"titulo": "Classificação", "campos": [
            linha("Natureza", p.natureza), linha("Categoria", p.categoria),
            linha("Tipo de ação", p.tipo_acao), linha("Fase atual", fase),
            linha("Meio de tramitação", p.meio_tramitacao), linha("Gerência", p.gerencia),
            linha("Escritório", p.escritorio),
        ]},
        {"titulo": "Pedidos", "campos": [linha("Pedidos", p.pedidos)]},
        {"titulo": "Validação no CNJ", "campos": [
            linha("Situação", p.get_cnj_validacao_display()),
            linha("Consultado em", apresentacao.data_hora(p.cnj_consultado_em)),
            linha("Divergências", "; ".join(p.cnj_divergencias)),
        ]},
        {"titulo": "Controle", "campos": [
            linha("Processado em", apresentacao.data_hora(p.atualizado_em)),
            linha("Cadastrado por", cadastrado_por),
            linha("Responsável", p.responsavel), linha("Observações", p.observacoes),
        ]},
    ]  # fmt: skip
    return grupos


def _andamentos_texto(p):
    itens = []
    for a in p.andamentos:
        data = a.get("data", "")
        try:
            data = apresentacao.data(timezone.datetime.fromisoformat(data)) if data else ""
        except ValueError:
            pass
        itens.append({"data": data, "evento": a.get("evento", ""), "fonte": a.get("fonte", "")})
    return itens


# ---------------------------------------------------------------- processo (TEL-28) e novo (TEL-35)
def _grupos(form, processo):
    origens = processo.origem_campos if processo is not None else {}
    grupos = []
    for titulo, campos in GRUPOS:
        grupos.append(
            {
                "titulo": titulo,
                "campos": [
                    {
                        "nome": n,
                        "rotulo": form.fields[n].label or n,
                        "campo": form[n],
                        "origem": origens.get(n, ""),
                    }
                    for n in campos
                ],  # fmt: skip
            }
        )
    return grupos


def _dados_do_post(form_class, instancia, post):
    """Campo ausente no POST = não muda (CAD-23): completa com o valor atual do processo."""
    from django.forms.models import model_to_dict

    atual = model_to_dict(instancia, fields=list(form_class.base_fields))
    dados = {}
    for nome in form_class.base_fields:
        if nome in post:
            dados[nome] = post.get(nome)
            continue
        valor = atual.get(nome)
        if nome == "valor_causa":
            from .forms import texto_valor

            valor = texto_valor(valor)
        elif nome == "carteira":
            valor = valor or ""
        elif hasattr(valor, "isoformat"):
            valor = (
                valor.isoformat()
                if nome != "proxima_audiencia"
                else timezone.localtime(valor).strftime("%Y-%m-%dT%H:%M")
            )
        dados[nome] = "" if valor is None else valor
    return dados


def _aplicar_edicao(processo, form, usuario, novo=False):
    alterados = []
    for nome in form.changed_data if not novo else form.cleaned_data:
        if nome not in form.fields:
            continue
        valor = form.cleaned_data[nome]
        if nome == "numero":
            digitos = cnj.so_digitos(valor)
            processo.numero = cnj.formatar(valor)[:25]
            processo.numero_digitos = digitos[:20]
            processo.numero_valido = cnj.valido(digitos)
            continue
        if novo and valor in (None, ""):
            continue
        setattr(processo, nome, valor)
        processo.origem_campos[nome] = "manual"
        alterados.append(nome)
    processo.atualizado_por = usuario
    return alterados


def _salvar_recalculando(processo):
    mescla.atualizar_audiencia(processo)
    mescla.recalcular(processo)
    processo.save()


class ProcessoView(CadastroMixin, View):
    """Conferência do processo (TEL-28; CAD-15). Template `juridico/processo.html`.

    GET `cadastro.ver`; POST (salvar) `cadastro.editar`: campos = nomes do modelo, campo ausente =
    não muda; edição vira origem `manual`; recalcula status/pendências (CAD-12); "Processo salvo."
    Erro de campo → 200 com `form` e erros por campo (nada gravado). Inexistente/excluído → 404.

    Contexto (além do shell): `processo` (numero, status, status_rotulo, carteira, criado_por_texto,
    ...), `resumo_grupos` [{titulo, campos[{rotulo, valor}]}] (leitura, datas DD/MM/AAAA e CPF/CNPJ
    completo), `form` + `grupos` [{titulo, campos[{nome, rotulo, campo (BoundField), origem}]}],
    `origem_campos`, `pendencias`, `cnj` {situacao, divergencias, consultado_em, mensagem (motivo
    quando falhou)}, `andamentos`
    [{data, evento, fonte}], `envios` [{quando, usuario, origem, descricao}], `url_pdf` ('' sem
    PDF), flags `pode_editar`, `pode_marcar`, `pode_desfazer`.
    """

    def _processo(self, pk):
        return get_object_or_404(Processo.objects.select_related("carteira", "criado_por"), pk=pk)

    def _contexto(self, processo, form):
        usuario = self.request.user
        itens = list(processo.itens.select_related("envio__enviado_por").order_by("-pk")[:50])
        item_pdf = next((i for i in itens if i.arquivo), None)
        envios = [
            {
                "quando": apresentacao.data_hora(i.envio.criado_em),
                "usuario": apresentacao.quem(i.envio.enviado_por),
                "origem": ROTULOS_ORIGEM.get(i.envio.origem, i.envio.origem),
                "descricao": i.aviso
                or (
                    "Cadastrou o processo." if i.acao == ItemEnvio.NOVO else "Atualizou o processo."
                ),
            }
            for i in itens
        ]
        processo.criado_por_texto = (
            f"Cadastrado por {apresentacao.nome(processo.criado_por)} em "
            f"{apresentacao.data(timezone.localtime(processo.criado_em))} via "
            f"{apresentacao.origem_rotulo(processo.criado_via)}"
        )
        pode_editar = pode(usuario, "cadastro.editar")
        return {
            "processo": processo,
            "form": form,
            "grupos": _grupos(form, processo),
            "origem_campos": processo.origem_campos,
            "resumo_grupos": grupos_leitura(processo, completo=True),
            "pendencias": processo.pendencias,
            "cnj": {
                "situacao": processo.cnj_validacao,
                "divergencias": processo.cnj_divergencias,
                "consultado_em": apresentacao.data_hora(processo.cnj_consultado_em),
                "mensagem": processo.cnj_mensagem,
            },
            "andamentos": _andamentos_texto(processo),
            "envios": envios,
            "url_pdf": reverse("juridico:pdf", kwargs={"pk": item_pdf.pk}) if item_pdf else "",
            "pode_editar": pode_editar,
            "pode_marcar": pode_editar and processo.status == Processo.CONFERIR,
            "pode_desfazer": self.adm and processo.status == Processo.CADASTRADO,
        }

    def get(self, request, pk):
        processo = self._processo(pk)
        form = ProcessoForm(instance=processo)
        return render(request, "juridico/processo.html", self._contexto(processo, form))

    def post(self, request, pk):
        self.exigir("cadastro.editar")
        processo = self._processo(pk)
        form = ProcessoForm(_dados_do_post(ProcessoForm, processo, request.POST), instance=processo)
        if not form.is_valid():
            return render(request, "juridico/processo.html", self._contexto(processo, form))
        processo = Processo.objects.get(pk=pk)
        _aplicar_edicao(processo, form, request.user)
        _salvar_recalculando(processo)
        messages.success(request, "Processo salvo.")
        return redirect("juridico:processo", pk=pk)


class ProcessoNovoView(CadastroMixin, View):
    """Cadastro manual (TEL-35; CAD-21). Template `juridico/processo_novo.html`. `cadastro.editar`.

    POST com os campos do modelo; `numero` obrigatório e válido ("Número CNJ inválido."). Número já
    existente → nada criado, 200 com `aviso_duplicidade` e `url_duplicado`. Sucesso: manual,
    consulta o CNJ ao salvar, redirect para `juridico:processo`.

    Contexto: `form`, `grupos`, `aviso_duplicidade` ('' ou texto), `url_duplicado` ('' ou link).
    """

    acao_requerida = "cadastro.editar"

    def _render(self, request, form, aviso="", url=""):
        return render(
            request,
            "juridico/processo_novo.html",
            {
                "form": form,
                "grupos": _grupos(form, None),
                "aviso_duplicidade": aviso,
                "url_duplicado": url,
            },
        )

    def get(self, request):
        return self._render(request, ProcessoForm())

    def post(self, request):
        digitos = cnj.so_digitos(request.POST.get("numero", ""))
        with transaction.atomic():
            travar_numero(digitos)  # dois cadastros do mesmo número: um cria, o outro vê o aviso
            existente = procurar_existente(digitos)
            if existente is not None:
                form = ProcessoForm(request.POST)
                aviso = aviso_existente(existente).replace(" Atualizado: nenhum dado novo.", "")
                return self._render(
                    request, form, aviso, reverse("juridico:processo", kwargs={"pk": existente.pk})
                )
            form = ProcessoForm(request.POST)
            if not form.is_valid():
                return self._render(request, form)
            processo = Processo(
                criado_por=request.user, criado_via=Processo.MANUAL, origem_campos={}
            )
            _aplicar_edicao(processo, form, request.user, novo=True)
            consultar_cnj(processo)
            _salvar_recalculando(processo)
        messages.success(request, "Processo cadastrado.")
        return redirect("juridico:processo", pk=processo.pk)


# ---------------------------------------------------------------- ações sobre o processo
class _AcaoProcesso(SoPost):
    acao_requerida = "cadastro.editar"

    def post(self, request, pk):
        return self.agir(request, get_object_or_404(Processo.objects, pk=pk))


class MarcarCadastradoView(_AcaoProcesso):
    """POST: marca como cadastrado no Espaider (exige status CONFERIR; CAD-15). Sem campos."""

    def agir(self, request, processo):
        if processo.status != Processo.CONFERIR:
            messages.error(request, "Resolva as pendências antes de marcar como cadastrado.")
        else:
            processo.status = Processo.CADASTRADO
            processo.cadastrado_espaider_em = timezone.now()
            processo.cadastrado_espaider_por = request.user
            processo.atualizado_por = request.user
            processo.save()
            messages.success(request, "Processo marcado como cadastrado no Espaider.")
        return redirect("juridico:processo", pk=processo.pk)


class DesfazerCadastradoView(_AcaoProcesso):
    """POST (Adm): desfaz o cadastrado; o status é recalculado (CAD-15)."""

    acao_requerida = "cadastro.configurar"

    def agir(self, request, processo):
        processo.cadastrado_espaider_em = processo.cadastrado_espaider_por = None
        processo.status = Processo.CONFERIR
        processo.atualizado_por = request.user
        mescla.recalcular(processo)
        processo.save()
        messages.success(request, "Cadastro desfeito.")
        return redirect("juridico:processo", pk=processo.pk)


class ConsultarCnjView(_AcaoProcesso):
    """POST: consulta o DataJud de novo (CAD-15). Sem campos."""

    def agir(self, request, processo):
        if not processo.numero_valido:
            messages.error(request, "Número CNJ inválido: não dá para consultar o DataJud.")
            return redirect("juridico:processo", pk=processo.pk)
        motivo = consultar_cnj(processo)
        _salvar_recalculando(processo)
        if motivo:
            messages.error(request, motivo)
        else:
            messages.success(request, f"CNJ consultado: {processo.get_cnj_validacao_display()}.")
        return redirect("juridico:processo", pk=processo.pk)


class ExcluirView(_AcaoProcesso):
    """POST: exclusão lógica (CAD-21), redirect para o painel + "Processo excluído."."""

    def agir(self, request, processo):
        processo.excluido_em, processo.excluido_por = timezone.now(), request.user
        processo.save()
        messages.success(request, "Processo excluído.")
        return redirect("juridico:painel")


class RestaurarView(SoPost):
    """POST (Adm): restaura um processo excluído (CAD-21)."""

    acao_requerida = "cadastro.configurar"

    def post(self, request, pk):
        processo = get_object_or_404(Processo.todos, pk=pk, excluido_em__isnull=False)
        processo.excluido_em = processo.excluido_por = None
        processo.save()
        messages.success(request, "Processo restaurado.")
        return redirect("juridico:excluidos")


# ---------------------------------------------------------------- envios
def _carteiras_choices(vazio):
    return [
        ("", vazio),
        *((str(c.pk), c.nome) for c in Carteira.objects.filter(ativa=True).order_by("nome")),
    ]


class EnviarPdfsView(CadastroMixin, View):
    """Enviar PDFs (TEL-29; CAD-03/04). Template `juridico/enviar_pdfs.html`. `cadastro.enviar`.

    POST multipart: `arquivos` (múltiplo, até 10, 30 MB cada, só "%PDF-") e `carteira` (pk ou
    vazio). Erro → 200, nada criado, `erros_arquivos` [str]; ok → redirect `juridico:envio` com
    "N PDF(s) na fila. Os dados aparecem no painel em alguns minutos."

    Contexto: `form` (form.carteira: ChoiceField), `erros_arquivos`.
    """

    acao_requerida = "cadastro.enviar"

    def _form(self, post=None):
        from django import forms

        class F(forms.Form):
            carteira = forms.ChoiceField(
                label="Carteira", required=False, choices=_carteiras_choices("Outra / não sei")
            )

        return F(post) if post is not None else F()

    def get(self, request):
        return render(
            request, "juridico/enviar_pdfs.html", {"form": self._form(), "erros_arquivos": []}
        )

    def post(self, request):
        form = self._form(request.POST)
        arquivos = request.FILES.getlist("arquivos")
        erros = servico.validar_pdfs(arquivos)
        if erros or not form.is_valid():
            return render(
                request, "juridico/enviar_pdfs.html", {"form": form, "erros_arquivos": erros}
            )
        carteira = (
            Carteira.objects.filter(pk=form.cleaned_data["carteira"] or None).first()
            if form.cleaned_data["carteira"]
            else None
        )
        envio, na_fila = servico.criar_envio_pdfs(request.user, arquivos, carteira)
        total = len(arquivos)
        messages.success(
            request,
            f"{total} PDF(s) na fila. Os dados aparecem no painel em alguns minutos."
            if na_fila
            else "Estes PDFs já estavam cadastrados: nada foi para a fila.",
        )
        return redirect("juridico:envio", pk=envio.pk)


class EnviarCnjView(CadastroMixin, View):
    """Cadastrar pelo CNJ (TEL-30; CAD-05/06, CAD-23 §3). Template `juridico/enviar_cnj.html`.

    POST: `numeros` (quebra de linha, vírgula ou ponto e vírgula; até 50), `carteira` (pk;
    vazio = "Outra / não sei"), `confirmar`. Se todos são novos e válidos → enfileira e redireciona
    para `juridico:envio`. Se algum já existe → 200 com `confirmacao`; o 2º POST (mesmos campos +
    confirmar=1) enfileira. Vazio → "Informe ao menos um número.".

    Contexto: `form` (numeros, carteira), `confirmacao` [{numero, valido, ja_existe: {url, quem,
    quando, via, excluido} | None}] ou None.
    """

    acao_requerida = "cadastro.enviar"

    def _form(self, post=None):
        from django import forms

        class F(forms.Form):
            numeros = forms.CharField(
                label="Números CNJ", required=False, widget=forms.Textarea(attrs={"rows": 6})
            )
            carteira = forms.ChoiceField(
                label="Carteira", required=False, choices=_carteiras_choices("Outra / não sei")
            )

        return F(post) if post is not None else F()

    def _render(self, request, form, confirmacao=None):
        return render(
            request, "juridico/enviar_cnj.html", {"form": form, "confirmacao": confirmacao}
        )

    def get(self, request):
        return self._render(request, self._form())

    def post(self, request):
        form = self._form(request.POST)
        if not form.is_valid():
            return self._render(request, form)
        texto = form.cleaned_data["numeros"]
        numeros = servico.separar_numeros(texto)
        if not numeros:
            form.add_error("numeros", servico.MSG_SEM_NUMERO)
            return self._render(request, form)
        if len(numeros) > servico.MAX_NUMEROS:
            form.add_error("numeros", f"Informe no máximo {servico.MAX_NUMEROS} números por vez.")
            return self._render(request, form)
        if not request.POST.get("confirmar"):
            linhas = servico.analisar_numeros(texto)
            if any(linha["ja_existe"] for linha in linhas):
                return self._render(request, form, linhas)
        pk = form.cleaned_data["carteira"]
        carteira = Carteira.objects.filter(pk=pk).first() if pk else None
        envio, na_fila = servico.criar_envio_cnj(request.user, texto, carteira)
        messages.success(
            request,
            f"{na_fila} número{'s' if na_fila != 1 else ''} na fila. "
            "Os dados aparecem no painel em alguns minutos.",
        )
        return redirect("juridico:envio", pk=envio.pk)


class EnviosView(CadastroMixin, TemplateView):
    """Envios (TEL-31). Template `juridico/envios.html`. Adm vê todos; os demais só os seus.

    Contexto: `envios` (Page de dicts {pk, quando, origem, casos, erros, duracao_texto, motivo,
    url}), `consulta`.
    """

    template_name = "juridico/envios.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        qs = _envios_anotados(_envios_visiveis(self.request)).order_by("-criado_em", "-pk")
        paginator = Paginator(qs, listagem.POR_PAGINA)
        pagina = listagem.pagina_valida(
            paginator, (self.request.GET.get("pagina") or self.request.GET.get("page") or 1)
        )
        pagina.object_list = [_linha_envio(e) for e in _com_motivo(pagina.object_list)]
        contexto.update(envios=pagina, page_obj=pagina, consulta="")
        return contexto


class EnvioView(CadastroMixin, TemplateView):
    """Detalhe do envio (CAD-17). Template `juridico/envio.html`. Só quem enviou e o Adm (404).

    Contexto: `envio` {pk, quando, origem, enviado_por, carteira}, `itens` [{pk, nome, status,
    status_rotulo, acao, motivo, etapa, aviso_duplicidade, processo_url, url_tentar, pode_tentar}],
    `url_status` (…/status/?envio=<pk>), `resumo_envio` {casos, sucessos, com_pendencias, erros}.
    """

    template_name = "juridico/envio.html"

    def get_context_data(self, pk, **kwargs):
        contexto = super().get_context_data(**kwargs)
        envio = get_object_or_404(_envios_visiveis(self.request), pk=pk)
        itens = list(envio.itens.select_related("processo").order_by("pk"))
        contexto.update(
            envio=Item(
                {
                    "pk": envio.pk,
                    "quando": apresentacao.data_hora(envio.criado_em),
                    "origem": ROTULOS_ORIGEM.get(envio.origem, envio.origem),
                    "enviado_por": apresentacao.quem(envio.enviado_por),
                    "carteira": envio.carteira.nome if envio.carteira_id else "",
                }
            ),
            itens=[_linha_item(i) for i in itens],
            url_status=f"{reverse('juridico:status')}?envio={envio.pk}",
            resumo_envio=servico.contagens_do_envio(envio),
        )
        return contexto


def _linha_item(i):
    return Item(
        {
            "pk": i.pk,
            "nome": i.nome_arquivo or i.numero_informado,
            "status": i.status,
            "status_rotulo": i.get_status_display(),
            "acao": i.acao,
            "motivo": i.motivo,
            "etapa": i.etapa_erro or "",
            "aviso_duplicidade": i.aviso,
            "processo_url": reverse("juridico:processo", kwargs={"pk": i.processo_id})
            if i.processo_id
            else None,
            "processo_numero": i.processo.numero if i.processo_id else "",
            "url_tentar": reverse("juridico:tentar_de_novo", kwargs={"pk": i.pk}),
            "pode_tentar": i.status == ItemEnvio.ERRO,
        }
    )


class StatusView(CadastroMixin, View):
    """JSON do auto-refresh (CAD-23 §8b): {total, com_pendencias, conferir, cadastrados, na_fila,
    erros, em_andamento}; com `?envio=<pk>` (só quem enviou e o Adm) também `itens` [{pk, status,
    processo_url|null, aviso|null, motivo|null}]."""

    http_method_names = ["get", "head", "options"]

    def get(self, request):
        resumo, andamento = _resumo(request.user)
        resposta = {**resumo, "em_andamento": andamento}
        envio_pk = request.GET.get("envio", "")
        if envio_pk:
            if not (envio_pk.isascii() and envio_pk.isdigit()):
                raise Http404
            envio = get_object_or_404(_envios_visiveis(request), pk=int(envio_pk))
            resposta["itens"] = [
                {
                    "pk": i.pk,
                    "status": i.status,
                    "processo_url": reverse("juridico:processo", kwargs={"pk": i.processo_id})
                    if i.processo_id
                    else None,
                    "aviso": i.aviso or None,
                    "motivo": i.motivo or None,
                }
                for i in envio.itens.order_by("pk")
            ]
        return JsonResponse(resposta)


class PdfView(CadastroMixin, View):
    """Baixa o PDF de um item (CAD-04): `cadastro.ver`, attachment, nome original saneado. Nunca
    por URL estática. Item sem arquivo → 404."""

    http_method_names = ["get", "head", "options"]

    def get(self, request, pk):
        item = get_object_or_404(ItemEnvio, pk=pk)
        if not item.arquivo:
            raise Http404
        try:
            arquivo = item.arquivo.open("rb")
        except OSError:
            raise Http404 from None
        return FileResponse(
            arquivo,
            as_attachment=True,
            filename=servico.nome_seguro(item.nome_arquivo),
            content_type="application/pdf",
        )


class _AcaoItem(SoPost):
    def post(self, request, pk):
        item = get_object_or_404(_itens_visiveis(request), pk=pk)
        return self.agir(request, item)


class TentarDeNovoView(_AcaoItem):
    """POST: item com erro volta para a fila (quem enviou ou Adm; CAD-13). Sem campos."""

    acao_requerida = "cadastro.enviar"

    def agir(self, request, item):
        if item.status != ItemEnvio.ERRO:
            messages.error(request, "Só dá para tentar de novo um item com erro.")
        else:
            item.status, item.tentativas = ItemEnvio.NA_FILA, 0
            item.etapa_erro, item.motivo, item.resposta_ia, item.resolvido = None, "", "", False
            item.save()
            Envio.objects.filter(pk=item.envio_id).update(terminado_em=None)
            messages.success(request, "Item de volta para a fila.")
        return redirect("juridico:envio", pk=item.envio_id)


class ResolverView(_AcaoItem):
    """POST: marca o erro como resolvido no Log (CAD-13/17). Sem campos."""

    def agir(self, request, item):
        item.resolvido = True
        item.save(update_fields=["resolvido"])
        messages.success(request, "Erro marcado como resolvido.")
        return redirect("juridico:erros")


# ---------------------------------------------------------------- log de erros (TEL-32)
class ErrosView(CadastroMixin, TemplateView):
    """Log de erros e desempenho (TEL-32; CAD-17, últimos 30 dias). Template `juridico/erros.html`.

    `?resolvido=1` mostra também os resolvidos. Adm vê tudo; os demais só os seus envios.

    Contexto: `cartoes` {ultima {quando, origem, casos, erros}|None, execucoes {envios, casos},
    casos_erro {n, pct}, tempo_medio {execucao, caso}, erros_pendentes}; `casos_por_dia` [{dia,
    rotulo, ok, sucesso, erro, tempo_medio_s, tempo_medio_texto}]; `erros_por_etapa` [{etapa,
    rotulo, total}]; `envios` [{pk, quando, origem, casos, erros, duracao_texto, motivo, url}];
    `itens` (Page de {pk, quando, nome, etapa, motivo, resolvido, url_resolvido, url_tentar});
    `filtro_resolvido` (bool).
    """

    template_name = "juridico/erros.html"
    ETAPAS = ("CNJ (DataJud)", "Dados incompletos", "Leitura do PDF", "Envio do PDF", "IA (Dify)")

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        request = self.request
        desde = timezone.now() - timedelta(days=30)
        itens_qs = _itens_visiveis(request).filter(envio__criado_em__gte=desde)
        problema = Q(status=ItemEnvio.ERRO) | Q(etapa_erro__isnull=False)
        totais = itens_qs.aggregate(
            casos=Count("pk"), erros=Count("pk", filter=problema), media=Avg("duracao_ms")
        )
        envios_qs = _envios_anotados(_envios_visiveis(request).filter(criado_em__gte=desde))
        envios = _com_motivo(envios_qs.order_by("-criado_em", "-pk")[:20])
        duracoes = [e.duracao_s for e in envios_qs if e.duracao_s is not None]
        ultimo = envios[0] if envios else None
        por_dia = {}
        for linha in (
            itens_qs.annotate(
                dia=TruncDate("envio__criado_em", tzinfo=timezone.get_current_timezone())
            )
            .values("dia")
            .annotate(
                total=Count("pk"), erros=Count("pk", filter=problema), media=Avg("duracao_ms")
            )
            .order_by("dia")
        ):
            erro = linha["erros"]
            media = (linha["media"] or 0) / 1000
            por_dia[linha["dia"]] = {
                "dia": linha["dia"].strftime("%d/%m"),
                "rotulo": linha["dia"].strftime("%d/%m"),
                "ok": linha["total"] - erro,
                "sucesso": linha["total"] - erro,
                "erro": erro,
                "tempo_medio_s": round(media, 1),
                "tempo_medio_texto": duracao_texto(media),
            }
        pendentes = dict(
            itens_qs.filter(etapa_erro__isnull=False, resolvido=False)
            .values_list("etapa_erro")
            .annotate(n=Count("pk"))
            .values_list("etapa_erro", "n")
        )
        mostrar_resolvidos = request.GET.get("resolvido") == "1"
        log = _itens_visiveis(request).filter(etapa_erro__isnull=False).order_by("-pk")
        if not mostrar_resolvidos:
            log = log.filter(resolvido=False)
        paginator = Paginator(log, listagem.POR_PAGINA)
        pagina = listagem.pagina_valida(
            paginator, (request.GET.get("pagina") or request.GET.get("page") or 1)
        )
        pagina.object_list = [
            Item(
                {
                    "pk": i.pk,
                    "quando": apresentacao.data_hora(i.envio.criado_em),
                    "nome": i.nome_arquivo or i.numero_informado,
                    "etapa": i.etapa_erro,
                    "motivo": i.motivo,
                    "resolvido": i.resolvido,
                    "url_resolvido": reverse("juridico:resolver", kwargs={"pk": i.pk}),
                    "url_tentar": reverse("juridico:tentar_de_novo", kwargs={"pk": i.pk})
                    if i.status == ItemEnvio.ERRO
                    else "",
                }
            )
            for i in pagina.object_list
        ]
        casos = totais["casos"] or 0
        envios_total = envios_qs.count()
        contexto.update(
            cartoes={
                "ultima": {
                    "quando": apresentacao.data_hora(ultimo.criado_em),
                    "origem": ROTULOS_ORIGEM.get(ultimo.origem, ultimo.origem),
                    "casos": ultimo.casos,
                    "erros": ultimo.erros,
                }
                if ultimo
                else None,
                "execucoes": {
                    "envios": _plural(envios_total, "envio", "envios"),
                    "casos": _plural(casos, "caso", "casos"),
                },
                "casos_erro": {
                    "n": totais["erros"],
                    "pct": f"{(totais['erros'] * 100 // casos) if casos else 0}%",
                },
                "tempo_medio": {
                    "execucao": duracao_texto(sum(duracoes) / len(duracoes)) if duracoes else "—",
                    "caso": duracao_texto((totais["media"] or 0) / 1000) if casos else "—",
                },
                "erros_pendentes": sum(pendentes.values()),
            },
            casos_por_dia=list(por_dia.values()),
            erros_por_etapa=[
                {"etapa": e, "rotulo": e, "total": pendentes.get(e, 0)} for e in self.ETAPAS
            ],
            envios=[_linha_envio(e) for e in envios],
            itens=pagina,
            page_obj=pagina,
            filtro_resolvido=mostrar_resolvidos,
        )
        return contexto


# ---------------------------------------------------------------- audiências (TEL-34)
class AudienciasView(CadastroMixin, TemplateView):
    """Audiências (TEL-34; CAD-20). Template `juridico/audiencias.html`: processos com audiência de
    hoje em diante, por data. Contexto: `processos` [{pk, numero, adverso, comarca, audiencia_texto,
    audiencia_proxima (≤7 dias), url_detalhe}]."""

    template_name = "juridico/audiencias.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        agora = timezone.now()
        contexto["processos"] = [
            {
                "pk": p.pk,
                "numero": p.numero,
                "adverso": p.adverso_nome,
                "comarca": p.comarca,
                "audiencia_texto": apresentacao.data_hora(p.proxima_audiencia),
                "audiencia_proxima": p.proxima_audiencia <= agora + timedelta(days=7),
                "url_detalhe": reverse("juridico:processo", kwargs={"pk": p.pk}),
            }
            for p in Processo.objects.filter(proxima_audiencia__gte=agora).order_by(
                "proxima_audiencia"
            )[:500]
        ]
        return contexto


# ---------------------------------------------------------------- configuração (TEL-33)
class ConfigView(CadastroMixin, View):
    """Configuração do cadastro (TEL-33; CAD-14). Template `juridico/config.html`. Só Adm.

    POST: dify_url, dify_credencial, dify_usuario, dify_ca_pem, datajud_url, datajud_credencial,
    setores_com_acesso (ids, múltiplo). Erro → 200 com erros por campo.

    Contexto: `form`, `carteiras` [{pk, nome, empresa, ativa}], `credenciais_bearer` [nome],
    `credenciais_header` [nome], `setores`, `excluidos` (lista; use |length), `resultado_teste`.
    """

    acao_requerida = "cadastro.configurar"

    @staticmethod
    def renderizar(request, form):
        return ConfigView()._render(request, form)

    def _render(self, request, form):
        sem_setor = Credencial.objects.filter(setor__isnull=True).order_by("nome")
        return render(
            request,
            "juridico/config.html",
            {
                "form": form,
                "carteiras": list(
                    Carteira.objects.order_by("nome").values("pk", "nome", "empresa", "ativa")
                ),
                "credenciais_bearer": list(
                    sem_setor.filter(tipo=Credencial.BEARER).values_list("nome", flat=True)
                ),
                "credenciais_header": list(
                    sem_setor.filter(tipo=Credencial.HEADER).values_list("nome", flat=True)
                ),
                "setores": list(Setor.objects.order_by("nome")),
                "excluidos": list(
                    Processo.todos.filter(excluido_em__isnull=False).values_list("pk", flat=True)
                ),
                "resultado_teste": "",
            },
        )

    def get(self, request):
        return self._render(request, ConfigForm(instance=ConfigCadastro.obter()))

    def post(self, request):
        form = ConfigForm(request.POST, instance=ConfigCadastro.obter())
        if not form.is_valid():
            return self._render(request, form)
        form.save()
        messages.success(request, "Configuração salva.")
        return redirect("juridico:config")


class TestarConexaoView(SoPost):
    """POST (Adm): testa o Dify ("ping") e o DataJud (número de exemplo), sem expor valores."""

    acao_requerida = "cadastro.configurar"

    def post(self, request):
        config = ConfigCadastro.obter()
        try:
            Dify(config).conversar("ping")
            dify = "ok"
        except ErroCliente as erro:
            dify = f"falhou ({erro.mensagem.rstrip('.')})"
        try:
            exemplo = cnj.numero_valido_de(1, 2020, 8, 26, 1)
            DataJud(config).consultar("tjsp", cnj.so_digitos(exemplo))
            datajud = "ok"
        except ErroCliente as erro:
            datajud = f"falhou ({erro.mensagem.rstrip('.')})"
        mensagem = f"Dify: {dify} · DataJud: {datajud}"
        (messages.success if dify == datajud == "ok" else messages.error)(request, mensagem)
        return redirect("juridico:config")


class CarteiraNovaView(SoPost):
    """POST (Adm): adiciona carteira (nome, empresa)."""

    acao_requerida = "cadastro.configurar"

    def post(self, request):
        form = CarteiraForm(
            {
                "nome": request.POST.get("nome", ""),
                "empresa": request.POST.get("empresa", ""),
                "ativa": "on",
            }
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Carteira adicionada.")
            return redirect("juridico:config")
        messages.error(request, " ".join(e for lista in form.errors.values() for e in lista))
        return ConfigView.renderizar(request, ConfigForm(instance=ConfigCadastro.obter()))


class CarteiraEditarView(SoPost):
    """POST (Adm): renomeia/ativa/desativa a carteira (nome, empresa, ativa=on|vazio)."""

    acao_requerida = "cadastro.configurar"

    def post(self, request, pk):
        carteira = get_object_or_404(Carteira, pk=pk)
        form = CarteiraForm(
            {"nome": request.POST.get("nome", carteira.nome),
             "empresa": request.POST.get("empresa", carteira.empresa),
             "ativa": request.POST.get("ativa", "")},
            instance=carteira,
        )  # fmt: skip
        if form.is_valid():
            form.save()
            messages.success(request, "Carteira salva.")
        else:
            messages.error(request, " ".join(e for lista in form.errors.values() for e in lista))
        return redirect("juridico:config")


class ExcluidosView(CadastroMixin, TemplateView):
    """Processos excluídos (CAD-21, Adm). Template `juridico/excluidos.html`. Contexto: `processos`
    [{pk, numero, adverso, excluido_em, excluido_por, url_restaurar}]."""

    acao_requerida = "cadastro.configurar"
    template_name = "juridico/excluidos.html"

    def get_context_data(self, **kwargs):
        contexto = super().get_context_data(**kwargs)
        contexto["processos"] = [
            {
                "pk": p.pk,
                "numero": p.numero,
                "adverso": p.adverso_nome,
                "excluido_em": apresentacao.data_hora(p.excluido_em),
                "excluido_por": apresentacao.quem(p.excluido_por) if p.excluido_por_id else "",
                "url_restaurar": reverse("juridico:restaurar", kwargs={"pk": p.pk}),
            }
            for p in Processo.todos.filter(excluido_em__isnull=False)
            .select_related("excluido_por")
            .order_by("-excluido_em")[:500]
        ]
        return contexto
