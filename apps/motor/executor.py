"""Executor sequencial do fluxo (EXE-01..07, EXE-12, EXE-13, SEG-07..10, SEG-16).

Percorre a cadeia Gatilho → HTTP... → Saída a partir do gatilho, grava um `ExecucaoNo` por nó
(entrada com placeholders resolvidos e SEG-09 aplicado) e para na primeira falha: o nó vira
`erro` (categoria SEG-10 + mensagem própria), os seguintes `nao_executado`. O que foi gravado
nunca contém segredo: headers/query sensíveis e o snapshot do grafo são mascarados.
"""

import json
import logging
import time

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone

from apps.execucoes.models import Execucao, ExecucaoNo
from apps.fluxos.grafo import METODOS_COM_CORPO, validar

from . import http, mascarar, placeholders

logger = logging.getLogger(__name__)


class FluxoComPendencias(Exception):
    """O grafo tem pendências (EXE-02): nenhuma execução é criada."""

    def __init__(self, pendencias):
        super().__init__("grafo com pendências")
        self.pendencias = pendencias


class FalhaNo(Exception):
    """Falha de um nó com categoria da SEG-10 e mensagem própria; `saida` opcional (diagnóstico)."""

    def __init__(self, categoria, mensagem, saida=None, entrada=None):
        super().__init__(mensagem)
        self.categoria = categoria
        self.mensagem = mensagem
        self.saida = saida or {}
        self.entrada = entrada or {}


def _cadeia(grafo):
    """Nós na ordem de execução, a partir do gatilho (o grafo já foi validado: cadeia simples)."""
    por_id = {no["id"]: no for no in grafo["nos"]}
    proximo = {a["de"]: a["para"] for a in grafo["arestas"]}
    atual = next(no["id"] for no in grafo["nos"] if no["tipo"] == "gatilho")
    ordem = []
    while atual is not None:
        ordem.append(por_id[atual])
        atual = proximo.get(atual)
    return ordem


def _resolver_config(config, anterior):
    """Config http com placeholders resolvidos (PLH-04), pronta para enviar."""
    caminhos = [
        caminho
        for texto in _textos_da_config(config)
        for caminho in placeholders.caminhos_usados(texto)
    ]
    if anterior.get("truncado") and any(c.split(".")[0] == "corpo" for c in caminhos):
        raise FalhaNo(
            "resposta_grande",
            "O corpo da resposta anterior foi cortado no limite e não serve de placeholder.",
        )
    resolvido = {
        "metodo": config.get("metodo", "GET"),
        "url": placeholders.resolver_url(config.get("url", ""), anterior),
        "headers": [
            {
                "nome": placeholders.resolver_valor(p["nome"], anterior),
                "valor": placeholders.resolver_valor(p["valor"], anterior),
            }
            for p in config.get("headers") or []
        ],
        "query": [
            {
                "nome": placeholders.resolver_valor(p["nome"], anterior),
                "valor": placeholders.resolver_valor(p["valor"], anterior),
            }
            for p in config.get("query") or []
        ],
        "corpo": placeholders.resolver_corpo(config.get("corpo", ""), anterior),
    }
    corpo = resolvido["corpo"]
    if corpo.strip() and resolvido["metodo"] in METODOS_COM_CORPO:
        try:
            json.loads(corpo)
        except ValueError, RecursionError:
            raise FalhaNo("json_invalido", "O corpo resolvido não é um JSON válido.") from None
    return resolvido


def _textos_da_config(config):
    yield config.get("url", "")
    yield config.get("corpo", "")
    for campo in ("headers", "query"):
        for par in config.get(campo) or []:
            yield par["nome"]
            yield par["valor"]


def _executar_http(no, anterior, prazo_restante, segredos):
    resolvido = _resolver_config(no["config"], anterior)
    entrada = mascarar.ocultar_valores(mascarar.mascarar_entrada_http(resolvido), segredos)
    if prazo_restante <= 0:
        raise FalhaNo("timeout", http.MENSAGENS["timeout"], entrada=entrada)
    try:
        resposta = http.requisitar(
            metodo=resolvido["metodo"],
            url=resolvido["url"],
            headers=resolvido["headers"],
            query=resolvido["query"],
            corpo=resolvido["corpo"],
            prazo_s=prazo_restante,
        )
    except http.ErroHttp as erro:
        raise FalhaNo(erro.categoria, erro.mensagem, entrada=entrada) from None
    return entrada, resposta


class _Execucao:
    """Estado de uma execução em andamento."""

    def __init__(self, fluxo, usuario):
        self.usuario = usuario
        grafo = fluxo.grafo
        self.nos = _cadeia(grafo)
        self.execucao = Execucao.objects.create(
            fluxo=fluxo,
            fluxo_nome=fluxo.nome,
            grafo_snapshot=mascarar.mascarar_grafo(grafo),
            executado_por=usuario,
            status=Execucao.EXECUTANDO,
        )
        self.prazo = time.monotonic() + float(settings.MOTOR_TIMEOUT_EXECUCAO)
        self.segredos = set()  # valores de headers sensíveis já vistos nesta execução

    def _gravar(self, ordem, no, status, entrada, saida, duracao_ms, falha=None):
        """Grava o nó e devolve a falha efetiva (se o banco recusar o conteúdo, o nó vira erro)."""
        try:
            self._criar_no(ordem, no, status, entrada, saida, duracao_ms, falha)
        except DatabaseError, ValueError, TypeError:
            # dado que o banco recusa (ex.: resposta estranha): grava o nó sem o conteúdo
            logger.exception("Não foi possível gravar o nó %s; gravando sem conteúdo", no["id"])
            falha = FalhaNo("conexao", "Não foi possível gravar o resultado deste nó.")
            self._criar_no(ordem, no, ExecucaoNo.ERRO, {}, {}, duracao_ms, falha)
        return falha

    def _criar_no(self, ordem, no, status, entrada, saida, duracao_ms, falha):
        ExecucaoNo.objects.create(
            execucao=self.execucao,
            no_id=no["id"],
            no_tipo=no["tipo"],
            no_titulo=no["titulo"][:80],
            ordem=ordem,
            status=status,
            entrada=entrada,
            saida=saida,
            erro_categoria=falha.categoria if falha else None,
            erro_mensagem=falha.mensagem if falha else "",
            duracao_ms=duracao_ms,
        )

    def _rodar_no(self, no, anterior_bruto, anterior_gravado):
        """Devolve (entrada, saida_gravada, saida_bruta). Levanta FalhaNo."""
        if no["tipo"] == "gatilho":
            saida = {
                "disparado_em": timezone.now().isoformat(),
                "executado_por": self.usuario.email,
            }
            return {}, saida, saida
        if no["tipo"] == "saida":
            return {}, anterior_gravado, anterior_gravado
        try:
            entrada, resposta = _executar_http(
                no, anterior_bruto, self.prazo - time.monotonic(), self.segredos
            )
        except placeholders.ErroPlaceholder as erro:
            raise FalhaNo(placeholders.CATEGORIA, erro.mensagem) from None
        gravada = mascarar.mascarar_saida_http(resposta)
        self.segredos |= mascarar.valores_sensiveis(resposta["headers"])
        categoria = http.categoria_de_status(resposta["status"])
        if categoria:
            mensagem = f"{http.MENSAGENS[categoria]} (HTTP {resposta['status']})"
            raise FalhaNo(categoria, mensagem, gravada, entrada)
        return entrada, gravada, resposta

    def executar(self):
        anterior_bruto, anterior_gravado, falha_no = {}, {}, None
        for ordem, no in enumerate(self.nos):
            if falha_no is not None:
                self._gravar(ordem, no, ExecucaoNo.NAO_EXECUTADO, {}, {}, 0)
                continue
            inicio = time.monotonic()
            entrada, saida = {}, {}
            try:
                entrada, saida, anterior_bruto = self._rodar_no(
                    no, anterior_bruto, anterior_gravado
                )
                anterior_gravado = saida
                status, falha = ExecucaoNo.SUCESSO, None
            except FalhaNo as erro:
                status, falha, entrada, saida = ExecucaoNo.ERRO, erro, erro.entrada, erro.saida
            except placeholders.ErroPlaceholder as erro:
                status, falha = ExecucaoNo.ERRO, FalhaNo(placeholders.CATEGORIA, erro.mensagem)
            except Exception:
                logger.exception("Falha inesperada ao executar o nó %s", no["id"])
                status = ExecucaoNo.ERRO
                falha = FalhaNo("conexao", "Erro interno ao executar este nó.")
            duracao = int((time.monotonic() - inicio) * 1000)
            falha = self._gravar(ordem, no, status, entrada, saida, duracao, falha)
            if falha is not None:
                falha_no = (no, falha)
        return self._finalizar(falha_no)

    def _finalizar(self, falha_no):
        execucao = self.execucao
        execucao.finalizada_em = timezone.now()
        if falha_no is None:
            execucao.status = Execucao.SUCESSO
        else:
            no, falha = falha_no
            execucao.status = Execucao.ERRO
            execucao.erro_resumo = f"{no['titulo']}: {falha.mensagem}"[:500]
        execucao.save(update_fields=["status", "finalizada_em", "erro_resumo"])
        return execucao


def _terminar_com_erro_interno(execucao):
    execucao.status = Execucao.ERRO
    execucao.finalizada_em = timezone.now()
    execucao.erro_resumo = "Erro interno durante a execução."
    execucao.save(update_fields=["status", "finalizada_em", "erro_resumo"])


def executar(fluxo, usuario):
    """Executa o fluxo de forma síncrona e devolve a `Execucao` gravada (EXE-01).

    Levanta `FluxoComPendencias` se o grafo tem pendências ou erro de formato (EXE-02).
    """
    erros, pendencias = validar(fluxo.grafo)
    if erros:
        pendencias = [{"no": None, "campo": e["campo"], "mensagem": e["mensagem"]} for e in erros]
    if pendencias:
        raise FluxoComPendencias(pendencias)
    em_andamento = _Execucao(fluxo, usuario)
    try:
        return em_andamento.executar()
    except Exception:
        # a execução nunca pode ficar presa em "executando"
        logger.exception("Falha inesperada na execução %s", em_andamento.execucao.pk)
        _terminar_com_erro_interno(em_andamento.execucao)
        return em_andamento.execucao
