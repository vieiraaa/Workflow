"""Execuções de exemplo (sem rede) para a demo local e para as capturas de tela.

Os dados seguem o formato gravado pelo executor (EXE-12) e já vêm mascarados (SEG-09).
"""

from datetime import timedelta

from django.utils import timezone

from apps.motor.mascarar import MASCARA, mascarar_grafo

from .models import Execucao, ExecucaoNo

CORPO_PEDIDO = {
    "id": 1,
    "cliente": "Maria Ficticia",
    "itens": [{"sku": "A-1", "qtd": 2}],
    "total": 59.9,
}
HEADERS_RESPOSTA = {
    "content-type": "application/json",
    "x-request-id": "demo-123",
    "set-cookie": MASCARA,
}


def _entrada(url):
    return {
        "metodo": "GET",
        "url": url,
        "headers": [
            {"nome": "Accept", "valor": "application/json"},
            {"nome": "Authorization", "valor": MASCARA},
        ],
        "query": [{"nome": "detalhe", "valor": "completo"}],
        "corpo": "",
    }


def _cenarios(usuario):
    gatilho = {"disparado_em": timezone.now().isoformat(), "executado_por": usuario.email}
    url = "https://api.exemplo.test/pedidos/1"
    ok = {"status": 200, "headers": HEADERS_RESPOSTA, "corpo": CORPO_PEDIDO, "truncado": False}
    erro500 = {
        "status": 500,
        "headers": {"content-type": "application/json"},
        "corpo": {"erro": "falha interna do servidor de exemplo", "codigo": 500},
        "truncado": False,
    }
    return {
        "sucesso": (
            "sucesso",
            "",
            [
                ("gatilho", "Início", "sucesso", {}, gatilho, None, 1),
                ("http", "Buscar pedido", "sucesso", _entrada(url), ok, None, 182),
                ("saida", "Resultado", "sucesso", {}, ok, None, 0),
            ],
        ),
        "erro_http": (
            "erro",
            "Buscar pedido: O servidor respondeu com erro do servidor (5xx). (HTTP 500)",
            [
                ("gatilho", "Início", "sucesso", {}, gatilho, None, 1),
                (
                    "http",
                    "Buscar pedido",
                    "erro",
                    _entrada(url),
                    erro500,
                    ("http_5xx", "O servidor respondeu com erro do servidor (5xx). (HTTP 500)"),
                    240,
                ),
                ("saida", "Resultado", "nao_executado", {}, {}, None, 0),
            ],
        ),
        "bloqueado_ssrf": (
            "erro",
            "Buscar metadados: Destino bloqueado por segurança: endereço não permitido.",
            [
                ("gatilho", "Início", "sucesso", {}, gatilho, None, 1),
                (
                    "http",
                    "Buscar metadados",
                    "erro",
                    {
                        **_entrada("http://169.254.169.254/latest/meta-data/"),
                        "headers": [],
                        "query": [],
                    },
                    {},
                    ("bloqueado_ssrf", "Destino bloqueado por segurança: endereço não permitido."),
                    3,
                ),
                ("saida", "Resultado", "nao_executado", {}, {}, None, 0),
            ],
        ),
    }


def criar_execucao(usuario, cenario="sucesso", fluxo=None, nome=None, minutos_atras=2):
    """Cria uma execução de exemplo: `sucesso`, `erro_http` ou `bloqueado_ssrf`."""
    status, resumo, nos = _cenarios(usuario)[cenario]
    inicio = timezone.now() - timedelta(minutes=minutos_atras)
    grafo = fluxo.grafo if fluxo is not None else None
    if grafo is None:
        from apps.fluxos.demo import grafo_exemplo

        grafo = grafo_exemplo()
    duracao = sum(no[6] for no in nos)
    execucao = Execucao.objects.create(
        fluxo=fluxo,
        fluxo_nome=nome or (fluxo.nome if fluxo else "Consulta de pedidos"),
        grafo_snapshot=mascarar_grafo(grafo),
        executado_por=usuario,
        setor_id=fluxo.setor_id if fluxo is not None else usuario.setor_id,
        status=status,
        iniciada_em=inicio,
        finalizada_em=inicio + timedelta(milliseconds=duracao),
        erro_resumo=resumo,
    )
    for ordem, (tipo, titulo, st, entrada, saida, falha, ms) in enumerate(nos):
        ExecucaoNo.objects.create(
            execucao=execucao,
            no_id=f"n{ordem + 1}",
            no_tipo=tipo,
            no_titulo=titulo,
            ordem=ordem,
            status=st,
            entrada=entrada,
            saida=saida,
            erro_categoria=falha[0] if falha else None,
            erro_mensagem=falha[1] if falha else "",
            duracao_ms=ms,
        )
    return execucao
