"""T-078: lógica pura do cadastro (CNJ, leitura do Dify, mesclagem, audiências, máscara, TLS)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.juridico import apresentacao, clientes, cnj, leitura, mescla, servico
from apps.juridico.models import Processo

pytestmark = pytest.mark.modulo("m8")


# ---------------------------------------------------------------- CNJ
def test_numero_cnj_valido_formato_e_alias():
    numero = cnj.numero_valido_de(1234567, 2024, 8, 26, 1)
    assert cnj.valido(numero) and cnj.valido(cnj.so_digitos(numero))
    assert not cnj.valido(numero[:-1] + "9") and not cnj.valido("123")
    assert cnj.alias_datajud(numero) == "tjsp" and cnj.sigla_tribunal(numero) == "TJSP"
    assert cnj.formatar("12345671920248260001") == numero


@pytest.mark.parametrize(
    ("j", "tr", "alias"),
    [(8, 19, "tjrj"), (4, 3, "trf3"), (5, 9, "trt9"), (6, 26, "tre-sp"), (1, 1, None)],
)
def test_alias_datajud(j, tr, alias):
    assert cnj.alias_datajud(cnj.numero_valido_de(10, 2022, j, tr, 100)) == alias


# ---------------------------------------------------------------- máscara e formatos
@pytest.mark.parametrize(
    ("entrada", "saida"),
    [
        ("123.456.789-09", "***.456.789-**"),
        ("12.345.678/0001-95", "**.345.678/0001-**"),
        ("12345", "•••"),
        ("123.456.789-09; 12.345.678/0001-95", "***.456.789-**; **.345.678/0001-**"),
        ("", ""),
    ],
)
def test_mascara_de_documento(entrada, saida):
    assert apresentacao.mascarar_documento(entrada) == saida


def test_valor_e_data_formatados():
    assert apresentacao.valor_texto(Decimal("1234.5")) == "R$ 1.234,50"
    assert apresentacao.valor_texto(None) == ""


# ---------------------------------------------------------------- leitura do Dify (CAD-08)
RESPOSTA = """```json
{"Numero Processo": "0001234-42.2022.8.26.0100", "adverso": "Fulano", "empresa": "ATIVOS S.A.",
 "valor da causa": "R$ 1.234,56", "distribuido_em": "15/03/2022", "tribunal": "tj-sp",
 "comarca": "Não localizado no PDF", "fase_atual": "EXECUÇÃO/CUMPRIMENTO",
 "andamentos": [{"data": "10/01/2023", "evento": "Juntada"}]}
```"""


def test_leitura_aceita_alternativas_cercas_e_converte():
    campos, pendencias = leitura.ler_resposta(RESPOSTA)
    assert campos["numero"] == "0001234-42.2022.8.26.0100" and campos["adverso_nome"] == "Fulano"
    assert campos["valor_causa"] == Decimal("1234.56") and campos["comarca"] == ""
    assert str(campos["distribuido_em"]) == "2022-03-15" and campos["tribunal"] == "TJ-SP"
    assert campos["fase_atual"] == "EXECUCAO_CUMPRIMENTO"
    assert campos["andamentos"] == [{"data": "2023-01-10", "evento": "Juntada", "fonte": "pdf"}]
    assert pendencias == []


def test_leitura_valor_ilegivel_vira_pendencia():
    resposta = '{"numero_cnj": "x", "empresa": "a", "adverso_nome": "b", "valor_causa": "muito"}'
    campos, pendencias = leitura.ler_resposta(resposta)
    assert campos["valor_causa"] is None and pendencias == ["Valor da causa ilegível: muito"]


@pytest.mark.parametrize(
    ("resposta", "mensagem"),
    [
        ("sem json", leitura.MSG_FORMATO),
        ("{quebrado", leitura.MSG_FORMATO),
        ('{"numero_cnj": "x"}', leitura.MSG_SEM_DADOS),
        ("{" * 50 + "}" * 50, leitura.MSG_FORMATO),
    ],
)
def test_leitura_erros(resposta, mensagem):
    with pytest.raises(leitura.ErroLeitura) as erro:
        leitura.ler_resposta(resposta)
    assert erro.value.mensagem == mensagem


def test_normalizar_e_cortar_texto():
    assert leitura.normalizar_texto("a  \t b \n\n  c  ") == "a b\nc"
    longo = "a" * 100
    assert leitura.cortar(longo, 200, 10, 5) == longo
    cortado = leitura.cortar(longo, 50, 10, 5)
    assert cortado == "a" * 10 + "\n[... trecho do meio omitido ...]\n" + "a" * 5


@pytest.mark.parametrize(
    ("texto", "valor"),
    [("R$ 1.234,56", "1234.56"), ("1234,56", "1234.56"), ("1234.56", "1234.56"), ("x", None)],
)
def test_converter_valor(texto, valor):
    assert leitura.converter_valor(texto) == (Decimal(valor) if valor else None)


# ----------------------------------------------------- mesclagem (CAD-11) e audiências (CAD-20)
def _processo(**campos):
    return Processo(numero="1", numero_digitos="1", origem_campos={}, **campos)


def test_pdf_substitui_e_cnj_so_preenche_vazio():
    processo = _processo(comarca="Antiga", juizo="")
    processo.pk = 1  # processo já existente: anota a mudança nas observações
    mudou = mescla.aplicar_pdf(processo, {"comarca": "Nova", "tribunal": "TJSP"})
    assert set(mudou) == {"comarca", "tribunal"} and processo.origem_campos["comarca"] == "pdf"
    assert "Atualizado pelo PDF em" in processo.observacoes
    mescla.aplicar_cnj(processo, {"comarca": "Do CNJ", "juizo": "1ª Vara"})
    assert processo.comarca == "Nova" and processo.juizo == "1ª Vara"
    assert processo.origem_campos["juizo"] == "cnj" and processo.origem_campos["comarca"] == "pdf"


def test_andamentos_sem_repetir_em_ordem_decrescente_com_limites():
    pdf = [{"data": f"2023-01-{d:02d}", "evento": f"e{d}", "fonte": "pdf"} for d in range(1, 8)]
    cnj_itens = [{"data": "2023-01-07", "evento": "E7", "fonte": "cnj"}]
    unidos = mescla.juntar_andamentos([], pdf, "pdf")
    datas = [a["data"] for a in unidos]
    assert datas == [f"2023-01-0{d}" for d in (7, 6, 5, 4, 3)]
    unidos = mescla.juntar_andamentos(unidos, cnj_itens, "cnj")
    assert len(unidos) == 5  # o do CNJ repete data+texto de um do PDF


def test_recalcular_pendencias_e_status():
    processo = _processo(numero_valido=False, criado_via="pdf")
    faltando = mescla.recalcular(processo)
    assert "Número" not in faltando  # o número existe; só o resto falta
    assert processo.status == Processo.COM_PENDENCIAS
    assert mescla.MSG_DV in processo.pendencias
    assert "Carteira não identificada." in processo.pendencias
    cadastrado = _processo(numero_valido=True, status=Processo.CADASTRADO)
    mescla.recalcular(cadastrado)
    assert cadastrado.status == Processo.CADASTRADO  # nunca volta sozinho


def test_extrair_audiencia_pega_a_futura_mais_proxima():
    agora = timezone.now()
    futura = (agora + timedelta(days=3)).astimezone()
    passada = (agora - timedelta(days=3)).astimezone()
    mais_longe = (agora + timedelta(days=30)).astimezone()

    def frase(quando, formato="às {:%H:%M}"):
        horario = formato.format(quando)
        return f"Audiência de conciliação designada para {quando:%d/%m/%Y}, {horario}."

    processo = _processo(
        observacoes=frase(passada) + " " + frase(mais_longe),
        andamentos=[{"data": "", "evento": frase(futura, "{0:%H}h{0:%M}")}],
    )
    achada = mescla.extrair_audiencia(processo, agora)
    assert achada.date() == futura.date() and achada.hour == futura.hour
    processo.origem_campos["proxima_audiencia"] = "manual"
    anterior = processo.proxima_audiencia
    mescla.atualizar_audiencia(processo, agora)
    assert processo.proxima_audiencia == anterior  # edição manual vale


def test_comparacao_com_datajud():
    processo = _processo(tribunal="TJ-SP", comarca="São Paulo")
    fonte = {
        "tribunal": "TJSP",
        "dataAjuizamento": "2022-03-15T00:00:00.000Z",
        "orgaoJulgador": {"nome": "1ª Vara Cível do Foro Central de SÃO PAULO"},
    }
    processo.distribuido_em = timezone.datetime(2022, 3, 15).date()
    assert mescla.comparar(processo, fonte) == []
    processo.comarca, processo.tribunal = "Santos", "TJRJ"
    divergencias = mescla.comparar(processo, fonte)
    assert [d.split(" ")[0] for d in divergencias] == ["tribunal", "comarca"]


# ---------------------------------------------------------------- serviço e TLS
def test_nome_seguro_e_separar_numeros():
    assert servico.nome_seguro('..\\pasta/a"b.pdf') == "a_b.pdf"
    assert servico.nome_seguro("") == "arquivo.pdf"
    assert servico.separar_numeros("1\n2, 1;3\r\n\n") == ["1", "2", "3"]


def test_pem_invalido_e_contextos_tls():
    with pytest.raises(ValueError, match="Certificado inválido"):
        clientes.validar_pem("isto não é um certificado")
    with pytest.raises(ValueError, match="Certificado inválido"):
        clientes.validar_pem("-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----")
    clientes.validar_pem("")  # vazio = cadeia padrão
    contextos = clientes.contextos_tls("https://dify.exemplo.test/api", "")
    assert contextos[0] is None and len(contextos) in (1, 2)  # padrão (+ truststore, se carregar)
