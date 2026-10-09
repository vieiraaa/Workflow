"""Executor do fluxo v2 (MV2-01..07, MV2-12): itens, ramos, ordem em profundidade, erro por item.

Percorre o grafo a partir do gatilho em busca em profundidade (destinos de um nó na ordem de
posição y, x do DESTINO; cada ramo vai até o fim ou até um Juntar que ainda espera entradas) e
grava um `ExecucaoNo` por visita. Nada gravado contém segredo: headers/query sensíveis, o valor
das credenciais usadas e o snapshot do grafo são mascarados (SEG-09, SEG-18).
"""

import copy
import json
import logging
import time

from django.conf import settings
from django.db import DatabaseError
from django.utils import timezone

from apps.execucoes.models import Execucao, ExecucaoNo
from apps.fluxos import catalogo
from apps.fluxos.grafo import arestas_de_retorno, normalizar, validar

from . import mascarar, nos
from .erros import FalhaNo, FluxoComPendencias
from .expressoes import ErroExpressao, Escopo

logger = logging.getLogger(__name__)

MAX_ITENS_GRAVADOS = 50
LIMITE_BYTES_EXECUCAO = 10 * 1024 * 1024
MAX_VOLTAS = 1000
MAX_REQUISICOES_GRAVADAS = 100

__all__ = ["FalhaNo", "FluxoComPendencias", "executar", "executar_teste"]


class _Parar(Exception):
    """A execução termina com erro neste nó (já gravado)."""

    def __init__(self, no, falha):
        super().__init__(falha.mensagem)
        self.no = no
        self.falha = falha


class Contexto:
    """O que os nós enxergam da execução em andamento."""

    def __init__(self, execucao_obj, usuario, fluxo_nome, prazo, fixos, setor_id=None):
        self.usuario = usuario
        self.setor_id = setor_id  # setor do fluxo: limita as credenciais visíveis (CRD-02)
        self.execucao = execucao_obj
        self.fluxo_nome = fluxo_nome
        self.resultados = {}  # título do nó → itens da saída 0 do último run
        self.segredos = set()
        self.agora = timezone.now()
        self._prazo = prazo
        self.fixos = fixos
        self._diagnosticos = []

    def prazo_restante(self):
        return self._prazo - time.monotonic()

    def escopo(self, item, indice, entrada, **extra):
        return Escopo(
            item=item,
            indice=indice,
            entrada=entrada,
            resultados=self.resultados,
            agora=self.agora,
            execucao_id=self.execucao.pk,
            fluxo_nome=self.fluxo_nome,
            usuario_email=self.usuario.email,
            parametros={},
            **extra,
        )

    def mascarar_requisicao(self, resolvido):
        """Requisição resolvida pronta para gravar (SEG-09 por nome + SEG-18 por valor)."""
        registro = mascarar.mascarar_entrada_http(resolvido)
        return mascarar.ocultar_valores(registro, self.segredos)

    def adicionar_segredos(self, valores):
        """Valores de credencial a mascarar por VALOR em tudo que é gravado (SEG-18)."""
        self.segredos |= {v for v in valores if isinstance(v, str) and len(v) >= 4}

    def diagnostico(self, falha):
        self._diagnosticos.append(falha)


def _como_falha(erro):
    if isinstance(erro, FalhaNo):
        return erro
    if isinstance(erro, ErroExpressao):
        return FalhaNo("expressao", erro.mensagem)
    logger.exception("Falha inesperada ao executar um nó")
    return FalhaNo("conexao", "Erro interno ao executar este nó.")


class _Execucao:
    """Estado de uma execução em andamento."""

    def __init__(self, fluxo, usuario, grafo, teste=False, ate_no=None):
        nos.carregar()
        self.usuario = usuario
        self.grafo = grafo
        self.por_id = {n["id"]: n for n in grafo["nos"]}
        arestas = [
            a for a in grafo["arestas"] if a["de"] in self.por_id and a["para"] in self.por_id
        ]
        self.incluidos = self._ancestrais(ate_no, arestas) if ate_no else set(self.por_id)
        arestas = [a for a in arestas if a["de"] in self.incluidos and a["para"] in self.incluidos]
        self.arestas = arestas
        self.retornos = arestas_de_retorno(grafo["nos"], arestas)
        self.saidas_do_no = self._saidas_ordenadas()
        self.entradas_de = {i: set() for i in self.por_id}
        for indice, aresta in enumerate(arestas):
            if indice not in self.retornos:
                self.entradas_de[aresta["para"]].add(indice)
        self.gatilho = next(n["id"] for n in grafo["nos"] if n["tipo"] == "gatilho")
        self.execucao = Execucao.objects.create(
            fluxo=fluxo,
            fluxo_nome=fluxo.nome,
            grafo_snapshot=mascarar.mascarar_grafo(grafo),
            executado_por=usuario,
            setor_id=fluxo.setor_id,
            status=Execucao.EXECUTANDO,
            teste=teste,
        )
        self.ctx = Contexto(
            self.execucao,
            usuario,
            fluxo.nome,
            time.monotonic() + float(settings.MOTOR_TIMEOUT_EXECUCAO),
            grafo.get("dados_fixos") or {},
            setor_id=fluxo.setor_id,
        )
        self.ordem = 0
        self.bytes_gravados = 0
        self.contagem = {}  # índice da aresta → itens entregues
        self.espera = {}  # Juntar: id → {entrada: itens}
        self.chegadas = {}  # Juntar: id → arestas já entregues
        self.lotes = {}  # Repetir em lotes: id → estado
        self.executados = set()

    # ------------------------------------------------------------ estrutura
    @staticmethod
    def _ancestrais(alvo, arestas):
        pais = {}
        for aresta in arestas:
            pais.setdefault(aresta["para"], set()).add(aresta["de"])
        visto, pilha = {alvo}, [alvo]
        while pilha:
            for pai in pais.get(pilha.pop(), ()):
                if pai not in visto:
                    visto.add(pai)
                    pilha.append(pai)
        return visto

    def _saidas_ordenadas(self):
        saidas = {i: [] for i in self.por_id}
        for indice, aresta in enumerate(self.arestas):
            destino = self.por_id[aresta["para"]]["posicao"]
            chave = (destino["y"], destino["x"], aresta["para"], aresta["saida"], indice)
            saidas[aresta["de"]].append((chave, indice))
        return {i: [ind for _, ind in sorted(lista)] for i, lista in saidas.items()}

    def _ordem_estatica(self):
        """Ordem prevista (profundidade, desempate por posição) para listar o que não rodou."""
        visto, ordem, pilha = set(), [], [self.gatilho]
        while pilha:
            atual = pilha.pop()
            if atual in visto:
                continue
            visto.add(atual)
            ordem.append(atual)
            pilha.extend(reversed([self.arestas[i]["para"] for i in self.saidas_do_no[atual]]))
        return ordem + [i for i in self.por_id if i in self.incluidos and i not in visto]

    # ------------------------------------------------------------ gravação
    def _itens_gravados(self, itens, truncar_por_orcamento=True):
        recorte = itens[:MAX_ITENS_GRAVADOS]
        gravados = mascarar.mascarar_itens(recorte, self.ctx.segredos)
        tamanho = len(json.dumps(gravados, ensure_ascii=False, default=str))
        if truncar_por_orcamento and self.bytes_gravados + tamanho > LIMITE_BYTES_EXECUCAO:
            return [], True
        self.bytes_gravados += tamanho
        return gravados, len(itens) > MAX_ITENS_GRAVADOS

    def _gravar(self, no, status, entradas, saidas, duracao_ms, falha=None, resultado=None):
        entrada_itens = [i for lista in entradas for i in lista]
        saida_itens = [i for lista in saidas if lista for i in lista]
        entrada_gravada, trunc_e = self._itens_gravados(entrada_itens)
        saida_gravada, trunc_s = self._itens_gravados(saida_itens)
        if resultado is not None:
            brutas = resultado.requisicoes
        else:
            brutas = [falha.requisicao] if falha is not None and falha.requisicao else []
        requisicoes = [mascarar.ocultar_valores(r, self.ctx.segredos) for r in brutas][
            :MAX_REQUISICOES_GRAVADAS
        ]
        dados = {
            "execucao": self.execucao,
            "no_id": no["id"],
            "no_tipo": no["tipo"],
            "no_titulo": no["titulo"][:80],
            "ordem": self.ordem,
            "status": status,
            "entrada": entrada_gravada,
            "saida": saida_gravada,
            "itens_entrada": len(entrada_itens),
            "itens_saida": len(saida_itens),
            "saidas_contagem": [len(s) if s else 0 for s in saidas],
            "truncado": trunc_e or trunc_s or any(i.get("truncado") for i in saida_itens),
            "logs": list(resultado.logs)[:200] if resultado else [],
            "requisicoes": requisicoes,
            "erro_categoria": falha.categoria if falha else None,
            "erro_mensagem": mascarar.ocultar_em_texto(falha.mensagem, self.ctx.segredos)
            if falha
            else "",
            "duracao_ms": duracao_ms,
        }
        self.ordem += 1
        try:
            ExecucaoNo.objects.create(**dados)
        except DatabaseError, ValueError, TypeError:
            logger.exception("Não foi possível gravar o nó %s; gravando sem conteúdo", no["id"])
            falha = FalhaNo("conexao", "Não foi possível gravar o resultado deste nó.")
            dados.update(
                status=ExecucaoNo.ERRO,
                entrada=[],
                saida=[],
                requisicoes=[],
                logs=[],
                erro_categoria=falha.categoria,
                erro_mensagem=falha.mensagem,
            )
            self.ordem += 1
            dados["ordem"] = self.ordem - 1
            ExecucaoNo.objects.create(**dados)
        return falha

    # ------------------------------------------------------------ execução de nós
    def _vazias(self, no):
        return [[] for _ in range(catalogo.n_saidas(no))]

    def _rodar(self, no, entradas, retorno=False):
        """Executa (ou pula) o nó, grava e devolve as saídas a entregar. Levanta `_Parar`."""
        inicio = time.monotonic()
        tipo = no["tipo"]
        total = sum(len(e) for e in entradas)
        status, resultado, falha = ExecucaoNo.SUCESSO, None, None
        try:
            if tipo == "repetir_em_lotes":
                saidas, status = self._lote(no, entradas[0], retorno)
            elif tipo != "gatilho" and total == 0:
                saidas, status = self._vazias(no), ExecucaoNo.SEM_ITENS
            elif tipo != "gatilho" and no.get("desativado"):
                saidas = self._vazias(no)
                if saidas:
                    saidas[0] = list(entradas[0])
                status = ExecucaoNo.DESATIVADO
            elif no["id"] in self.ctx.fixos:
                saidas = self._vazias(no)
                if saidas:
                    saidas[0] = copy.deepcopy(self.ctx.fixos[no["id"]])
                status = ExecucaoNo.FIXO
            else:
                if self.ctx.prazo_restante() <= 0:
                    raise FalhaNo("timeout", "A execução excedeu o tempo limite.")
                resultado = nos.REGISTRO[tipo](self.ctx, no, entradas)
                saidas = resultado.saidas
                if resultado.erro is not None:
                    status, falha = ExecucaoNo.ERRO, resultado.erro
        except (FalhaNo, ErroExpressao) as erro:
            falha = _como_falha(erro)
            self._gravar(no, ExecucaoNo.ERRO, entradas, [], self._ms(inicio), falha)
            raise _Parar(no, falha) from None
        except Exception as erro:  # noqa: BLE001 - nada pode escapar sem gravar o nó
            falha = _como_falha(erro)
            self._gravar(no, ExecucaoNo.ERRO, entradas, [], self._ms(inicio), falha)
            raise _Parar(no, falha) from None
        self.executados.add(no["id"])
        self.ctx.resultados[no["titulo"]] = list(saidas[0]) if saidas and saidas[0] else []
        efetiva = self._gravar(no, status, entradas, saidas, self._ms(inicio), falha, resultado)
        if efetiva is not falha and efetiva is not None:  # o banco recusou o conteúdo
            raise _Parar(no, efetiva)
        return saidas

    @staticmethod
    def _ms(inicio):
        return int((time.monotonic() - inicio) * 1000)

    def _lote(self, no, itens, retorno):
        """Repetir em lotes (NOV-04, MV2-15 B5): saída 0 = lote atual; saída 1 = pronto."""
        estado = self.lotes.get(no["id"])
        if retorno and estado is not None:
            estado["acumulado"].extend(itens)
        elif not itens:
            return self._vazias(no), ExecucaoNo.SEM_ITENS
        else:
            estado = self.lotes[no["id"]] = {
                "todos": list(itens),
                "pos": 0,
                "acumulado": [],
                "voltas": 0,
            }
        tamanho = no["config"].get("tamanho_lote")
        tamanho = tamanho if isinstance(tamanho, int) and tamanho >= 1 else 1
        if estado["pos"] < len(estado["todos"]):
            estado["voltas"] += 1
            if estado["voltas"] > MAX_VOLTAS:
                raise FalhaNo("laco_excessivo", "O laço passou de 1.000 voltas.")
            lote = estado["todos"][estado["pos"] : estado["pos"] + tamanho]
            estado["pos"] += tamanho
            return [lote, None], ExecucaoNo.SUCESSO
        del self.lotes[no["id"]]
        return [None, estado["acumulado"]], ExecucaoNo.SUCESSO

    def _receber(self, no, entrada, itens, aresta):
        """Entradas prontas para rodar o nó, ou None enquanto o Juntar espera outras entradas."""
        quantidade = catalogo.n_entradas(no)
        if quantidade <= 1 or no["tipo"] == "repetir_em_lotes":
            return [itens]
        espera = self.espera.setdefault(no["id"], {})
        espera.setdefault(entrada, []).extend(itens)
        chegadas = self.chegadas.setdefault(no["id"], set())
        chegadas.add(aresta)
        if not self.entradas_de[no["id"]] <= chegadas:
            return None
        del self.espera[no["id"]], self.chegadas[no["id"]]
        return [espera.get(i, []) for i in range(quantidade)]

    def _entregar(self, no, saidas, pilha):
        tarefas, usados = [], {}
        for indice in self.saidas_do_no[no["id"]]:
            aresta = self.arestas[indice]
            alca = aresta["saida"]
            itens = saidas[alca] if alca < len(saidas) else []
            if itens is None:
                continue
            usados[alca] = usados.get(alca, 0) + 1
            if usados[alca] > 1:
                itens = copy.deepcopy(itens)
            self.contagem[indice] = self.contagem.get(indice, 0) + len(itens)
            tarefas.append((aresta["para"], aresta["entrada"], itens, indice))
        pilha.extend(reversed(tarefas))

    def executar(self):
        pilha = [(self.gatilho, 0, [], None)]
        parada = None
        try:
            while pilha:
                id_, entrada, itens, aresta = pilha.pop()
                no = self.por_id[id_]
                entradas = self._receber(no, entrada, itens, aresta) if aresta is not None else [[]]
                if entradas is None:
                    continue
                saidas = self._rodar(no, entradas, retorno=aresta in self.retornos)
                self._entregar(no, saidas, pilha)
        except _Parar as erro:
            parada = erro
        for id_ in self._ordem_estatica():
            if id_ not in self.executados and (parada is None or id_ != parada.no["id"]):
                if parada is not None:
                    self._gravar(self.por_id[id_], ExecucaoNo.NAO_EXECUTADO, [], [], 0)
        return self._finalizar(parada)

    def _finalizar(self, parada):
        execucao = self.execucao
        execucao.finalizada_em = timezone.now()
        execucao.arestas = [
            {
                "de": self.arestas[i]["de"],
                "saida": self.arestas[i]["saida"],
                "para": self.arestas[i]["para"],
                "entrada": self.arestas[i]["entrada"],
                "itens": quantidade,
            }
            for i, quantidade in sorted(self.contagem.items())
        ]
        if parada is None:
            execucao.status = Execucao.SUCESSO
        else:
            execucao.status = Execucao.ERRO
            resumo = f"{parada.no['titulo']}: {parada.falha.mensagem}"
            execucao.erro_resumo = mascarar.ocultar_em_texto(resumo, self.ctx.segredos)[:500]
        execucao.save(update_fields=["status", "finalizada_em", "erro_resumo", "arestas"])
        return execucao


def _terminar_com_erro_interno(execucao):
    execucao.status = Execucao.ERRO
    execucao.finalizada_em = timezone.now()
    execucao.erro_resumo = "Erro interno durante a execução."
    execucao.save(update_fields=["status", "finalizada_em", "erro_resumo"])


def _pendencias_do(grafo, ate_no=None):
    erros, pendencias = validar(grafo)
    if erros:
        return [{"no": None, "campo": e["campo"], "mensagem": e["mensagem"]} for e in erros]
    if ate_no and not any(n["id"] == ate_no for n in grafo.get("nos", [])):
        raise KeyError(ate_no)
    if ate_no:
        v2 = normalizar(grafo)
        validas = [
            a
            for a in v2["arestas"]
            if a["de"] in {n["id"] for n in v2["nos"]} and a["para"] in {n["id"] for n in v2["nos"]}
        ]
        relevantes = _Execucao._ancestrais(ate_no, validas)
        pendencias = [p for p in pendencias if p["no"] is None or p["no"] in relevantes]
    return pendencias


def _rodar(fluxo, usuario, grafo, teste, ate_no):
    pendencias = _pendencias_do(grafo, ate_no)
    if pendencias:
        raise FluxoComPendencias(pendencias)
    em_andamento = _Execucao(fluxo, usuario, normalizar(grafo), teste=teste, ate_no=ate_no)
    try:
        return em_andamento.executar()
    except Exception:
        # a execução nunca pode ficar presa em "executando"
        logger.exception("Falha inesperada na execução %s", em_andamento.execucao.pk)
        _terminar_com_erro_interno(em_andamento.execucao)
        return em_andamento.execucao


def executar(fluxo, usuario):
    """Executa o fluxo de forma síncrona e devolve a `Execucao` gravada (EXE-01).

    Levanta `FluxoComPendencias` se o grafo tem pendências ou erro de formato (EXE-02).
    """
    return _rodar(fluxo, usuario, fluxo.grafo, False, None)


def executar_teste(fluxo, usuario, no_id, grafo=None):
    """Executa só até `no_id` (e seus ancestrais) como execução de teste (MV2-06, MV2-12 L7).

    Usa `grafo` (o do editor, ainda não salvo) ou o do fluxo. `KeyError` se o nó não existe.
    """
    return _rodar(fluxo, usuario, grafo if grafo is not None else fluxo.grafo, True, no_id)
