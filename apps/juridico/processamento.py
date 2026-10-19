"""Processamento da fila do cadastro (CAD-06..13): um item por vez, na ordem de chegada.

PDF → texto (pypdf) → Dify → leitura da resposta → mesclagem → DataJud → gravação. Falhas viram
item `erro` (nenhum processo gravado) ou `concluido` com `etapa_erro` (processo gravado com
problema, CAD-23 §5). Nada aqui loga segredo, texto do PDF ou resposta da IA.
"""

import hashlib
import logging
import time
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models.functions import Coalesce
from django.utils import timezone

from . import apresentacao, cnj, leitura, mescla, pdf
from .clientes import (
    QUERY_PDF_ANEXADO,
    DataJud,
    Dify,
    ErroCliente,
    mascarar_dados,
    mascarar_texto,
    segredos_do_cadastro,
)
from .models import Carteira, ConfigCadastro, Envio, ItemEnvio, Processo

logger = logging.getLogger(__name__)
MSG_LEITURA_PDF = "Não foi possível abrir o PDF nem lê-lo como imagem (corrompido ou com senha)."
MSG_INTERROMPIDO = "Processamento interrompido."
MAX_RESPOSTA_IA = 200 * 1024


class FalhaItem(Exception):
    """Falha que encerra o item como `erro`."""

    def __init__(self, etapa, motivo, resposta_ia=""):
        super().__init__(motivo)
        self.etapa = etapa
        self.motivo = motivo
        self.resposta_ia = resposta_ia


# ---------------------------------------------------------------- avisos de duplicidade (CAD-06)
def aviso_existente(processo, atualizados=None):
    """Aviso da CAD-06 (b)/(d). `atualizados=None` (confirmação) omite 'Atualizado'."""
    quando = apresentacao.data(timezone.localtime(processo.criado_em))
    via = apresentacao.origem_rotulo(processo.criado_via)
    texto = (
        f"Este processo já existia: cadastrado por {apresentacao.quem(processo.criado_por)} "
        f"em {quando} via {via}."
    )
    if atualizados is not None:
        campos = ", ".join(atualizados) if atualizados else "nenhum dado novo"
        texto += f" Atualizado: {campos}."
    if processo.excluido_em:
        texto = (
            f"Este processo tinha sido excluído por {apresentacao.quem(processo.excluido_por)} "
            f"em {apresentacao.data(timezone.localtime(processo.excluido_em))} e foi restaurado. "
            + texto
        )
    return texto


def travar_numero(digitos):
    """Serializa quem grava o MESMO número (workers e cadastro manual): trava consultiva da
    transação, liberada no commit. Sem número válido não há o que serializar."""
    if not cnj.valido(digitos):
        return
    chave = int.from_bytes(
        hashlib.sha256(f"cadastro:{digitos}".encode()).digest()[:8], "big", signed=True
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [chave])


def procurar_existente(numero):
    """Processo (inclusive excluído) de mesmo número VÁLIDO; inválido nunca casa (CAD-06c)."""
    digitos = cnj.so_digitos(numero)
    if not cnj.valido(digitos):
        return None
    return Processo.todos.filter(numero_digitos=digitos, numero_valido=True).first()


# ---------------------------------------------------------------- DataJud (CAD-10)
def consultar_cnj(processo, config=None):
    """Consulta o DataJud e atualiza o processo (sem salvar). Devolve `motivo` de log ou None."""
    config = config or ConfigCadastro.obter()
    agora = timezone.now()
    if not processo.numero_valido:
        return None
    alias = cnj.alias_datajud(processo.numero_digitos)
    processo.cnj_divergencias = []
    processo.cnj_mensagem = ""
    processo.cnj_consultado_em = agora
    if alias is None:
        processo.cnj_validacao = "falhou"
        processo.cnj_mensagem = "Tribunal não suportado no DataJud."
        return processo.cnj_mensagem
    try:
        fonte = DataJud(config).consultar(alias, processo.numero_digitos)
    except ErroCliente as erro:
        processo.cnj_validacao = "falhou"
        processo.cnj_mensagem = erro.mensagem[:500]
        if erro.categoria == "recusada":
            config.datajud_recusado_em = agora
            config.save(update_fields=["datajud_recusado_em"])
        return erro.mensagem
    if config.datajud_recusado_em:
        config.datajud_recusado_em = None
        config.save(update_fields=["datajud_recusado_em"])
    if fonte is None:
        processo.cnj_validacao = "nao_encontrado"
        return None
    try:
        fonte = mascarar_dados(fonte, segredos_do_cadastro(config))
        divergencias = mescla.comparar(processo, fonte)
        campos = mescla.campos_do_datajud(fonte, alias)
    except AttributeError, TypeError, ValueError, KeyError, RecursionError:
        processo.cnj_validacao = "falhou"  # forma inesperada: o processo é gravado mesmo assim
        processo.cnj_mensagem = "O DataJud devolveu uma resposta inesperada."
        return processo.cnj_mensagem
    mescla.aplicar_cnj(processo, campos)
    processo.cnj_divergencias = divergencias
    processo.cnj_validacao = "divergente" if divergencias else "confere"
    return None


def _deduzir_carteira(empresa):
    alvo = cnj.sem_acento(empresa)
    if not alvo:
        return None
    for carteira in sorted(Carteira.objects.filter(ativa=True), key=lambda c: -len(c.nome)):
        if cnj.sem_acento(carteira.nome) in alvo:
            return carteira
    return None


def _fechar_item(item, processo, acao, aviso, etapa=None, motivo=""):
    item.processo, item.acao, item.aviso = processo, acao, aviso
    item.status = ItemEnvio.CONCLUIDO
    item.etapa_erro, item.motivo = etapa, motivo[:500]


# ---------------------------------------------------------------- PDF
def _consultar_dify(item, config, conteudo):
    """(campos, pendências, resposta_ia) do Dify; levanta FalhaItem."""
    try:
        dify = Dify(config)
    except ErroCliente as erro:
        raise FalhaItem("IA (Dify)", erro.mensagem) from None
    texto, falha_leitura = "", False
    try:
        texto = leitura.normalizar_texto(pdf.extrair_texto(conteudo))
    except pdf.ErroPdf:
        falha_leitura = True
    try:
        if len(texto) >= 200:
            query = leitura.cortar(
                texto,
                settings.JURIDICO_TEXTO_MAX,
                settings.JURIDICO_TEXTO_INICIO,
                settings.JURIDICO_TEXTO_FIM,
            )
            answer, bruto = dify.conversar(query)
        else:
            try:
                arquivo_id = dify.enviar_arquivo(conteudo, item.nome_arquivo)
            except ErroCliente as erro:
                if erro.categoria == "recusada":
                    raise
                if falha_leitura and erro.categoria in ("http", "formato"):
                    raise FalhaItem("Leitura do PDF", MSG_LEITURA_PDF) from None
                raise FalhaItem("Envio do PDF", _motivo_ia(erro)) from None
            answer, bruto = dify.conversar(QUERY_PDF_ANEXADO, arquivo_id)
    except ErroCliente as erro:
        raise FalhaItem("IA (Dify)", _motivo_ia(erro)) from None
    resposta_ia = mascarar_texto(bruto, dify.segredos)[:MAX_RESPOSTA_IA]
    try:
        campos, pendencias = leitura.ler_resposta(answer)
    except leitura.ErroLeitura as erro:
        raise FalhaItem("IA (Dify)", erro.mensagem, resposta_ia) from None
    segredos = segredos_do_cadastro(config)  # chave refletida em campo extraído (CAD-18)
    return mascarar_dados(campos, segredos), mascarar_dados(pendencias, segredos), resposta_ia


def _motivo_ia(erro):
    if erro.categoria in ("recusada", "formato", "tls", "credencial", "resposta_grande"):
        return erro.mensagem
    return f"A IA não respondeu: {erro.mensagem}."


def _gravar_pdf(item, campos, pendencias, config):
    envio = item.envio
    travar_numero(cnj.so_digitos(campos.get("numero", "")))
    existente = procurar_existente(campos.get("numero", ""))
    agora = timezone.now()
    if existente is None:
        digitos = cnj.so_digitos(campos.get("numero", ""))
        valido = cnj.valido(digitos)
        processo = Processo(
            numero=cnj.formatar(digitos) if len(digitos) == 20 else campos.get("numero", "")[:25],
            numero_digitos=digitos[:20],
            numero_valido=valido,
            criado_por=envio.enviado_por,
            criado_via=Processo.PDF,
            carteira=envio.carteira or _deduzir_carteira(campos.get("empresa", "")),
            origem_campos={},
            pendencias=list(pendencias),
        )
        mescla.aplicar_pdf(processo, campos, agora)
        acao, atualizados, aviso = ItemEnvio.NOVO, [], ""
    else:
        processo = existente
        excluido = processo.excluido_em is not None
        mudou = mescla.aplicar_pdf(processo, campos, agora)
        atualizados = [mescla._rotulo(c) for c in mudou]
        if envio.carteira and processo.carteira_id is None:
            processo.carteira = envio.carteira
        processo.pendencias = [*processo.pendencias, *pendencias]
        aviso = aviso_existente(processo, atualizados)
        if excluido:
            processo.excluido_em = processo.excluido_por = None
        acao = ItemEnvio.ATUALIZADO
    processo.atualizado_por = envio.enviado_por
    mescla.atualizar_audiencia(processo)
    motivo_cnj = consultar_cnj(processo, config)
    faltando = mescla.recalcular(processo)
    mescla.atualizar_audiencia(processo)
    processo.save()
    etapa, motivo = None, ""
    if faltando:
        etapa = "Dados incompletos"
        motivo = f"Processo {processo.numero} gravado, mas faltou: {', '.join(faltando)}"
    if motivo_cnj and (motivo_cnj.startswith("Chave do DataJud") or not etapa):
        etapa, motivo = "CNJ (DataJud)", motivo_cnj
    _fechar_item(item, processo, acao, aviso, etapa, motivo)


def _processar_pdf(item, config):
    if not item.arquivo:
        raise FalhaItem("Leitura do PDF", MSG_LEITURA_PDF)
    try:
        with item.arquivo.open("rb") as arquivo:
            conteudo = arquivo.read()
    except OSError:
        raise FalhaItem("Leitura do PDF", "O arquivo do PDF não está mais no servidor.") from None
    campos, pendencias, item.resposta_ia = _consultar_dify(item, config, conteudo)
    with transaction.atomic():
        _gravar_pdf(item, campos, pendencias, config)


# ---------------------------------------------------------------- CNJ
def _processar_cnj(item, config):
    envio = item.envio
    digitos = cnj.so_digitos(item.numero_informado)
    valido = cnj.valido(digitos)
    with transaction.atomic():
        travar_numero(digitos)
        existente = procurar_existente(digitos)
        if existente is None:
            processo = Processo(
                numero=cnj.formatar(digitos),
                numero_digitos=digitos,
                numero_valido=valido,
                criado_por=envio.enviado_por,
                criado_via=Processo.CNJ_ORIGEM,
                carteira=envio.carteira,
                empresa=envio.carteira.empresa if envio.carteira_id else "",
                origem_campos={"empresa": "cnj"}
                if envio.carteira_id and envio.carteira.empresa
                else {},
            )
            acao, aviso, atualizados = ItemEnvio.NOVO, "", []
        else:
            processo, acao = existente, ItemEnvio.ATUALIZADO
            antes = {c: getattr(processo, c) for c in mescla.CAMPOS_DADOS}
        motivo_cnj = consultar_cnj(processo, config)
        if existente is not None:
            atualizados = [mescla._rotulo(c) for c, v in antes.items() if getattr(processo, c) != v]
            aviso = aviso_existente(processo, atualizados)
            if processo.excluido_em:
                processo.excluido_em = processo.excluido_por = None
            if envio.carteira and processo.carteira_id is None:
                processo.carteira = envio.carteira
        processo.atualizado_por = envio.enviado_por
        mescla.atualizar_audiencia(processo)
        faltando = mescla.recalcular(processo)
        processo.save()
        etapa, motivo = None, ""
        if faltando and processo.cnj_validacao in ("nao_encontrado", "falhou"):
            etapa = "Dados incompletos"
            motivo = f"Processo {processo.numero} gravado, mas faltou: {', '.join(faltando)}"
        if motivo_cnj:
            etapa, motivo = "CNJ (DataJud)", motivo_cnj
        _fechar_item(item, processo, acao, aviso, etapa, motivo)


# ---------------------------------------------------------------- item e fila
def processar_item(item, config=None):
    """Processa UM item já marcado `processando`. Nunca levanta (falha vira estado do item)."""
    config = config or ConfigCadastro.obter()
    inicio = time.monotonic()
    try:
        if item.envio.origem == Envio.PDF:
            _processar_pdf(item, config)
        else:
            _processar_cnj(item, config)
    except FalhaItem as falha:
        item.status, item.etapa_erro = ItemEnvio.ERRO, falha.etapa
        item.motivo = mascarar_texto(falha.motivo, segredos_do_cadastro(config))[:500]
        item.resposta_ia = falha.resposta_ia or item.resposta_ia
    except Exception:  # noqa: BLE001 - o worker não pode morrer por um item
        logger.exception("Falha inesperada ao processar o item %s do cadastro", item.pk)
        item.status, item.etapa_erro = ItemEnvio.ERRO, "Gravação"
        item.motivo = "Falha inesperada ao gravar o processo."
    item.duracao_ms = int((time.monotonic() - inicio) * 1000)
    item.save()
    _encerrar_envio_se_acabou(item.envio_id)


def _encerrar_envio_se_acabou(envio_id):
    if not ItemEnvio.objects.filter(
        envio_id=envio_id, status__in=[ItemEnvio.NA_FILA, ItemEnvio.PROCESSANDO]
    ).exists():
        Envio.objects.filter(pk=envio_id, terminado_em__isnull=True).update(
            terminado_em=timezone.now()
        )


def recuperar_travados():
    """Item em `processando` há mais de JURIDICO_TRAVADO_MIN volta para a fila uma vez (CAD-13)."""
    limite = timezone.now() - timedelta(minutes=settings.JURIDICO_TRAVADO_MIN)
    travados = ItemEnvio.objects.annotate(desde=Coalesce("iniciado_em", "criado_em")).filter(
        status=ItemEnvio.PROCESSANDO, desde__lt=limite
    )
    for item in travados:
        if item.tentativas >= 1:  # já voltou para a fila uma vez
            item.status, item.etapa_erro, item.motivo = ItemEnvio.ERRO, "Gravação", MSG_INTERROMPIDO
            item.save(update_fields=["status", "etapa_erro", "motivo"])
            _encerrar_envio_se_acabou(item.envio_id)
        else:
            item.status = ItemEnvio.NA_FILA
            item.tentativas += 1
            item.save(update_fields=["status", "tentativas"])


def reservar_proximo():
    """Pega o item mais antigo da fila e o marca `processando` (seguro com mais de um worker)."""
    with transaction.atomic():
        item = (
            ItemEnvio.objects.select_for_update(skip_locked=True, of=("self",))
            .select_related("envio", "envio__carteira", "envio__enviado_por")
            .filter(status=ItemEnvio.NA_FILA)
            .order_by("pk")
            .first()
        )
        if item is None:
            return None
        agora = timezone.now()
        item.status, item.iniciado_em = ItemEnvio.PROCESSANDO, agora
        item.save(update_fields=["status", "iniciado_em"])
        Envio.objects.filter(pk=item.envio_id, iniciado_em__isnull=True).update(iniciado_em=agora)
        return item


def processar_fila():
    """Processa a fila atual até esvaziar. Devolve quantos itens processou."""
    recuperar_travados()
    total = 0
    while (item := reservar_proximo()) is not None:
        processar_item(item)
        total += 1
    return total
