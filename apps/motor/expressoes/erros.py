"""Erro das expressões (categoria `expressao`, MV2-12 L12)."""

CATEGORIA = "expressao"


class ErroExpressao(Exception):
    """`mensagem` é própria e segura (inclui um trecho da expressão, nunca texto de exceção)."""

    categoria = CATEGORIA

    def __init__(self, mensagem, trecho=None):
        if trecho is not None:
            trecho = " ".join(str(trecho).split())
            trecho = trecho if len(trecho) <= 60 else trecho[:57] + "..."
            mensagem = f"{mensagem} Trecho: {trecho}"
        super().__init__(mensagem)
        self.mensagem = mensagem


class ErroRespostaGrande(ErroExpressao):
    """Uso do corpo de uma resposta cortada no limite lido (SEG-07, MV2-24 d)."""

    categoria = "resposta_grande"


class CorpoCortado(str):
    """Texto do corpo de uma resposta HTTP cortada no limite lido: usá-lo num nó seguinte falha."""

    __slots__ = ()
