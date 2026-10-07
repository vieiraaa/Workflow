"""Fluxos de exemplo para a demo local (semear_demo) e para as capturas de tela."""

import copy

from .models import Fluxo, grafo_inicial


def _no(id_, tipo, titulo, x, y, **config):
    return {
        "id": id_,
        "tipo": tipo,
        "titulo": titulo,
        "posicao": {"x": x, "y": y},
        "config": config,
    }


def grafo_exemplo(url="https://api.exemplo.test/pedidos/1", titulo="Buscar pedido"):
    """Cadeia Gatilho → HTTP → Saída. Válida quando `url` é uma URL http(s) completa."""
    return {
        "versao": 1,
        "nos": [
            _no("n1", "gatilho", "Início", 80, 120),
            _no(
                "n2",
                "http",
                titulo,
                360,
                120,
                metodo="GET",
                url=url,
                headers=[{"nome": "Accept", "valor": "application/json"}],
                query=[{"nome": "detalhe", "valor": "completo"}],
                corpo="",
            ),
            _no("n3", "saida", "Resultado", 640, 120),
        ],
        "arestas": [{"de": "n1", "para": "n2"}, {"de": "n2", "para": "n3"}],
    }


def grafo_com_url_invalida():
    """Mesma cadeia, mas com a URL do nó HTTP inválida (pendência no nó n2)."""
    return grafo_exemplo(url="ftp://api.exemplo.test/pedidos")


def criar_fluxo(dono, nome, status="rascunho", grafo=None, descricao=""):
    return Fluxo.objects.create(
        nome=nome,
        descricao=descricao,
        dono=dono,
        status=status,
        grafo=copy.deepcopy(grafo if grafo is not None else grafo_inicial()),
    )


EXEMPLOS = [
    ("Consulta de pedidos", "ativo", grafo_exemplo, "Busca um pedido na API de exemplo."),
    (
        "Status do serviço",
        "ativo",
        lambda: grafo_exemplo("https://api.exemplo.test/saude", "Ver saúde"),
        "",
    ),
    ("Cotação de frete", "rascunho", grafo_exemplo, "Ainda em construção."),
    ("Rascunho sem saída", "rascunho", grafo_inicial, "Só o gatilho por enquanto."),
    (
        "Integração com URL errada",
        "rascunho",
        grafo_com_url_invalida,
        "Tem uma pendência no nó HTTP.",
    ),
]


def semear():
    """Cria os fluxos de exemplo que faltarem (idempotente, por nome)."""
    from apps.contas.models import Usuario

    dono = Usuario.objects.filter(email="coord@exemplo.test").first() or Usuario.objects.first()
    if dono is None:
        return 0
    criados = 0
    for nome, status, fabrica_grafo, descricao in EXEMPLOS:
        if not Fluxo.objects.filter(nome=nome).exists():
            criar_fluxo(dono, nome, status, fabrica_grafo(), descricao)
            criados += 1
    return criados
