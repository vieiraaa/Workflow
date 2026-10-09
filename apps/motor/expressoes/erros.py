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
