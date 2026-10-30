"""Exportação para o CSLOG (D-064): de-para do Processo → linha do `processo.csv`.

O CSLOG não tem API de importação: o sistema gera o arquivo e alguém o importa lá. Funções puras
(sem banco nem rede), testadas em tests/unit/juridico/test_cslog.py. O CSLOG vem ANTES do Espaider.
"""

import csv
import io
import re

from . import cnj

ARQUIVO_PROCESSO = "processo.csv"
SEPARADOR = ";"
CODIFICACAO = "utf-8-sig"  # UTF-8 com BOM: o Excel BR abre com acentos
ADVOGADO_LOGIN = "MAGDA.LOGIN"
FILIAL = "Curitiba"

COLUNAS = (
    "CPF - AUTOR DA ACAO", "OPERACAO", "CONTRATO", "NUM_PROCESSO", "NUM_PROCESSO_UNICA", "VARA",
    "ESFERA", "COMARCA", "FORO", "UF", "TIPO_ACAO", "NUMERO_PASTA", "ADV_PARTE_CONTRARIA",
    "ADVOGADO_LOGIN", "ESTAGIARIO_LOGIN", "LOCALIZADOR_CPF/CNPJ", "FILIAL", "STATUS_FINALIZADO",
    "DATA_DISTRIBUICAO", "VALOR_CAUSA", "CONTRATOS", "ID_JUIZ", "NOME_JUIZ", "VENC_PARC_AJUIZ",
    "PLATAFORMA",
)  # fmt: skip

# Base de tipos de ação do CSLOG (carteira Veículo): (processo/subprocesso, grupo, ID_TIPO, nome).
# Os IDs se repetem entre Processo e Sub Processo (0, 1, 3...): a chave da tela é "P<id>"/"S<id>".
PROCESSO, SUBPROCESSO = "P", "S"
CONTRA, PRO, OUTROS, SUB = "Contra", "Pró", "Outros", "Subprocesso"
TIPOS = (
    (PROCESSO, CONTRA, 169, "Administrativo (Contra)"),
    (PROCESSO, CONTRA, 17, "Consignatória (Contra)"),
    (PROCESSO, CONTRA, 159, "Cumprimento de Sentença (Contra)"),
    (PROCESSO, CONTRA, 33, "Embargos à Execução (Contra)"),
    (PROCESSO, CONTRA, 28, "Embargos de Terceiro (Contra)"),
    (PROCESSO, CONTRA, 196, "Exceção de Pré-Executividade"),
    (PROCESSO, CONTRA, 118, "Execução (Contra)"),
    (PROCESSO, CONTRA, 34, "Exibição de Documentos"),
    (PROCESSO, CONTRA, 149, "Falência (Contra)"),
    (PROCESSO, CONTRA, 8, "Indenizatória (Contra)"),
    (PROCESSO, CONTRA, 258, "Inexigibilidade"),
    (PROCESSO, CONTRA, 35, "Mandado de Segurança (Contra)"),
    (PROCESSO, CONTRA, 20, "Medida Cautelar (Contra)"),
    (PROCESSO, CONTRA, 85, "Notificação"),
    (PROCESSO, CONTRA, 86, "Ofício"),
    (PROCESSO, CONTRA, 161, "Outros Feitos (Contra)"),
    (PROCESSO, CONTRA, 257, "Pré processual"),
    (PROCESSO, CONTRA, 37, "Prestação de Contas"),
    (PROCESSO, CONTRA, 188, "Reclamação Procon (Contra)"),
    (PROCESSO, CONTRA, 162, "Recuperação Judicial (Contra)"),
    (PROCESSO, CONTRA, 36, "Repetição de Indébito"),
    (PROCESSO, CONTRA, 92, "Rescisória (Contra)"),
    (PROCESSO, CONTRA, 7, "Revisional"),
    (PROCESSO, CONTRA, 195, "SuperEndividamento (Contra)"),
    (PROCESSO, CONTRA, 259, "Sustação de protesto"),
    (PROCESSO, OUTROS, 26, "Criminal"),
    (PROCESSO, OUTROS, 190, "Entrega Amigável"),
    (PROCESSO, OUTROS, 21, "Inquérito Policial"),
    (PROCESSO, OUTROS, 165, "Processo de Interesse"),
    (PROCESSO, PRO, 168, "Administrativo (Pró)"),
    (PROCESSO, PRO, 170, "Anulatória (Pró)"),
    (PROCESSO, PRO, 3, "BA- Ação de Execução"),
    (PROCESSO, PRO, 1, "Busca e Apreensão"),
    (PROCESSO, PRO, 105, "Cobrança (Pró)"),
    (PROCESSO, PRO, 158, "Cumprimento de Sentença (Pró)"),
    (PROCESSO, PRO, 102, "Embargos à Execução (Pró)"),
    (PROCESSO, PRO, 106, "Embargos de Terceiro (Pró)"),
    (PROCESSO, PRO, 4, "Execução (Pró)"),
    (PROCESSO, PRO, 186, "Mandado de Segurança (Pró)"),
    (PROCESSO, PRO, 187, "Medida Cautelar (Pró)"),
    (PROCESSO, PRO, 31, "Monitória"),
    (PROCESSO, PRO, 160, "Outros Feitos (Pró)"),
    (PROCESSO, PRO, 0, "Reint. de Posse"),
    (PROCESSO, PRO, 184, "Requerimento de Desbloqueio"),
    (PROCESSO, PRO, 150, "Rescisória (Pró)"),
    (PROCESSO, PRO, 189, "Restituição de Coisa Apreendida (Pró)"),
    (SUBPROCESSO, SUB, 46, "Agravo ao STJ"),
    (SUBPROCESSO, SUB, 0, "Agravo de Instrumento"),
    (SUBPROCESSO, SUB, 47, "Agravo Interno"),
    (SUBPROCESSO, SUB, 25, "Apelação"),
    (SUBPROCESSO, SUB, 48, "Apreensão em Comarca Distinta"),
    (SUBPROCESSO, SUB, 62, "Arguição de Suspeição e de Impedimento"),
    (SUBPROCESSO, SUB, 1, "Carta Precatória"),
    (SUBPROCESSO, SUB, 59, "Cumprimento de Sentença (Contra)"),
    (SUBPROCESSO, SUB, 58, "Cumprimento de Sentença (Pró)"),
    (SUBPROCESSO, SUB, 29, "Embargos de Declaração"),
    (SUBPROCESSO, SUB, 6, "Exceção de Incompetência"),
    (SUBPROCESSO, SUB, 50, "Habilitação de Crédito"),
    (SUBPROCESSO, SUB, 67, "Impugnação de crédito"),
    (SUBPROCESSO, SUB, 45, "Liquidação de Sentença"),
    (SUBPROCESSO, SUB, 63, "Pedido de providências"),
    (SUBPROCESSO, SUB, 49, "Processo Administrativo"),
    (SUBPROCESSO, SUB, 2, "Rec. Especial"),
    (SUBPROCESSO, SUB, 3, "Rec. Extraordinário"),
    (SUBPROCESSO, SUB, 30, "Rec. Inominado"),
    (SUBPROCESSO, SUB, 64, "Reclamação disciplinar"),
    (SUBPROCESSO, SUB, 65, "Reclamação para garantia das decisões"),
    (SUBPROCESSO, SUB, 68, "Recurso Ordinário"),
    (SUBPROCESSO, SUB, 66, "Representação por excesso de prazo"),
    (SUBPROCESSO, SUB, 52, "Restauração de Autos"),
)
POR_CHAVE = {f"{nivel}{id_}": (nivel, grupo, id_, nome) for nivel, grupo, id_, nome in TIPOS}

# Classe do processo (texto sem acento, minúsculo) → tipo. Ordem importa: a primeira regra que
# casa vence. (palavras, ID Contra, ID Pró); None = não existe naquele polo (usa o outro).
REGRAS_SUBPROCESSO = (
    (("agravo de instrumento",), 0),
    (("agravo interno", "agravo regimental"), 47),
    (("agravo em recurso especial", "agravo ao stj", "agravo em recurso extraordinario"), 46),
    (("embargos de declaracao",), 29),
    (("apelacao",), 25),
    (("recurso especial",), 2),
    (("recurso extraordinario",), 3),
    (("recurso inominado",), 30),
    (("recurso ordinario",), 68),
    (("carta precatoria",), 1),
    (("excecao de incompetencia",), 6),
    (("habilitacao de credito",), 50),
    (("impugnacao de credito",), 67),
    (("liquidacao de sentenca", "liquidacao por"), 45),
    (("restauracao de autos",), 52),
    (("suspeicao", "impedimento"), 62),
    (("apreensao em comarca distinta",), 48),
    (("pedido de providencias",), 63),
    (("reclamacao disciplinar",), 64),
    (("excesso de prazo",), 66),
)
REGRAS_PROCESSO = (
    (("superendividamento",), 195, None),
    (("recuperacao judicial",), 162, None),
    (("falencia",), 149, None),
    (("cumprimento de sentenca",), 159, 158),
    (("embargos a execucao", "embargos do devedor", "embargos de devedor"), 33, 102),
    (("embargos de terceiro",), 28, 106),
    (("excecao de pre",), 196, None),
    (("busca e apreensao",), None, 1),
    (("reintegracao de posse",), None, 0),
    (("restituicao de coisa apreendida",), None, 189),
    (("desbloqueio",), None, 184),
    (("monitoria",), None, 31),
    (("execucao",), 118, 4),
    (("consignat",), 17, None),
    (("exibicao de documento", "producao antecipada"), 34, None),
    (("prestacao de contas", "exigir contas"), 37, None),
    (("mandado de seguranca",), 35, 186),
    (("cautelar",), 20, 187),
    (("procon",), 188, None),
    (("repeticao de indebito",), 36, None),
    (("revisional", "revisao de contrato", "revisao contratual"), 7, None),
    (("rescisoria",), 92, 150),
    (("sustacao de protesto", "cancelamento de protesto"), 259, None),
    (("anulatoria",), None, 170),
    (("inexistencia", "inexigibilidade", "inexigivel", "inexistente", "declaratoria"), 258, None),
    (("indenizacao", "indenizatoria", "danos morais", "danos materiais", "reparacao"), 8, None),
    (("cobranca",), 161, 105),
    (("pre-processual", "pre processual", "reclamacao pre"), 257, None),
    (("notificacao",), 85, None),
    (("oficio",), 86, None),
    (("administrativ",), 169, 168),
)
# Classe genérica ("Procedimento Comum Cível"): olha os pedidos e assuntos, só com as regras de
# mérito (pedidos falam em "execução", "cobrança indevida"... sem ser a classe da ação).
REGRAS_PEDIDOS = (
    (("superendividamento",), 195, None),
    (("inexistencia", "inexigibilidade", "inexigivel", "inexistente"), 258, None),
    (("revisional", "revisao de contrato", "revisao contratual"), 7, None),
    (("repeticao de indebito", "repeticao do indebito"), 36, None),
    (("exibicao de documento",), 34, None),
    (("prestacao de contas", "exigir contas"), 37, None),
    (("sustacao de protesto", "cancelamento de protesto"), 259, None),
    (("indenizacao", "danos morais", "danos materiais"), 8, None),
)
OUTROS_FEITOS = (161, 160)

_RE_CONTRA = re.compile(
    r"\b(reu|re|reus|requerid[oa]s?|executad[oa]s?|embargad[oa]s?|impetrad[oa]s?|demandad[oa]s?|"
    r"reclamad[oa]s?|apelad[oa]s?|agravad[oa]s?|recorrid[oa]s?|promovid[oa]s?)\b"
)
_RE_PRO = re.compile(
    r"\b(autor[a]?(es)?|requerentes?|exequentes?|embargantes?|impetrantes?|demandantes?|"
    r"reclamantes?|apelantes?|agravantes?|recorrentes?|promoventes?|credor[a]?)\b"
)
_RE_DOCUMENTO = re.compile(r"\d[\d.\-/ ]{9,20}\d")
_RE_CONTRATOS = re.compile(r"[,;|\n]+")
_INICIO_FORMULA = "=+-@\t\r"  # célula começando assim vira fórmula no Excel


def chave(nivel, id_):
    return f"{nivel}{id_}"


def rotulo(chave_tipo):
    """'8 · Indenizatória (Contra)' ou '' (chave desconhecida)."""
    tipo = POR_CHAVE.get(chave_tipo)
    return f"{tipo[2]} · {tipo[3]}" if tipo else ""


def grupos_para_select():
    """[(grupo, [(chave, rótulo)])] na ordem da base, para o <select> com <optgroup>."""
    ordem = {}
    for nivel, grupo, id_, _nome in TIPOS:
        ordem.setdefault(grupo, []).append((chave(nivel, id_), rotulo(chave(nivel, id_))))
    return list(ordem.items())


def polo(condicao):
    """Polo do cliente pela condição ('Réu' → Contra; 'Autor'/'Exequente' → Pró; senão None)."""
    texto = cnj.sem_acento(condicao)
    if _RE_CONTRA.search(texto):
        return CONTRA
    if _RE_PRO.search(texto):
        return PRO
    return None


def _aplicar(regras, texto, polo_cliente):
    for palavras, id_contra, id_pro in regras:
        if any(p in texto for p in palavras):
            preferido, outro = (id_pro, id_contra) if polo_cliente == PRO else (id_contra, id_pro)
            return chave(PROCESSO, preferido if preferido is not None else outro)
    return None


def sugerir_tipo(processo):
    """(chave, motivo) do tipo de ação no CSLOG mais parecido com a classe do processo. Polo pela
    condição (sem condição = Contra, o caso comum do escritório); classe genérica → pedidos."""
    classe = cnj.sem_acento(processo.tipo_acao)
    polo_cliente = polo(processo.condicao)
    sem_polo = "" if polo_cliente else " (polo não informado: considerado Contra)"
    for palavras, id_ in REGRAS_SUBPROCESSO:
        if any(p in classe for p in palavras):
            return chave(SUBPROCESSO, id_), "sugerido pela classe"
    if achado := _aplicar(REGRAS_PROCESSO, classe, polo_cliente):
        return achado, f"sugerido pela classe{sem_polo}"
    merito = cnj.sem_acento(f"{processo.pedidos} {processo.assuntos_cnj}")
    if achado := _aplicar(REGRAS_PEDIDOS, merito, polo_cliente):
        return achado, f"sugerido pelos pedidos{sem_polo}"
    padrao = OUTROS_FEITOS[1] if polo_cliente == PRO else OUTROS_FEITOS[0]
    return chave(PROCESSO, padrao), f"nenhuma regra reconheceu a classe{sem_polo}"


# ---------------------------------------------------------------- valores das colunas
def documento(texto):
    """Primeiro CPF (11 dígitos) ou CNPJ (14) do texto, com máscara; '' se não houver."""
    for trecho in _RE_DOCUMENTO.findall(texto or ""):
        d = cnj.so_digitos(trecho)
        if len(d) == 11:
            return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
        if len(d) == 14:
            return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return ""


def contratos(texto):
    """Números de contrato de 'operações vinculadas' ('1, 2; 3' → ['1', '2', '3'])."""
    return [c.strip() for c in _RE_CONTRATOS.split(texto or "") if c.strip()]


def uf(processo):
    """UF do cadastro; sem ela, a do número CNJ (Justiça Estadual ou Eleitoral)."""
    if (processo.estado or "").strip():
        return processo.estado.strip().upper()[:2]
    digitos = cnj.so_digitos(processo.numero)
    if len(digitos) == 20 and digitos[13] in "86":
        tr = int(digitos[14:16])
        if 1 <= tr <= len(cnj.UFS):
            sigla = cnj.UFS[tr - 1].upper()
            return "DF" if sigla == "DFT" else sigla
    return ""


def login_do_usuario(usuario):
    """Login do CSLOG de quem gera o arquivo: a parte do e-mail antes do @, em maiúsculas."""
    return (usuario.email or "").split("@")[0].upper()


def data_br(valor):
    return valor.strftime("%d/%m/%Y") if valor else ""


def valor_br(valor):
    """1234.5 → '1234,50' (sem separador de milhar: é dado de importação, não tela)."""
    return f"{valor:.2f}".replace(".", ",") if valor is not None else ""


def faltando(processo):
    """Rótulos do que falta para o CSLOG; os dois primeiros impedem gerar a linha."""
    itens = []
    if not processo.numero_valido:
        itens.append("número CNJ válido")
    if not documento(processo.adverso_cpf_cnpj):
        itens.append("CPF/CNPJ do autor")
    for rotulo_, valor in (
        ("comarca", processo.comarca),
        ("UF", uf(processo)),
        ("juízo", processo.juizo),
        ("distribuição", processo.distribuido_em),
        ("valor da causa", processo.valor_causa),
    ):
        if valor in (None, ""):
            itens.append(rotulo_)
    return itens


def bloqueio(processo):
    """Motivo para NÃO entrar no CSV ('' = pode): sem número válido ou sem CPF/CNPJ do autor."""
    if not processo.numero_valido:
        return "Sem número CNJ válido"
    if not documento(processo.adverso_cpf_cnpj):
        return "Sem CPF/CNPJ do autor"
    return ""


def linha(processo, chave_tipo, login_estagiario):
    """Dict coluna → valor do processo.csv."""
    cpf = documento(processo.adverso_cpf_cnpj)
    lista = contratos(processo.operacoes_vinculadas)
    tipo = POR_CHAVE.get(chave_tipo)
    valores = {
        "CPF - AUTOR DA ACAO": cpf,
        "CONTRATO": lista[0] if lista else cpf,
        "NUM_PROCESSO_UNICA": cnj.formatar(processo.numero),
        "VARA": processo.juizo,
        "ESFERA": processo.juizo,
        "COMARCA": processo.comarca,
        "FORO": processo.comarca,
        "UF": uf(processo),
        "TIPO_ACAO": str(tipo[2]) if tipo else "",
        "ADV_PARTE_CONTRARIA": processo.advogado_adverso_nome,
        "ADVOGADO_LOGIN": ADVOGADO_LOGIN,
        "ESTAGIARIO_LOGIN": login_estagiario,
        "FILIAL": FILIAL,
        "DATA_DISTRIBUICAO": data_br(processo.distribuido_em),
        "VALOR_CAUSA": valor_br(processo.valor_causa),
        "CONTRATOS": ", ".join(lista),
    }
    return {coluna: _celula(valores.get(coluna, "")) for coluna in COLUNAS}


def _celula(valor):
    """Uma linha só, sem espaço sobrando e sem virar fórmula ao abrir no Excel."""
    texto = " ".join(str(valor or "").split())
    return texto.lstrip(_INICIO_FORMULA)


def gerar_csv(linhas):
    """Texto do CSV (cabeçalho + linhas), separador ';' e fim de linha CRLF."""
    saida = io.StringIO()
    escritor = csv.DictWriter(saida, fieldnames=COLUNAS, delimiter=SEPARADOR, lineterminator="\r\n")
    escritor.writeheader()
    escritor.writerows(linhas)
    return saida.getvalue()
