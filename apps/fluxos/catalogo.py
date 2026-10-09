"""Catálogo de tipos de nó do grafo v2 (NOV-01..06, MV2-02): chaves de config, tipos e alças.

Só dados e funções puras (sem Django): o validador (`grafo.py`), o executor e a importação usam
as mesmas definições. "Alças" são as saídas/entradas numeradas de um nó (aresta.saida/entrada).
"""

# Tipos de valor de config: "texto", "bool", "int", "numero", "lista", "obj", "texto?"
# (texto ou null), "obj?" (objeto ou null). Enums ficam em ENUMS_CONFIG (fora da lista = erro).
TIPOS_DE_NO = (
    "gatilho",
    "http",
    "codigo",
    "editar_campos",
    "filtrar",
    "se",
    "escolher",
    "juntar",
    "ordenar",
    "limitar",
    "remover_duplicados",
    "separar_lista",
    "agregar",
    "resumir",
    "data_hora",
    "repetir_em_lotes",
    "parar_com_erro",
    "sem_operacao",
    "saida",
)

ESQUEMA_CONFIG = {
    "gatilho": {},
    "saida": {},
    "sem_operacao": {},
    "http": {
        "metodo": "texto",
        "url": "texto",
        "headers": "lista",
        "query": "lista",
        "corpo": "obj",
        "credencial": "texto?",
        "resposta": "texto",
        "resposta_completa": "bool",
        "paginacao": "obj?",
    },
    "codigo": {"modo": "texto", "codigo": "texto"},
    "editar_campos": {
        "modo": "texto",
        "campos": "lista",
        "incluir_outros": "bool",
        "json": "texto",
    },
    "filtrar": {
        "condicoes": "lista",
        "combinar": "texto",
        "manter_descartados": "bool",
    },
    "se": {"condicoes": "lista", "combinar": "texto"},
    "escolher": {"regras": "lista", "saida_outros": "bool"},
    "juntar": {
        "modo": "texto",
        "campo1": "texto",
        "campo2": "texto",
        "tipo": "texto",
        "entrada": "int",
        "entradas": "int",
    },
    "ordenar": {"campos": "lista"},
    "limitar": {"quantidade": "int", "de": "texto"},
    "remover_duplicados": {"comparar": "texto", "campos": "lista"},
    "separar_lista": {"campo": "texto", "incluir": "texto"},
    "agregar": {"modo": "texto", "campos": "lista", "saida": "texto"},
    "resumir": {"agrupar_por": "lista", "operacoes": "lista"},
    "data_hora": {
        "operacao": "texto",
        "campo": "texto",
        "formato": "texto",
        "quantidade": "numero",
        "unidade": "texto",
        "saida": "texto",
    },
    "repetir_em_lotes": {"tamanho_lote": "int"},
    "parar_com_erro": {"mensagem": "texto"},
}

ENUMS_CONFIG = {
    ("http", "resposta"): ("json", "texto", "automatica"),
    ("codigo", "modo"): ("uma_vez_para_todos", "uma_vez_por_item"),
    ("editar_campos", "modo"): ("manual", "json"),
    ("filtrar", "combinar"): ("e", "ou"),
    ("se", "combinar"): ("e", "ou"),
    ("juntar", "modo"): (
        "anexar",
        "combinar_por_campo",
        "combinar_por_posicao",
        "escolher_entrada",
    ),
    ("juntar", "tipo"): ("dentro", "esquerda", "direita", "externa"),
    ("limitar", "de"): ("inicio", "fim"),
    ("remover_duplicados", "comparar"): ("todos", "campos"),
    ("separar_lista", "incluir"): ("nada", "campos_pai"),
    ("agregar", "modo"): ("campos", "todos"),
    (
        "data_hora",
        "operacao",
    ): ("agora", "formatar", "somar", "subtrair", "diferenca", "inicio_de"),
}

CHAVES_CORPO = {"tipo", "conteudo"}
TIPOS_DE_CORPO = ("nenhum", "json", "formulario", "texto")
EM_ERRO = ("parar", "continuar", "saida_de_erro")
CORES_NOTA = ("amarela", "azul", "verde", "cinza")
MAX_REGRAS_ESCOLHER = 10
ENTRADAS_JUNTAR = (2, 4)
SEM_ALCA_DE_ERRO = ("gatilho", "saida")

ROTULOS = {
    "gatilho": "Manual",
    "http": "Requisição HTTP",
    "codigo": "Código",
    "editar_campos": "Editar campos",
    "filtrar": "Filtrar",
    "se": "Se",
    "escolher": "Escolher",
    "juntar": "Juntar",
    "ordenar": "Ordenar",
    "limitar": "Limitar",
    "remover_duplicados": "Remover duplicados",
    "separar_lista": "Separar lista em itens",
    "agregar": "Agregar",
    "resumir": "Resumir",
    "data_hora": "Data e hora",
    "repetir_em_lotes": "Repetir em lotes",
    "parar_com_erro": "Parar com erro",
    "sem_operacao": "Sem operação",
    "saida": "Saída",
}


def _config(no):
    config = no.get("config") if isinstance(no, dict) else None
    return config if isinstance(config, dict) else {}


def n_entradas(no):
    """Quantas alças de entrada o nó tem (gatilho: 0; Juntar: 2..4; demais: 1)."""
    tipo = no.get("tipo")
    if tipo == "gatilho":
        return 0
    if tipo == "juntar":
        entradas = _config(no).get("entradas", 2)
        if isinstance(entradas, int) and not isinstance(entradas, bool):
            return min(max(entradas, ENTRADAS_JUNTAR[0]), ENTRADAS_JUNTAR[1])
        return ENTRADAS_JUNTAR[0]
    return 1


def n_saidas_normais(no):
    """Saídas "de dados" do nó, sem a alça de erro."""
    tipo, config = no.get("tipo"), _config(no)
    if tipo in ("saida", "parar_com_erro"):
        return 0
    if tipo == "se" or tipo == "repetir_em_lotes":
        return 2
    if tipo == "filtrar":
        return 2 if config.get("manter_descartados") is True else 1
    if tipo == "escolher":
        regras = config.get("regras")
        quantidade = len(regras) if isinstance(regras, list) else 0
        return quantidade + (1 if config.get("saida_outros") is True else 0)
    return 1


def tem_alca_de_erro(no):
    return no.get("em_erro") == "saida_de_erro" and no.get("tipo") not in SEM_ALCA_DE_ERRO


def n_saidas(no):
    """Total de alças de saída (inclui a de erro, sempre a última, quando em_erro=saida_de_erro)."""
    return n_saidas_normais(no) + (1 if tem_alca_de_erro(no) else 0)
