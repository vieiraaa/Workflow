"""D-048: API de entrada do n8n → itens pendentes → aprovação do jurídico → fila do cadastro."""

import copy
import json

import pytest
from django.core.management import call_command
from django.urls import reverse

from apps.juridico import recebimentos
from apps.juridico.models import ConfigCadastro, Envio, ItemEnvio, Processo, Recebimento
from tests.conftest import criar_usuario

pytestmark = [pytest.mark.modulo("m8"), pytest.mark.django_db]

API = reverse("api_juridico_recebimentos")
PAINEL = reverse("juridico:painel")
LISTA = f"{PAINEL}?aba=aprovacoes"  # Aprovações é uma aba do painel (D-063)

# Recorte do retorno do n8n (dados fictícios): válido, válido com prazo, mesmo processo de novo,
# número inválido e item sem processo.
VALIDO = {
    "linha": 1, "tabela": 1, "data": "2026-10-14", "hora": "16:10:16",
    "tipo": "CUMPRIMENTO DE SENTENÇA", "tipo_padronizado": "CUMPRIMENTO DE SENTENÇA",
    "remetente": "Tribunal de Justica do Estado de Santa Catarina", "remetente_sigla": "TJSC",
    "origem": "tribunal", "numero_controle": None, "cliente": None, "uf": "SC",
    "processo": "5007919-63.2001.8.24.0005", "processo_tribunal": "TJSC",
    "motivo": "Cumprimento de sentença", "alertas": [],
}  # fmt: skip
COM_PRAZO = {
    "linha": 1, "tabela": 1, "data": "2026-10-15", "hora": "09:12:44",
    "tipo": "PROCEDIMENTO COMUM CÍVEL", "remetente_sigla": "TJRJ", "origem": "tribunal",
    "uf": "RJ", "processo": "5205894-69.2026.8.19.0001", "outras_colunas": {"PRAZO": "15 dias"},
    "alertas": ["uf_inferida_do_processo"],
}  # fmt: skip
CARTA = {
    "linha": 4, "tabela": 1, "data": "2026-10-13", "hora": None,
    "tipo": "CARTA DE AR DE CITAÇÃO", "remetente_sigla": "PJD", "origem": "correios",
    "numero_controle": "YH900000025BR", "cliente": "VALTER SIMULADO PRESS", "uf": "RS",
    "processo": "5087109-82.2026.8.21.0005", "alertas": [],
}  # fmt: skip
INVALIDO = {
    "linha": 2, "data": "2026-10-15", "hora": "09:40:02", "tipo": "PROCEDIMENTO DO JUIZADO",
    "processo": "5197975-39.2026.8.19.0001", "processo_valido": True, "alertas": [],
}  # fmt: skip
SEM_PROCESSO = {
    "linha": 5, "data": None, "tipo": "PJE", "cliente": "CLIENTE SEM PROCESSO", "uf": "RJ",
    "processo": None, "motivo": "verificar", "alertas": ["data_nao_reconhecida", "sem_processo"],
}  # fmt: skip
ITENS = [VALIDO, COM_PRAZO, CARTA, INVALIDO, SEM_PROCESSO]


@pytest.fixture
def chave():
    return recebimentos.gerar_chave()


def _post(client, corpo, chave=None, **extra):
    if chave:
        extra["HTTP_AUTHORIZATION"] = f"Bearer {chave}"
    dados = corpo if isinstance(corpo, (bytes, str)) else json.dumps(corpo)
    return client.post(API, dados, content_type="application/json", **extra)


@pytest.fixture
def com_acesso(usuario_base):
    """O setor do Base passa a ter acesso ao cadastro (CAD-02): ele pode aprovar."""
    ConfigCadastro.obter().setores_com_acesso.add(usuario_base.setor)
    return usuario_base


# ------------------------------------------------------------------ API
def test_sem_chave_configurada_a_api_recusa_com_503(client):
    resposta = _post(client, ITENS, chave="qualquer")
    assert resposta.status_code == 503 and resposta.json()["ok"] is False
    assert Recebimento.objects.count() == 0


@pytest.mark.parametrize("cabecalho", [None, "Bearer errada", "Basic abc", "Bearer "])
def test_chave_ausente_ou_errada_da_401(client, chave, cabecalho):
    extra = {"HTTP_AUTHORIZATION": cabecalho} if cabecalho else {}
    resposta = _post(client, ITENS, **extra)
    assert resposta.status_code == 401
    assert Recebimento.objects.count() == 0


def test_recebe_a_lista_e_grava_pendentes(client, chave):
    resposta = _post(client, ITENS, chave)
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["ok"] is True
    assert (corpo["recebidos"], corpo["novos"], corpo["repetidos"]) == (5, 5, 0)
    assert corpo["invalidos"] == []
    assert Recebimento.objects.filter(status=Recebimento.PENDENTE).count() == 5
    r = Recebimento.objects.get(numero_digitos="52058946920268190001")
    assert r.numero == "5205894-69.2026.8.19.0001" and r.numero_valido
    assert (r.prazo, r.uf, r.remetente_sigla, str(r.data), str(r.hora)) == (
        "15 dias", "RJ", "TJRJ", "2026-10-15", "09:12:44",
    )  # fmt: skip
    assert r.dados == COM_PRAZO


def test_numero_e_validado_pelo_digito_verificador_e_nao_pelo_n8n(client, chave):
    _post(client, ITENS, chave)
    invalido = Recebimento.objects.get(numero_digitos="51979753920268190001")
    assert invalido.numero_valido is False and "processo_invalido" in invalido.alertas
    sem = Recebimento.objects.get(cliente="CLIENTE SEM PROCESSO")
    assert sem.numero_valido is False and sem.numero == "" and sem.data is None


def test_x_api_key_tambem_vale(client, chave):
    assert _post(client, [VALIDO], HTTP_X_API_KEY=chave).status_code == 200


def test_aceita_objeto_com_itens_e_url_sem_barra(client, chave):
    resposta = client.post(
        API.rstrip("/"),
        json.dumps({"itens": [VALIDO]}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {chave}",
    )
    assert resposta.status_code == 200 and resposta.json()["novos"] == 1


# Envelope do n8n (D-059): um objeto por e-mail, com os itens em "registros" (dados fictícios).
ENVELOPE = {
    "email": {"id": "AAMk-ficticio", "assunto": "Casos Novos ESPAIDER",
              "de": "exemplo@exemplo.test",
              "recebido_em": "2026-10-27T11:15:17Z"},
    "texto_email": "Boa tarde! Segue planilha.",
    "resumo": {"total_registros": 3},
    "alertas_email": [],
    "registros": [VALIDO, CARTA, INVALIDO],
}  # fmt: skip


@pytest.mark.parametrize("corpo", [[ENVELOPE], ENVELOPE], ids=["lista_de_envelopes", "envelope"])
def test_aceita_o_envelope_do_n8n_com_registros(client, chave, corpo):
    resposta = _post(client, corpo, chave)
    assert resposta.status_code == 200, resposta.content
    assert resposta.json()["recebidos"] == 3 and resposta.json()["novos"] == 3
    numeros = set(Recebimento.objects.values_list("numero", flat=True))
    assert numeros == {VALIDO["processo"], CARTA["processo"], INVALIDO["processo"]}
    r = Recebimento.objects.get(numero=CARTA["processo"])
    assert (
        r.cliente == "VALTER SIMULADO PRESS"
        and r.dados["email"]["assunto"] == "Casos Novos ESPAIDER"
    )
    assert _post(client, corpo, chave).json()["novos"] == 0  # reenvio do mesmo e-mail não duplica


def test_dois_envelopes_num_envio_so(client, chave):
    outro = {
        **ENVELOPE,
        "email": {**ENVELOPE["email"], "id": "AAMk-outro"},
        "registros": [COM_PRAZO],
    }
    assert _post(client, [ENVELOPE, outro], chave).json()["recebidos"] == 4


def test_reenvio_do_n8n_nao_duplica(client, chave):
    _post(client, ITENS, chave)
    movido = [dict(i, linha=99) for i in ITENS]  # mesma coisa em outra posição do e-mail
    corpo = _post(client, movido + [VALIDO], chave).json()
    assert (corpo["recebidos"], corpo["novos"], corpo["repetidos"]) == (6, 0, 6)
    assert Recebimento.objects.count() == 5


def test_mesmo_processo_com_conteudo_diferente_entra_duas_vezes(client, chave):
    outra = dict(VALIDO, tipo="PROCEDIMENTO COMUM CÍVEL", hora="14:19:09")
    assert _post(client, [VALIDO, outra], chave).json()["novos"] == 2


@pytest.mark.parametrize(
    "corpo,status",
    [
        (b"{nao e json", 400),
        ({"outra": 1}, 400),
        ("123", 400),
        ([{"processo": "1"}] * 501, 413),
    ],
)
def test_formato_errado(client, chave, corpo, status):
    assert _post(client, corpo, chave).status_code == status
    assert Recebimento.objects.count() == 0


def test_item_que_nao_e_objeto_volta_como_invalido(client, chave):
    corpo = _post(client, [VALIDO, "texto", 7], chave).json()
    assert corpo["novos"] == 1
    assert [i["indice"] for i in corpo["invalidos"]] == [1, 2]


def test_corpo_grande_demais_da_413(client, chave):
    grande = [{"processo": "x" * 1000, "n": i} for i in range(2200)]
    assert _post(client, grande, chave).status_code == 413


def test_so_post(client, chave):
    resposta = client.get(API, HTTP_AUTHORIZATION=f"Bearer {chave}")
    assert resposta.status_code == 405 and resposta.json()["ok"] is False


def test_textos_longos_sao_cortados_e_alertas_estranhos_ignorados(client, chave):
    item = dict(VALIDO, tipo_padronizado="T" * 5000, cliente={"x": 1}, alertas=["ok", 3, None])
    assert _post(client, [item], chave).status_code == 200
    r = Recebimento.objects.get()
    assert len(r.tipo) == 300 and r.cliente == "" and r.alertas == ["ok"]


def test_nova_chave_derruba_a_anterior(client, chave):
    recebimentos.gerar_chave()
    assert _post(client, [VALIDO], chave).status_code == 401


def test_chave_guardada_so_como_hash():
    valor = recebimentos.gerar_chave()
    config = ConfigCadastro.obter()
    assert valor.startswith("cwj_") and valor not in (
        config.api_chave_hash,
        config.api_chave_inicio,
    )
    assert config.api_chave_inicio == valor[:10]


# ------------------------------------------------------------------ tela de aprovações
def test_tela_exige_acesso_ao_cadastro(cliente_anonimo, cliente_base, cliente_adm):
    assert cliente_anonimo.get(LISTA).status_code == 302
    assert cliente_base.get(LISTA).status_code == 403  # setor sem acesso ao cadastro
    resposta = cliente_adm.get(LISTA)
    assert resposta.status_code == 200
    usados = [t.name for t in resposta.templates]
    assert "juridico/painel.html" in usados and "componentes/aba_aprovacoes.html" in usados


def test_endereco_antigo_redireciona_para_a_aba_com_a_querystring(cliente_adm, cliente_base):
    antigo = reverse("juridico:aprovacoes")
    resposta = cliente_adm.get(antigo, {"status": "todos", "q": "x", "outro": "y"})
    assert resposta.status_code == 302 and resposta.url == f"{LISTA}&status=todos&q=x"
    assert cliente_adm.get(antigo).url == LISTA
    assert cliente_base.get(antigo).status_code == 403


def test_abas_do_painel_com_aprovacoes_primeiro(client, chave, com_acesso):
    _post(client, ITENS, chave)
    cliente = client.__class__()
    cliente.force_login(com_acesso)
    abas = cliente.get(PAINEL).context["abas"]
    assert [a["chave"] for a in abas] == ["aprovacoes", "processamento", "cadastrados"]
    assert abas[0]["total"] == 5 and abas[0]["url"] == "?aba=aprovacoes"
    resposta = cliente.get(LISTA)
    assert resposta.status_code == 200 and resposta.context["aba"] == "aprovacoes"
    assert [a["ativa"] for a in resposta.context["abas"]] == [True, False, False]


def test_lista_pendentes_com_alertas_e_ja_cadastrado(client, chave, cliente_adm):
    _post(client, ITENS, chave)
    Processo.objects.create(
        numero="5007919-63.2001.8.24.0005", numero_digitos="50079196320018240005",
        numero_valido=True,
    )  # fmt: skip
    resposta = cliente_adm.get(LISTA)
    linhas = {i["numero"] or i["cliente"]: i for i in resposta.context["itens"]}
    assert len(linhas) == 5 and resposta.context["total_pendentes"] == 5
    assert linhas["5007919-63.2001.8.24.0005"]["ja_cadastrado_url"]
    assert linhas["5197975-39.2026.8.19.0001"]["aprovavel"] is False
    rotulos = [a["rotulo"] for a in linhas["5205894-69.2026.8.19.0001"]["alertas"]]
    assert rotulos == ["UF deduzida do número"]
    assert [a["grave"] for a in linhas["CLIENTE SEM PROCESSO"]["alertas"]] == [False, True]


def test_busca_por_numero_e_cliente(client, chave, cliente_adm):
    _post(client, ITENS, chave)
    assert (
        len(cliente_adm.get(PAINEL, {"aba": "aprovacoes", "q": "52058946"}).context["itens"]) == 1
    )
    assert len(cliente_adm.get(PAINEL, {"aba": "aprovacoes", "q": "valter"}).context["itens"]) == 1
    assert (
        len(cliente_adm.get(PAINEL, {"aba": "aprovacoes", "q": "nada-disso"}).context["itens"]) == 0
    )


def test_paginacao_de_25(client, chave, cliente_adm):
    itens = [dict(VALIDO, hora=f"10:{i:02d}:00") for i in range(30)]
    _post(client, itens, chave)
    resposta = cliente_adm.get(LISTA)
    assert len(resposta.context["itens"]) == 25 and resposta.context["page_obj"].has_next()


def test_queries_constantes(client, chave, cliente_adm, django_assert_max_num_queries):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    _post(client, ITENS[:1], chave)
    cliente_adm.get(LISTA)
    with CaptureQueriesContext(connection) as poucos:
        cliente_adm.get(LISTA)
    limite = len(poucos.captured_queries)  # antes da próxima requisição, que zera o log
    _post(client, [dict(VALIDO, hora=f"11:{i:02d}:00") for i in range(20)], chave)
    with django_assert_max_num_queries(limite):
        cliente_adm.get(LISTA)


# ------------------------------------------------------------------ aprovar / descartar
def _ids(**filtro):
    return list(Recebimento.objects.filter(**filtro).values_list("pk", flat=True))


def test_aprovar_manda_para_a_fila_do_cadastro_por_cnj(client, chave, com_acesso):
    _post(client, ITENS + [dict(VALIDO, tipo="OUTRO AVISO")], chave)
    cliente = client.__class__()
    cliente.force_login(com_acesso)
    resposta = cliente.post(reverse("juridico:aprovar"), {"ids": _ids(), "consulta": "q=x"})
    assert resposta.status_code == 302 and resposta.url == f"{LISTA}&q=x"
    envio = Envio.objects.get()
    assert envio.origem == Envio.CNJ and envio.enviado_por == com_acesso
    # 4 aprovados com 3 números distintos (o VALIDO veio duas vezes) → 3 itens na fila
    numeros = sorted(envio.itens.values_list("numero_informado", flat=True))
    assert numeros == ["50079196320018240005", "50871098220268210005", "52058946920268190001"]
    assert Recebimento.objects.filter(status=Recebimento.APROVADO).count() == 4
    duas = Recebimento.objects.filter(numero_digitos="50079196320018240005")
    assert {r.item_envio_id for r in duas} == {
        envio.itens.get(numero_informado="50079196320018240005").pk
    }
    # inválido e sem processo continuam pendentes
    assert Recebimento.objects.filter(status=Recebimento.PENDENTE).count() == 2
    textos = [str(m) for m in resposta.wsgi_request._messages]
    assert any("3 processos na fila" in t and "2 itens sem número válido" in t for t in textos)


def test_aprovado_vira_processo_no_worker(client, chave, usuario_adm, cliente_adm):
    _post(client, [VALIDO], chave)
    cliente_adm.post(reverse("juridico:aprovar"), {"ids": _ids()})
    call_command("processar_cadastros", "--uma-vez")
    r = Recebimento.objects.select_related("item_envio__processo").get()
    assert r.item_envio.status == ItemEnvio.CONCLUIDO
    assert r.item_envio.processo.numero_digitos == "50079196320018240005"
    linha = cliente_adm.get(PAINEL, {"aba": "aprovacoes", "status": "aprovado"}).context["itens"][0]
    assert linha["processo_url"] and linha["decisao"].startswith("Aprovado por Ana Admin")


def test_aprovar_so_invalidos_nao_cria_envio(client, chave, cliente_adm):
    _post(client, [INVALIDO, SEM_PROCESSO], chave)
    resposta = cliente_adm.post(reverse("juridico:aprovar"), {"ids": _ids()})
    assert resposta.status_code == 302 and Envio.objects.count() == 0
    assert Recebimento.objects.filter(status=Recebimento.PENDENTE).count() == 2


def test_aprovar_sem_selecao(cliente_adm):
    resposta = cliente_adm.post(reverse("juridico:aprovar"), {"ids": ["x", ""]})
    assert resposta.status_code == 302 and Envio.objects.count() == 0


def test_aprovar_duas_vezes_nao_reenvia(client, chave, cliente_adm):
    _post(client, [VALIDO], chave)
    ids = _ids()
    cliente_adm.post(reverse("juridico:aprovar"), {"ids": ids})
    cliente_adm.post(reverse("juridico:aprovar"), {"ids": ids})
    assert Envio.objects.count() == 1 and ItemEnvio.objects.count() == 1


def test_descartar_com_motivo(client, chave, cliente_adm):
    _post(client, [INVALIDO], chave)
    cliente_adm.post(reverse("juridico:descartar"), {"ids": _ids(), "motivo": "  já tratado  "})
    r = Recebimento.objects.get()
    assert r.status == Recebimento.DESCARTADO and r.motivo_descarte == "já tratado"
    linha = cliente_adm.get(PAINEL, {"aba": "aprovacoes", "status": "descartado"}).context["itens"][
        0
    ]
    assert linha["decisao"].startswith("Descartado por Ana Admin")


@pytest.mark.parametrize("rota", ["juridico:aprovar", "juridico:descartar"])
def test_sem_acesso_nao_decide(client, chave, cliente_base, rota):
    _post(client, [VALIDO], chave)
    assert cliente_base.post(reverse(rota), {"ids": _ids()}).status_code == 403
    assert Recebimento.objects.get().status == Recebimento.PENDENTE


def test_decisoes_so_por_post(cliente_adm):
    assert cliente_adm.get(reverse("juridico:aprovar")).status_code == 405


# ------------------------------------------------------------------ notificação
def test_contador_no_menu_e_aviso_na_home_para_quem_aprova(client, chave, com_acesso):
    cliente = client.__class__()
    cliente.force_login(com_acesso)
    resposta = cliente.get(reverse("inicio"))
    assert resposta.context["aviso_aprovacoes"] is None
    _post(client, ITENS, chave)
    resposta = cliente.get(reverse("inicio"))
    # D-063: sem item próprio; o número fica em "Cadastro de processos"
    assert "aprovacoes" not in {i["chave"] for i in resposta.context["menu"]}
    item = next(i for i in resposta.context["menu"] if i["chave"] == "juridico")
    assert item["contador"] == 5 and item["grupo"] == "Jurídico"
    assert resposta.context["aviso_aprovacoes"] == {"total": 5, "url": LISTA}
    corpo = resposta.content.decode()
    assert "aguardando aprovação" in corpo and "sidebar__contador" in corpo


def test_quem_nao_tem_acesso_nao_ve_aviso_nem_item(client, chave, cliente_base):
    _post(client, ITENS, chave)
    resposta = cliente_base.get(reverse("inicio"))
    assert resposta.context["aviso_aprovacoes"] is None
    assert "aprovacoes" not in {i["chave"] for i in resposta.context["menu"]}


def test_aba_aprovacoes_marca_o_item_do_cadastro_no_menu(cliente_adm):
    ativos = {i["chave"] for i in cliente_adm.get(LISTA).context["menu"] if i["ativo"]}
    assert ativos == {"juridico"}
    ativos = {
        i["chave"]
        for i in cliente_adm.get(reverse("juridico:painel")).context["menu"]
        if i["ativo"]
    }
    assert ativos == {"juridico"}


# ------------------------------------------------------------------ chave na configuração
def test_adm_gera_chave_e_ve_uma_vez(cliente_adm):
    resposta = cliente_adm.post(reverse("juridico:gerar_chave_api"))
    assert resposta.status_code == 302
    pagina = cliente_adm.get(reverse("juridico:config"))
    nova = pagina.context["chave_api_nova"]
    assert nova.startswith("cwj_") and nova in pagina.content.decode()
    assert pagina.context["url_api"].endswith("/api/juridico/recebimentos/")
    de_novo = cliente_adm.get(reverse("juridico:config"))
    assert de_novo.context["chave_api_nova"] == "" and nova not in de_novo.content.decode()
    assert de_novo.context["chave_api"]["inicio"] == nova[:10]


def test_so_adm_gera_chave(com_acesso, client):
    cliente = client.__class__()
    cliente.force_login(com_acesso)
    assert cliente.post(reverse("juridico:gerar_chave_api")).status_code == 403
    assert ConfigCadastro.obter().api_chave_hash == ""


def test_simulacao_nao_aprova(client, chave, cliente_adm, com_acesso):
    """D-047 + D-048: o Adm simulando quem aprova vê a fila, mas não decide."""
    _post(client, [VALIDO], chave)
    cliente_adm.post(reverse("contas:simular_iniciar", kwargs={"pk": com_acesso.pk}))
    assert cliente_adm.get(LISTA).status_code == 200
    cliente_adm.post(reverse("juridico:aprovar"), {"ids": _ids()})
    assert Recebimento.objects.get().status == Recebimento.PENDENTE


def test_outro_usuario_qualquer_nao_usa_a_api_pela_sessao(client, chave, usuario_adm):
    """Sessão logada não substitui a chave."""
    cliente = client.__class__()
    cliente.force_login(usuario_adm)
    assert _post(cliente, [VALIDO]).status_code == 401
    assert criar_usuario("x@exemplo.test", "X").pk  # o banco segue íntegro
    assert copy.deepcopy(VALIDO) == VALIDO


# ---------------------------------------------------------------- importação manual (D-060)
IMPORTAR = reverse("juridico:importar_carga")


def _arquivo(conteudo, nome="carga.json"):
    from django.core.files.uploadedfile import SimpleUploadedFile

    dados = conteudo if isinstance(conteudo, bytes) else json.dumps(conteudo).encode()
    return SimpleUploadedFile(nome, dados, content_type="application/json")


def test_importar_a_carga_do_email_cria_pendentes_e_registra_no_log(cliente_adm):
    from apps.juridico.models import ChamadaApi

    resposta = cliente_adm.post(IMPORTAR, {"arquivo": _arquivo([ENVELOPE])})
    lote = Recebimento.objects.get(numero=VALIDO["processo"]).lote
    assert resposta.status_code == 302 and resposta.url == f"{LISTA}&status=todos&lote={lote}"
    assert Recebimento.objects.filter(status=Recebimento.PENDENTE).count() == 3
    chamada = ChamadaApi.objects.get()
    assert chamada.status_http == 200 and chamada.novos == 3 and chamada.lote == lote
    assert chamada.agente.startswith("Importação manual por ")


def test_importar_a_mesma_carga_ou_o_que_ja_veio_pela_api_nao_duplica(client, chave, cliente_adm):
    _post(client, ENVELOPE["registros"], chave)  # chegou pela API (lista simples, sem o e-mail)
    resposta = cliente_adm.post(IMPORTAR, {"arquivo": _arquivo([ENVELOPE])}, follow=True)
    assert Recebimento.objects.count() == 3
    assert "0 novo(s), 3 repetido(s)" in resposta.content.decode()


@pytest.mark.parametrize(
    ("conteudo", "mensagem"),
    [
        (b"isto nao e json", "Não é a carga do n8n"),
        ({"outra": "coisa"}, "Não é a carga do n8n"),
        (b"", "Escolha o arquivo .json"),
    ],
)
def test_importar_arquivo_errado_avisa_e_nao_cria_nada(cliente_adm, conteudo, mensagem):
    resposta = cliente_adm.post(IMPORTAR, {"arquivo": _arquivo(conteudo)}, follow=True)
    assert mensagem in resposta.content.decode() and not Recebimento.objects.exists()


def test_importar_arquivo_grande_demais(cliente_adm):
    grande = _arquivo(b" " * (recebimentos.MAX_BYTES + 1))
    resposta = cliente_adm.post(IMPORTAR, {"arquivo": grande}, follow=True)
    assert "passa de 2 MB" in resposta.content.decode() and not Recebimento.objects.exists()


def test_importar_exige_acesso_ao_cadastro_e_post(cliente_anonimo, cliente_base, cliente_adm):
    assert cliente_anonimo.post(IMPORTAR, {"arquivo": _arquivo([ENVELOPE])}).status_code == 302
    assert cliente_base.post(IMPORTAR, {"arquivo": _arquivo([ENVELOPE])}).status_code == 403
    assert cliente_adm.get(IMPORTAR).status_code == 405
    assert not Recebimento.objects.exists()


def test_tela_tem_o_botao_e_o_modal_de_importar(cliente_adm):
    html = cliente_adm.get(LISTA).content.decode()
    assert 'data-modal-abrir="modal-importar-carga"' in html and f'action="{IMPORTAR}"' in html
    assert 'enctype="multipart/form-data"' in html and "Importar carga do n8n" in html
