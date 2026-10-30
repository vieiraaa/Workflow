"""D-049: log das chamadas à API do n8n (aceitas e recusadas) e filtro por envio nas Aprovações."""

import json

import pytest
from django.urls import reverse

from apps.juridico import recebimentos
from apps.juridico.models import ChamadaApi, ConfigCadastro, Recebimento

pytestmark = [pytest.mark.modulo("m8"), pytest.mark.django_db]

API = reverse("api_juridico_recebimentos")
LOG = reverse("juridico:api_log")
PAINEL = reverse("juridico:painel")
APROVACOES = f"{PAINEL}?aba=aprovacoes"  # aba do painel (D-063)
ITEM = {"data": "2026-10-14", "hora": "16:10:16", "tipo": "CUMPRIMENTO DE SENTENÇA",
        "processo": "5007919-63.2001.8.24.0005", "uf": "SC"}  # fmt: skip
INVALIDO = {"tipo": "PJE", "processo": "5197975-39.2026.8.19.0001"}


def _post(client, corpo, chave=None, **extra):
    if chave:
        extra["HTTP_AUTHORIZATION"] = f"Bearer {chave}"
    dados = corpo if isinstance(corpo, (bytes, str)) else json.dumps(corpo)
    return client.post(API, dados, content_type="application/json", **extra)


@pytest.fixture
def chave():
    return recebimentos.gerar_chave()


def test_chamada_aceita_vira_linha_com_contagens(client, chave):
    _post(client, [ITEM, INVALIDO, "x"], chave, HTTP_USER_AGENT="n8n/1.80")
    _post(client, [ITEM], chave)
    primeira, segunda = ChamadaApi.objects.order_by("pk")
    assert primeira.status_http == 200 and primeira.aceita
    assert (primeira.recebidos, primeira.novos, primeira.repetidos, primeira.invalidos) == (
        3, 2, 0, 1,
    )  # fmt: skip
    assert primeira.lote and primeira.ip == "127.0.0.1" and primeira.agente == "n8n/1.80"
    assert primeira.tamanho > 0 and "2 novo(s)" in primeira.mensagem
    assert (segunda.novos, segunda.repetidos) == (0, 1)


@pytest.mark.parametrize(
    "preparar,corpo,cabecalho,status",
    [
        (False, [ITEM], "Bearer qualquer", 503),
        (True, [ITEM], "Bearer errada", 401),
        (True, [ITEM], None, 401),
        (True, b"{quebrado", "CHAVE", 400),
        (True, [ITEM] * 501, "CHAVE", 413),
    ],
)
def test_recusas_tambem_ficam_no_log(client, preparar, corpo, cabecalho, status):
    chave = recebimentos.gerar_chave() if preparar else ""
    extra = {}
    if cabecalho:
        extra["HTTP_AUTHORIZATION"] = cabecalho.replace("CHAVE", f"Bearer {chave}")
    assert _post(client, corpo, **extra).status_code == status
    linha = ChamadaApi.objects.get()
    assert linha.status_http == status and not linha.aceita and linha.mensagem
    assert linha.lote is None and linha.novos == 0
    assert Recebimento.objects.count() == 0


def test_log_nunca_guarda_a_chave_nem_o_corpo(client, chave):
    _post(client, [dict(ITEM, cliente="NOME SIGILOSO")], chave)
    _post(client, [ITEM], "cwj_chave_errada_secreta")
    for linha in ChamadaApi.objects.values():
        texto = json.dumps(linha, default=str)
        assert chave not in texto and "cwj_chave_errada_secreta" not in texto
        assert "NOME SIGILOSO" not in texto


def test_get_na_api_nao_entra_no_log(client, chave):
    client.get(API, HTTP_AUTHORIZATION=f"Bearer {chave}")
    assert ChamadaApi.objects.count() == 0


def test_falha_ao_gravar_o_log_nao_derruba_a_api(client, chave, monkeypatch):
    def quebra(*args, **kwargs):
        raise RuntimeError("banco do log fora")

    monkeypatch.setattr(ChamadaApi.objects, "create", quebra)
    resposta = _post(client, [ITEM], chave)
    assert resposta.status_code == 200 and Recebimento.objects.count() == 1


# ------------------------------------------------------------------ tela do log
def test_tela_so_para_quem_aprova(cliente_anonimo, cliente_base, cliente_adm):
    assert cliente_anonimo.get(LOG).status_code == 302
    assert cliente_base.get(LOG).status_code == 403
    resposta = cliente_adm.get(LOG)
    assert resposta.status_code == 200
    assert "juridico/api_log.html" in [t.name for t in resposta.templates]
    assert "Nenhuma chamada ainda" in resposta.content.decode()


def test_lista_situacao_dos_itens_e_link_para_os_itens(client, chave, cliente_adm, usuario_adm):
    _post(client, [ITEM, INVALIDO], chave)
    _post(client, [ITEM], "errada")
    recebimentos.descartar(usuario_adm, [Recebimento.objects.get(numero_valido=False).pk])
    resposta = cliente_adm.get(LOG)
    recusada, aceita = list(resposta.context["chamadas"])
    assert recusada["status_rotulo"] == "Chave recusada" and recusada["url_itens"] == ""
    assert aceita["status_rotulo"] == "Aceita"
    assert (aceita["pendentes"], aceita["aprovados"], aceita["descartados"]) == (1, 0, 1)
    lote = ChamadaApi.objects.get(status_http=200).lote
    assert aceita["url_itens"] == f"{APROVACOES}&status=todos&lote={lote}"
    resumo = resposta.context["resumo_24h"]
    assert (resumo["total"], resumo["aceitas"], resumo["recusadas"], resumo["novos"]) == (
        2, 1, 1, 2,
    )  # fmt: skip


def test_filtro_por_resultado(client, chave, cliente_adm):
    _post(client, [ITEM], chave)
    _post(client, [ITEM], "errada")
    _post(client, b"{x", chave)
    contar = lambda r: len(cliente_adm.get(LOG, {"resultado": r}).context["chamadas"])  # noqa: E731
    assert (contar(""), contar("aceitas"), contar("recusadas"), contar("lixo")) == (3, 1, 2, 3)


def test_paginacao_e_queries_constantes(client, chave, cliente_adm, django_assert_max_num_queries):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    _post(client, [ITEM], chave)
    cliente_adm.get(LOG)
    with CaptureQueriesContext(connection) as poucos:
        cliente_adm.get(LOG)
    limite = len(poucos.captured_queries)
    for i in range(29):
        _post(client, [dict(ITEM, hora=f"10:{i:02d}:00")], chave)
    with django_assert_max_num_queries(limite):
        resposta = cliente_adm.get(LOG)
    assert len(resposta.context["chamadas"]) == 25 and resposta.context["page_obj"].has_next()


def test_base_com_acesso_ao_cadastro_ve_o_log(cliente_base, usuario_base):
    ConfigCadastro.obter().setores_com_acesso.add(usuario_base.setor)
    resposta = cliente_base.get(LOG)
    assert resposta.status_code == 200 and resposta.context["url_config"] == ""


def test_menu_marca_o_cadastro_no_log(cliente_adm):
    ativos = {i["chave"] for i in cliente_adm.get(LOG).context["menu"] if i["ativo"]}
    assert ativos == {"juridico"}


# ------------------------------------------------------------------ aprovações por envio
def test_aprovacoes_filtra_por_lote_e_status_todos(client, chave, cliente_adm, usuario_adm):
    _post(client, [ITEM, INVALIDO], chave)
    _post(client, [dict(ITEM, hora="11:00:00")], chave)
    lote = str(ChamadaApi.objects.order_by("pk").first().lote)
    recebimentos.descartar(usuario_adm, [Recebimento.objects.get(numero_valido=False).pk])
    resposta = cliente_adm.get(PAINEL, {"aba": "aprovacoes", "status": "todos", "lote": lote})
    itens = list(resposta.context["itens"])
    assert len(itens) == 2 and resposta.context["lote_atual"] == lote
    assert resposta.context["lote_rotulo"].startswith("envio de ")
    assert resposta.context["pendentes"] is False  # "todos" é só leitura: sem seleção
    corpo = resposta.content.decode()
    assert "Mostrando só os itens do envio de" in corpo and "Pendente" in corpo
    assert (
        len(cliente_adm.get(PAINEL, {"aba": "aprovacoes", "lote": lote}).context["itens"]) == 1
    )  # só pendentes


def test_lote_invalido_e_ignorado(client, chave, cliente_adm):
    _post(client, [ITEM], chave)
    resposta = cliente_adm.get(PAINEL, {"aba": "aprovacoes", "lote": "nao-e-uuid'--"})
    assert resposta.status_code == 200 and resposta.context["lote_atual"] == ""
    assert len(resposta.context["itens"]) == 1


def test_voltar_depois_de_aprovar_mantem_o_lote(client, chave, cliente_adm):
    _post(client, [ITEM], chave)
    lote = str(ChamadaApi.objects.get().lote)
    resposta = cliente_adm.post(
        reverse("juridico:aprovar"),
        {"ids": [Recebimento.objects.get().pk], "consulta": f"lote={lote}&outro=x"},
    )
    assert resposta.url == f"{APROVACOES}&lote={lote}"
