"""Aceite M8 · worker, Dify, leitura da resposta, status e pendências (CAD-07, CAD-08, CAD-09, CAD-12, CAD-13). Só pela spec."""
import json
from decimal import Decimal

import pytest
from django.urls import reverse

from .conftest import (
    SEGREDO_DIFY,
    campos_dify,
    cnj,
    pdf_bytes,
    pdf_escaneado,
    pdf_processo,
    texto_processo,
    upload,
)

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

NUM, DIG = cnj(1234)


def _processo(cad):
    return cad.Processo.objects.get()


# ---------------- caminho feliz e chamada ao Dify (CAD-07) ----------------

def test_pdf_com_texto_vira_processo_pelo_dify(cad, ingerir):
    """CAD-07/08: PDF com texto → chat-messages → Processo criado com os campos mapeados (CAD-23 1_dify), item concluido/novo."""
    item, p = ingerir(cad.ana, NUM, carteira=cad.carteiras["Ativos"])
    assert item.status == "concluido" and item.acao == "novo" and p is not None and item.tentativas >= 0
    assert (p.numero, p.numero_digitos, p.numero_valido) == (NUM, DIG, True)
    assert p.adverso_nome == "João da Silva Fictício" and p.adverso_cpf_cnpj == "123.456.789-09"
    assert p.tribunal == "TJSP" and p.comarca == "São Paulo" and p.juizo == "1ª Vara Cível" and p.estado == "SP"
    assert p.empresa.startswith("ATIVOS") and p.condicao == "Autor" and p.advogado_empresa == "Dra. Helena Fictícia"
    assert p.advogado_adverso_nome == "Dr. Pedro Fictício" and p.advogado_adverso_oab == "OAB/SP 123456"
    assert p.tipo_acao == "Ação de Cobrança" and p.rito == "Comum" and p.natureza == "Cível" and p.instancia == "1º Grau"
    assert p.operacoes_vinculadas == "OP-998877" and p.pedidos == "Condenação ao pagamento do valor devido."
    assert str(p.distribuido_em) == "2022-03-15" and str(p.data_citacao) == "2022-04-20" and p.valor_causa == Decimal("1234.56")
    assert p.criado_por == cad.ana_u and p.criado_via == "pdf" and p.carteira == cad.carteiras["Ativos"]
    assert item.processo_id == p.pk


def test_chamada_ao_dify_tem_o_formato_da_spec(cad, ingerir):
    """CAD-07: POST {dify_url}/chat-messages com {inputs: {}, query, response_mode: blocking, user: dify_usuario} e Bearer da credencial."""
    ingerir(cad.ana, NUM)
    (req,) = cad.dify.chats_req
    corpo = json.loads(req["corpo"])
    assert req["metodo"] == "POST" and req["headers"]["authorization"] == f"Bearer {SEGREDO_DIFY}"
    assert corpo["inputs"] == {} and corpo["response_mode"] == "blocking" and corpo["user"] == "construtor-espaider"
    assert NUM in corpo["query"] and not corpo.get("files") and cad.dify.uploads == []


def test_usuario_do_dify_vem_da_configuracao(cad, ingerir):
    """CAD-14/07: o `user` enviado é o dify_usuario configurado."""
    cad.config.dify_usuario = "usuario-de-teste-9"
    cad.config.save()
    ingerir(cad.ana, NUM)
    assert cad.dify.chats[0]["user"] == "usuario-de-teste-9"


def test_query_e_o_texto_normalizado(cad, enviar, rodar):
    """CAD-23 query_texto: espaços/tabs → 1 espaço; quebras com espaços em volta → 1 quebra; trim."""
    texto = "  Linha   um\t\tcom   tabs  \n   \n  Linha dois " + "x" * 300 + f" {NUM}  "
    enviar(cad.ana, (pdf_bytes(texto, numero=NUM), "n.pdf"))
    rodar()
    q = cad.dify.chats[0]["query"]
    assert q == q.strip() and "  " not in q and "\t" not in q and " \n" not in q and "\n " not in q
    assert q.startswith("Linha um com tabs") and "Linha dois" in q


def test_texto_ate_40000_nao_e_cortado(cad, enviar, rodar):
    """CAD-07: texto de exatamente 40.000 caracteres vai inteiro."""
    t = (f"{NUM} " + "palavra " * 6000)[:40000].rstrip()
    t = t + "y" * (40000 - len(t))
    enviar(cad.ana, (pdf_bytes(t, numero=NUM), "g.pdf"))
    rodar()
    assert cad.dify.chats[0]["query"] == t and "trecho do meio omitido" not in cad.dify.chats[0]["query"]


def test_texto_acima_de_40000_vira_25000_marcador_15000(cad, enviar, rodar):
    """CAD-07: > 40.000 → primeiros 25.000 + '\\n[... trecho do meio omitido ...]\\n' + últimos 15.000."""
    corpo = f"{NUM} " + "".join(f"w{i:05d} " for i in range(8000))
    t = corpo.strip()
    assert len(t) > 40000
    enviar(cad.ana, (pdf_bytes(t, numero=NUM), "g.pdf"))
    rodar()
    q = cad.dify.chats[0]["query"]
    marcador = "\n[... trecho do meio omitido ...]\n"
    assert q == t[:25000] + marcador + t[-15000:] and len(q) == 25000 + len(marcador) + 15000


def test_texto_curto_usa_upload_e_files(cad, enviar, rodar):
    """CAD-07: texto < 200 caracteres → files/upload (multipart file+user) e chat-messages com a query literal e files[]."""
    enviar(cad.ana, (pdf_bytes(f"curto {NUM}", numero=NUM), "curto.pdf"))
    rodar()
    (up,) = cad.dify.uploads
    assert up["headers"]["content-type"].startswith("multipart/form-data") and f"Bearer {SEGREDO_DIFY}" == up["headers"]["authorization"]
    assert "construtor-espaider" in up["corpo"] and "%PDF-" in up["corpo"]
    (chat,) = cad.dify.chats
    assert chat["query"] == ("O processo está no PDF ANEXADO (pode ser escaneado ou protegido contra cópia). Leia o arquivo inteiro, "
                             "página por página, e extraia os dados seguindo exatamente as instruções e o formato JSON.")
    assert chat["response_mode"] == "blocking" and chat["inputs"] == {}
    (f,) = chat["files"]
    assert f["type"] == "document" and f["transfer_method"] == "local_file" and f["upload_file_id"].startswith("up-")


def test_pdf_sem_texto_escaneado_usa_upload(cad, ingerir):
    """CAD-07: PDF sem texto → upload; o resultado chega ao processo normalmente."""
    item, p = ingerir(cad.ana, NUM, escaneado=True)
    assert len(cad.dify.uploads) == 1 and cad.dify.chats[0]["files"] and item.status == "concluido" and p.numero_digitos == DIG


def test_texto_com_199_e_200_caracteres_na_fronteira(cad, enviar, rodar):
    """CAD-07: 200+ caracteres → texto; menos que isso → upload."""
    def tam(n):
        base = f"{NUM} "
        return base + "a" * (n - len(base))
    enviar(cad.ana, (pdf_bytes(tam(199), numero=NUM), "a.pdf"), (pdf_bytes(tam(200), numero=NUM), "b.pdf"))
    rodar()
    assert len(cad.dify.uploads) == 1 and len(cad.dify.chats) == 2
    assert sum(1 for c in cad.dify.chats if c.get("files")) == 1


def test_fila_na_ordem_de_chegada_um_por_vez(cad, enviar, rodar):
    """CAD-07: um item por vez, na ordem de chegada (n8n)."""
    nums = [cnj(i)[0] for i in (10, 11, 12)]
    enviar(cad.ana, *[pdf_processo(n, str(i)) for i, n in enumerate(nums)])
    rodar()
    ordem = [next(n for n in nums if n in c["query"]) for c in cad.dify.chats]
    assert ordem == nums
    assert list(cad.ItemEnvio.objects.order_by("pk").values_list("status", flat=True)) == ["concluido"] * 3


def test_uma_passada_esvazia_a_fila_e_depois_nao_faz_nada(cad, enviar, rodar):
    """CAD-07: --uma-vez processa a fila atual e sai; segunda passada não repete itens concluídos."""
    enviar(cad.ana, pdf_processo(NUM))
    rodar()
    rodar()
    assert len(cad.dify.chats) == 1 and not cad.ItemEnvio.objects.filter(status__in=["na_fila", "processando"]).exists()


def test_envio_registra_inicio_e_termino(cad, enviar, rodar):
    """Modelo Envio: iniciado_em/terminado_em preenchidos depois do processamento; item com duracao_ms."""
    enviar(cad.ana, pdf_processo(NUM))
    rodar()
    e = cad.Envio.objects.get()
    assert e.iniciado_em and e.terminado_em and e.terminado_em >= e.iniciado_em
    assert cad.ItemEnvio.objects.get().duracao_ms is not None


# ---------------- leitura da resposta (CAD-08) ----------------

def test_resposta_com_cercas_e_texto_em_volta(cad, ingerir):
    """CAD-08: tira cercas ``` e pega do 1º '{' ao último '}' (mesmo com texto antes/depois)."""
    for modo in ("cercas", "prefixo"):
        cad.dify.modo = modo
        n = cnj(100 + len(modo))
        item, p = ingerir(cad.ana, n[0], variante=modo)
        assert item.status == "concluido" and p.adverso_nome == "João da Silva Fictício", modo


def test_chaves_alternativas_do_dify(cad, ingerir):
    """CAD-08/CAD-23: nomes alternativos de chave (sem acento/caixa/não alfanuméricos) são aceitos e mapeados."""
    n = cnj(7)
    alt = {"Número do Processo": n[0], "Parte Adversa": "Maria Alternativa", "CPF/CNPJ Adverso": "111.222.333-44",
           "Advogado Adverso": "Dr. Alt", "OAB Advogado Adverso": "OAB/RJ 1", "Classe": "Execução", "Valor da Causa": "R$ 10,00",
           "Vara": "2ª Vara", "Pedidos": "pedido alt", "Andamentos": [{"data": "01/02/2023", "evento": "alt"}],
           "numero_contrato": "CT-1", "Parte Empresa": "Empresa Alt", "Polo Empresa": "Réu", "Data Distribuição": "02/03/2021",
           "tribunal": "TJRJ", "comarca": "Rio"}
    cad.dify.respostas[n[0]] = alt
    item, p = ingerir(cad.ana, n[0])
    assert (p.adverso_nome, p.adverso_cpf_cnpj, p.advogado_adverso_nome, p.advogado_adverso_oab) == ("Maria Alternativa", "111.222.333-44", "Dr. Alt", "OAB/RJ 1")
    assert p.tipo_acao == "Execução" and p.valor_causa == Decimal("10.00") and p.juizo == "2ª Vara" and p.pedidos == "pedido alt"
    assert p.operacoes_vinculadas == "CT-1" and p.empresa == "Empresa Alt" and p.condicao == "Réu" and str(p.distribuido_em) == "2021-03-02"
    assert any(a["evento"] == "alt" for a in p.andamentos)


@pytest.mark.parametrize("vazio", ["Não localizado", "não encontrado", "Não informado", "NÃO CONSTA", "não consta"])
def test_nao_localizado_vira_vazio(cad, ingerir, vazio):
    """CAD-08: 'Não localizado/encontrado/informado/consta' = vazio (e vira pendência de obrigatório)."""
    n = cnj(20 + len(vazio))
    item, p = ingerir(cad.ana, n[0], variante=vazio, campos={"juizo": vazio, "comarca": vazio})
    assert p.juizo == "" and p.comarca == ""
    assert any(x.startswith("Verificar:") and "Comarca" in x and "Juízo" in x for x in p.pendencias) and p.status == "COM_PENDENCIAS"


@pytest.mark.parametrize("bruto,esperado", [("R$ 1.234,56", Decimal("1234.56")), ("R$ 10,00", Decimal("10.00")), ("R$ 1.000.000,01", Decimal("1000000.01")),
                                            ("R$ 0,99", Decimal("0.99"))])
def test_valor_da_causa_em_reais_vira_decimal(cad, ingerir, bruto, esperado):
    """CAD-08: 'R$ 1.234,56' → decimal."""
    n = cnj(30 + int(esperado) % 50)
    _, p = ingerir(cad.ana, n[0], variante=bruto, campos={"valor_causa": bruto})
    assert p.valor_causa == esperado


def test_valor_ilegivel_vira_vazio_e_pendencia(cad, ingerir):
    """CAD-08: valor inválido → vazio + pendência 'Valor da causa ilegível: <texto>'."""
    _, p = ingerir(cad.ana, NUM, campos={"valor_causa": "muitos reais"})
    assert p.valor_causa is None and "Valor da causa ilegível: muitos reais" in p.pendencias and p.status == "COM_PENDENCIAS"


def test_datas_dd_mm_aaaa_viram_data(cad, ingerir):
    """CAD-08: DD/MM/AAAA → data; data impossível não derruba o processamento."""
    _, p = ingerir(cad.ana, NUM, campos={"distribuido_em": "29/02/2024", "data_citacao": "31/04/2023"})
    assert str(p.distribuido_em) == "2024-02-29" and p.data_citacao is None


def test_menos_de_3_campos_e_erro(cad, ingerir):
    """CAD-08: menos de 3 campos preenchidos → erro (etapa IA (Dify)), nenhum processo criado."""
    cad.dify.respostas[NUM] = {"numero_cnj": NUM, "tribunal": "TJSP"}
    item, p = ingerir(cad.ana, NUM)
    assert item.status == "erro" and item.etapa_erro == "IA (Dify)" and p is None and cad.Processo.objects.count() == 0
    assert item.motivo == "A IA não encontrou dados de processo neste PDF (talvez não seja um processo)."


def test_json_invalido_e_erro_de_formato(cad, ingerir):
    """CAD-08: resposta sem JSON → erro 'A IA não devolveu os dados no formato esperado.' (etapa IA (Dify))."""
    cad.dify.modo = "invalido"
    item, p = ingerir(cad.ana, NUM)
    assert item.status == "erro" and item.etapa_erro == "IA (Dify)" and item.motivo == "A IA não devolveu os dados no formato esperado." and p is None


def test_json_quebrado_dentro_de_chaves(cad, ingerir):
    """CAD-08: '{' ... '}' que não é JSON válido → mesmo erro de formato."""
    cad.dify.respostas[NUM] = '{"numero_cnj": "x", "tribunal": TJSP,,, }'
    item, _ = ingerir(cad.ana, NUM)
    assert item.status == "erro" and item.motivo == "A IA não devolveu os dados no formato esperado."


def test_resposta_ia_guardada_e_mascarada(cad, ingerir):
    """Modelo ItemEnvio.resposta_ia / CAD-18: a resposta bruta fica no item; chave refletida pelo Dify aparece mascarada."""
    cad.dify.eco_chave = True
    cad.dify.extra = {"marcador_bruto": "MARCADOR-RESPOSTA-BRUTA"}
    item, _ = ingerir(cad.ana, NUM)
    assert "MARCADOR-RESPOSTA-BRUTA" in item.resposta_ia and SEGREDO_DIFY not in item.resposta_ia and len(item.resposta_ia) <= 200 * 1024


# ---------------- carteira (CAD-08) ----------------

def test_carteira_do_envio_prevalece(cad, ingerir):
    """CAD-08: carteira do envio é a do processo, mesmo que a empresa sugira outra."""
    _, p = ingerir(cad.ana, NUM, carteira=cad.carteiras["Volvo"])
    assert p.carteira == cad.carteiras["Volvo"]


@pytest.mark.parametrize("empresa,carteira", [("ATIVOS S.A. SECURITIZADORA DE CRÉDITOS FINANCEIROS", "Ativos"),
                                              ("cooperativa de credito (sistema AILOS)", "Ailos"), ("Volvo do Brasil", "Volvo")])
def test_carteira_deduzida_pela_empresa_sem_acento_e_caixa(cad, ingerir, empresa, carteira):
    """CAD-08: carteira vazia no envio → deduzida pela empresa (contém o nome da carteira, sem acento/maiúsculas)."""
    n = cnj(40 + len(empresa))
    _, p = ingerir(cad.ana, n[0], variante=carteira, campos={"empresa": empresa})
    assert p.carteira == cad.carteiras[carteira]


def test_carteira_nao_identificada_fica_vazia_com_pendencia(cad, ingerir):
    """CAD-08: sem carteira no envio e empresa desconhecida → vazia + pendência 'Carteira não identificada.'."""
    _, p = ingerir(cad.ana, NUM, campos={"empresa": "Empresa Desconhecida Ltda"})
    assert p.carteira is None and "Carteira não identificada." in p.pendencias and p.status == "COM_PENDENCIAS"


def test_carteira_inativa_nao_e_deduzida(cad, ingerir):
    """CAD-08/14: carteira desativada não é candidata na dedução."""
    cad.Carteira.objects.filter(pk=cad.carteiras["Ailos"].pk).update(ativa=False)
    _, p = ingerir(cad.ana, NUM, campos={"empresa": "Cooperativa Ailos"})
    assert p.carteira is None and "Carteira não identificada." in p.pendencias


# ---------------- fase (CAD-09) ----------------

@pytest.mark.parametrize("rotulo,token", [("POSTULATÓRIA", "POSTULATORIA"), ("INSTRUTÓRIA", "INSTRUTORIA"), ("DECISÓRIA", "DECISORIA"),
                                          ("RECURSAL", "RECURSAL"), ("EXECUÇÃO/CUMPRIMENTO", "EXECUCAO_CUMPRIMENTO"), ("ARQUIVADO", "ARQUIVADO")])
def test_fase_do_dify_vira_token(cad, ingerir, rotulo, token):
    """CAD-09: rótulos do Dify → tokens do enum fase_atual."""
    n = cnj(60 + len(token))
    _, p = ingerir(cad.ana, n[0], variante=token, campos={"fase_atual": rotulo})
    assert p.fase_atual == token


def test_fase_desconhecida_fica_vazia_sem_derrubar(cad, ingerir):
    """CAD-09: fase fora da lista → vazia (nulo), processamento segue."""
    item, p = ingerir(cad.ana, NUM, campos={"fase_atual": "FASE INVENTADA"})
    assert item.status == "concluido" and p.fase_atual in (None, "")


# ---------------- status e pendências (CAD-12) ----------------

def test_completo_vira_conferir(cad, ingerir):
    """CAD-12: todos os obrigatórios presentes → CONFERIR, sem pendências."""
    _, p = ingerir(cad.ana, NUM, carteira=cad.carteiras["Ativos"])
    assert p.status == "CONFERIR" and p.pendencias == []


@pytest.mark.parametrize("campo,rotulo", [("tribunal", "Tribunal"), ("comarca", "Comarca"), ("juizo", "Juízo"), ("adverso_nome", "Adverso"),
                                          ("valor_causa", "Valor da causa"), ("distribuido_em", "Distribuído em")])
def test_obrigatorio_faltando_gera_pendencia_verificar(cad, ingerir, campo, rotulo):
    """CAD-12: faltando obrigatório → pendência 'Verificar: <campos>' e COM_PENDENCIAS; item concluido + etapa 'Dados incompletos'."""
    n = cnj(70 + len(campo))
    item, p = ingerir(cad.ana, n[0], variante=campo, carteira=cad.carteiras["Ativos"], campos={campo: ""})
    assert p.status == "COM_PENDENCIAS" and any(x.startswith("Verificar:") and rotulo in x for x in p.pendencias)
    assert item.status == "concluido" and item.etapa_erro == "Dados incompletos"
    assert item.motivo.startswith(f"Processo {n[0]} gravado, mas faltou:") and rotulo in item.motivo


def test_varios_faltando_numa_unica_pendencia(cad, ingerir):
    """CAD-12: os campos faltantes ficam juntos numa pendência 'Verificar: a, b'."""
    _, p = ingerir(cad.ana, NUM, carteira=cad.carteiras["Ativos"], campos={"comarca": "", "juizo": "", "tribunal": ""})
    verificar = [x for x in p.pendencias if x.startswith("Verificar:")]
    assert len(verificar) == 1 and all(r in verificar[0] for r in ("Comarca", "Juízo", "Tribunal"))


# ---------------- falhas viram item com etapa e motivo (CAD-13) ----------------

@pytest.mark.parametrize("modo", ["401", "403"])
def test_dify_recusa_a_chave(cad, ingerir, modo):
    """CAD-13: Dify 401/403 → erro 'O Dify recusou a chave: confira a credencial em Configuração.' (IA (Dify))."""
    cad.dify.modo = modo
    item, p = ingerir(cad.ana, NUM)
    assert item.status == "erro" and item.etapa_erro == "IA (Dify)" and p is None
    assert item.motivo == "O Dify recusou a chave: confira a credencial em Configuração."


def test_dify_fora_do_ar(cad, ingerir):
    """CAD-13: Dify 500 → 'A IA não respondeu: <motivo curto>.'"""
    cad.dify.modo = "500"
    item, _ = ingerir(cad.ana, NUM)
    assert item.status == "erro" and item.etapa_erro == "IA (Dify)" and item.motivo.startswith("A IA não respondeu:") and item.motivo.endswith(".")
    assert len(item.motivo) <= 500


def test_dify_timeout_configuravel(cad, ingerir, settings):
    """CAD-07/13: prazo (JURIDICO_DIFY_TIMEOUT_S) estourado → 'A IA não respondeu: …', sem travar a fila."""
    settings.JURIDICO_DIFY_TIMEOUT_S = 1
    cad.dify.atraso = 3
    item, _ = ingerir(cad.ana, NUM)
    assert item.status == "erro" and item.etapa_erro == "IA (Dify)" and item.motivo.startswith("A IA não respondeu:")


def test_dify_inacessivel_porta_fechada(cad, ingerir):
    """CAD-13: Dify fora (conexão recusada) → erro 'A IA não respondeu', fila segue."""
    cad.config.dify_url = "http://127.0.0.1:9/dify"
    cad.config.save()
    item, _ = ingerir(cad.ana, NUM)
    assert item.status == "erro" and item.etapa_erro == "IA (Dify)"


def test_um_item_com_erro_nao_para_os_demais(cad, enviar, rodar):
    """CAD-07/13: erro num item não impede os seguintes."""
    n1, n2 = cnj(1)[0], cnj(2)[0]
    cad.dify.respostas[n1] = '{"numero_cnj": "x"}'
    enviar(cad.ana, pdf_processo(n1, "a"), pdf_processo(n2, "b"))
    rodar()
    a, b = cad.ItemEnvio.objects.order_by("pk")
    assert a.status == "erro" and b.status == "concluido" and cad.Processo.objects.count() == 1


def test_falha_no_upload_do_dify_e_envio_do_pdf(cad, ingerir):
    """CAD-23(5): falha no files/upload → etapa 'Envio do PDF', status erro, nenhum processo."""
    cad.dify.modo = "upload_500"
    item, p = ingerir(cad.ana, NUM, escaneado=True)
    assert item.status == "erro" and item.etapa_erro == "Envio do PDF" and p is None


def test_pdf_corrompido_nao_vira_processo(cad, enviar, rodar):
    """CAD-13: PDF ilegível (cabeçalho ok, corpo corrompido) → sem processo; item com erro e motivo legível (nunca 500/stack)."""
    cad.dify.modo = "upload_500"
    enviar(cad.ana, (b"%PDF-1.4\nlixo lixo lixo sem estrutura\n%%EOF", "quebrado.pdf"))
    rodar()
    item = cad.ItemEnvio.objects.get()
    assert item.status == "erro" and item.etapa_erro in ("Leitura do PDF", "Envio do PDF") and cad.Processo.objects.count() == 0
    assert item.motivo and "Traceback" not in item.motivo and len(item.motivo) <= 500


def test_motivo_nao_vaza_a_chave(cad, ingerir):
    """CAD-18: nenhum motivo/erro contém o valor da credencial."""
    cad.dify.modo = "401"
    item, _ = ingerir(cad.ana, NUM)
    assert SEGREDO_DIFY not in (item.motivo or "") and SEGREDO_DIFY not in (item.resposta_ia or "")


def test_credencial_do_dify_inexistente(cad, ingerir):
    """CAD-14/13: credencial do Dify apagada/vazia → erro claro no item (sem 500), nada chega ao Dify."""
    cad.config.dify_credencial = "Nao existe"
    cad.config.save()
    item, _ = ingerir(cad.ana, NUM)
    assert item.status == "erro" and item.motivo and cad.dify.chats == []


def test_destino_nao_liberado_ssrf_no_dify(cad, ingerir, nao_liberado):
    """CAD-07: mesma proteção SSRF do motor — dify_url para servidor local NÃO liberado é bloqueado e nada é enviado."""
    nao_liberado.rotas["/dify/chat-messages"] = lambda req: (200, {"answer": "{}"}, None)
    cad.config.dify_url = f"{nao_liberado.base}/dify"
    cad.config.save()
    item, _ = ingerir(cad.ana, NUM)
    assert item.status == "erro" and nao_liberado.requisicoes == []


@pytest.mark.parametrize("alvo", ["http://169.254.169.254/dify", "http://localhost:1/dify", "http://[::1]:1/dify"])
def test_dify_url_interna_e_bloqueada(cad, ingerir, alvo):
    """CAD-07/SEG-01..06: endereço interno/metadados na dify_url → erro, nada enviado a lugar algum."""
    cad.config.dify_url = alvo
    cad.config.save()
    item, _ = ingerir(cad.ana, NUM)
    assert item.status == "erro" and cad.dify.chats == []


def test_resposta_do_dify_maior_que_2mb(cad, ingerir):
    """CAD-07: resposta até 2 MB; acima disso → erro (não grava lixo, nem estoura memória)."""
    cad.dify.respostas[NUM] = "{" + '"k": "' + "z" * (2 * 1024 * 1024 + 10) + '"}'
    item, p = ingerir(cad.ana, NUM)
    assert item.status == "erro" and p is None and len(item.resposta_ia or "") <= 200 * 1024
