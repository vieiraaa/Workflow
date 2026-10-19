"""Erros do motor: falha de nó com categoria (SEG-10 + MV2-12 L12) e mensagem própria."""

CATEGORIAS_NOVAS = (
    "expressao",
    "codigo",
    "codigo_limite",
    "credencial",
    "limite_itens",
    "parado",
    "paginacao",
    "laco_excessivo",
    "codigo_indisponivel",
    "resposta_invalida",
)


class FluxoComPendencias(Exception):
    """O grafo tem pendências (EXE-02): nenhuma execução é criada."""

    def __init__(self, pendencias):
        super().__init__("grafo com pendências")
        self.pendencias = pendencias


class FalhaNo(Exception):
    """Falha de um nó/item com `categoria` e `mensagem` próprias (nunca texto de exceção de driver).

    `saida` e `requisicao` são diagnósticos opcionais já mascarados pelo executor na gravação.
    """

    def __init__(self, categoria, mensagem, saida=None, requisicao=None):
        super().__init__(mensagem)
        self.categoria = categoria
        self.mensagem = mensagem
        self.saida = saida or {}
        self.requisicao = requisicao

    def como_dict(self):
        return {"categoria": self.categoria, "mensagem": self.mensagem}
