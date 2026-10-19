"""Criação de envios (CAD-03, CAD-05, CAD-06): validação dos arquivos/números e fila."""

import hashlib
import re
from pathlib import PurePath

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from . import apresentacao, cnj
from .models import Envio, ItemEnvio
from .processamento import aviso_existente, procurar_existente

MSG_SEM_PDF = "Escolha ao menos um PDF."
MSG_SEM_NUMERO = "Informe ao menos um número."
MAX_NUMEROS = 50


def nome_seguro(nome):
    """Nome original saneado (sem pasta, sem controle/aspas/barras)."""
    base = PurePath((nome or "").replace("\\", "/")).name
    base = re.sub(r'[\x00-\x1f"<>|:*?]', "_", base).strip(" .") or "arquivo.pdf"
    return base[:255]


def validar_pdfs(arquivos):
    """Lista de mensagens de erro (vazia = ok). Só vale o conteúdo: tem de começar com %PDF-."""
    if not arquivos:
        return [MSG_SEM_PDF]
    maximo = settings.JURIDICO_PDF_MAX_ARQUIVOS
    if len(arquivos) > maximo:
        return [f"Envie no máximo {maximo} PDFs por vez."]
    limite_mb = settings.JURIDICO_PDF_MAX_MB
    erros = []
    for arquivo in arquivos:
        nome = nome_seguro(arquivo.name)
        if arquivo.size > limite_mb * 1024 * 1024:
            erros.append(f"{nome}: maior que {limite_mb} MB.")
            continue
        arquivo.seek(0)
        inicio = arquivo.read(5)
        arquivo.seek(0)
        if inicio != b"%PDF-":
            erros.append(f"{nome}: não é um PDF.")
    return erros


def _sha256(arquivo):
    resumo = hashlib.sha256()
    arquivo.seek(0)
    for pedaco in arquivo.chunks():
        resumo.update(pedaco)
    arquivo.seek(0)
    return resumo.hexdigest()


def aviso_arquivo_repetido(anterior):
    quando = apresentacao.data_hora(anterior.envio.criado_em)
    return (
        f"Já temos este arquivo: processo {anterior.processo.numero} · enviado por "
        f"{apresentacao.quem(anterior.envio.enviado_por)} em {quando}."
    )


@transaction.atomic
def criar_envio_pdfs(usuario, arquivos, carteira):
    """Cria Envio + itens (CAD-03). Arquivo já concluído antes (mesmo sha256) vira `ignorado`."""
    envio = Envio.objects.create(origem=Envio.PDF, enviado_por=usuario, carteira=carteira)
    na_fila = 0
    for arquivo in arquivos:
        nome = nome_seguro(arquivo.name)
        resumo = _sha256(arquivo)
        anterior = (
            ItemEnvio.objects.select_related("envio__enviado_por", "processo")
            .filter(sha256=resumo, status=ItemEnvio.CONCLUIDO, processo__isnull=False)
            .order_by("pk")
            .first()
        )
        if anterior is not None:
            ItemEnvio.objects.create(
                envio=envio,
                nome_arquivo=nome,
                sha256=resumo,
                status=ItemEnvio.IGNORADO,
                processo=anterior.processo,
                duplicado_de=anterior,
                aviso=aviso_arquivo_repetido(anterior),
            )
            continue
        item = ItemEnvio(envio=envio, nome_arquivo=nome, sha256=resumo)
        item.arquivo.save(nome, ContentFile(arquivo.read()), save=False)
        item.save()
        na_fila += 1
    if na_fila == 0:
        envio.iniciado_em = envio.terminado_em = timezone.now()
        envio.save(update_fields=["iniciado_em", "terminado_em"])
    return envio, na_fila


def separar_numeros(texto):
    """Números do textarea (quebra de linha, vírgula ou ponto e vírgula), sem repetir, até 50+1."""
    vistos, itens = set(), []
    for pedaco in re.split(r"[\n\r,;]+", texto or ""):
        pedaco = pedaco.strip()
        if not pedaco:
            continue
        chave = cnj.so_digitos(pedaco) or pedaco
        if chave in vistos:
            continue
        vistos.add(chave)
        itens.append(pedaco)
    return itens


def analisar_numeros(texto):
    """Uma linha por número para a confirmação (CAD-06b): novo, inválido ou já existente."""
    linhas = []
    for pedaco in separar_numeros(texto)[: MAX_NUMEROS + 1]:
        digitos = cnj.so_digitos(pedaco)
        linha = {"numero": cnj.formatar(digitos) if len(digitos) == 20 else pedaco,
                 "valido": len(digitos) == 20, "ja_existe": None}  # fmt: skip
        existente = procurar_existente(digitos) if len(digitos) == 20 else None
        if existente is not None:
            linha["ja_existe"] = {
                "url": reverse("juridico:processo", kwargs={"pk": existente.pk}),
                "quem": apresentacao.quem(existente.criado_por),
                "quando": apresentacao.data(timezone.localtime(existente.criado_em)),
                "via": apresentacao.origem_rotulo(existente.criado_via),
                "excluido": existente.excluido_em is not None,
                "aviso": aviso_existente(existente),
            }
        linhas.append(linha)
    return linhas


@transaction.atomic
def criar_envio_cnj(usuario, texto, carteira):
    """Um item na fila por número de 20 dígitos; os demais viram item com erro (CAD-05)."""
    envio = Envio.objects.create(origem=Envio.CNJ, enviado_por=usuario, carteira=carteira)
    na_fila = 0
    for pedaco in separar_numeros(texto):
        digitos = cnj.so_digitos(pedaco)
        if len(digitos) != 20:
            ItemEnvio.objects.create(
                envio=envio,
                numero_informado=pedaco[:40],
                status=ItemEnvio.ERRO,
                etapa_erro="Gravação",
                motivo=f"Número inválido (o padrão CNJ tem 20 dígitos): {pedaco}"[:500],
            )
            continue
        ItemEnvio.objects.create(envio=envio, numero_informado=digitos)
        na_fila += 1
    if na_fila == 0:
        envio.iniciado_em = envio.terminado_em = timezone.now()
        envio.save(update_fields=["iniciado_em", "terminado_em"])
    return envio, na_fila


def contagens_do_envio(envio):
    itens = list(envio.itens.all())
    return {
        "casos": len(itens),
        "sucessos": sum(i.status == ItemEnvio.CONCLUIDO and not i.etapa_erro for i in itens),
        "com_pendencias": sum(
            i.status == ItemEnvio.CONCLUIDO and bool(i.etapa_erro) for i in itens
        ),
        "erros": sum(i.status == ItemEnvio.ERRO for i in itens),
    }
