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
    fluxo = Fluxo(
        nome=nome,
        descricao=descricao,
        dono=dono,
        status=status,
        grafo=copy.deepcopy(grafo if grafo is not None else grafo_inicial()),
    )
    fluxo.full_clean()  # a semeadura também respeita o formato canônico (GRF-09)
    fluxo.save()
    return fluxo


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
    _semear_execucoes()
    return criados


def _semear_execucoes():
    """Execuções de exemplo (sucesso, erro HTTP, bloqueio SSRF) se ainda não houver nenhuma."""
    from apps.contas.models import Usuario
    from apps.execucoes import demo as demo_execucoes
    from apps.execucoes.models import Execucao

    if Execucao.objects.exists():
        return
    fluxo = Fluxo.objects.filter(nome="Consulta de pedidos").first()
    for email, cenario, minutos in (
        ("coord@exemplo.test", "sucesso", 90),
        ("base@exemplo.test", "sucesso", 40),
        ("base@exemplo.test", "erro_http", 20),
        ("coord@exemplo.test", "bloqueado_ssrf", 5),
    ):
        usuario = Usuario.objects.filter(email=email).first()
        if usuario:
            demo_execucoes.criar_execucao(usuario, cenario, fluxo=fluxo, minutos_atras=minutos)
