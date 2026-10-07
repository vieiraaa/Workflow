import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import RequestFactory
from django.utils import timezone

from apps.execucoes import apresentacao, demo
from apps.execucoes.models import Execucao
from apps.execucoes.views import ExecucaoDetalheView, ExecucaoListaView
from apps.fluxos import demo as demo_fluxos
from tests.conftest import criar_usuario

pytestmark = [pytest.mark.modulo("m3"), pytest.mark.django_db]


def _lista(usuario, **params):
    request = RequestFactory().get("/execucoes/", params)
    request.user = usuario
    return ExecucaoListaView.as_view()(request).context_data


def _detalhe(usuario, pk):
    request = RequestFactory().get("/")
    request.user = usuario
    return ExecucaoDetalheView.as_view()(request, pk=pk).context_data


@pytest.mark.parametrize(
    ("ms", "texto"),
    [
        (None, ""),
        (0, "0,0 s"),
        (300, "0,3 s"),
        (1234, "1,2 s"),
        (59_999, "60,0 s"),
        (65_000, "1 min 05 s"),
    ],
)
def test_duracao_texto(ms, texto):
    assert apresentacao.duracao_texto(ms) == texto


def test_json_formatado_e_corpo_texto():
    assert apresentacao.json_formatado({}) == "" and apresentacao.json_formatado(None) == ""
    assert apresentacao.json_formatado({"a": "ç"}) == '{\n  "a": "ç"\n}'
    assert apresentacao.corpo_texto("<b>x</b>") == "<b>x</b>"
    assert apresentacao.corpo_texto({"a": 1}) == '{\n  "a": 1\n}'
    assert apresentacao.corpo_texto(None) == ""


def test_lista_anonimo_e_escopo_da_base(usuario_base, usuario_coordenador):
    request = RequestFactory().get("/")
    request.user = AnonymousUser()
    assert ExecucaoListaView.as_view()(request).status_code == 302
    demo.criar_execucao(usuario_base, nome="Minha")
    demo.criar_execucao(usuario_coordenador, nome="Alheia")
    assert [e["fluxo_nome"] for e in _lista(usuario_base)["execucoes"]] == ["Minha"]
    assert {e["fluxo_nome"] for e in _lista(usuario_coordenador)["execucoes"]} == {
        "Minha",
        "Alheia",
    }


def test_sem_papel_recebe_403(usuario_sem_papel):
    with pytest.raises(PermissionDenied):
        _lista(usuario_sem_papel)


def test_linhas_filtros_e_ordenacao(usuario_adm):
    demo.criar_execucao(usuario_adm, "sucesso", nome="Aaa", minutos_atras=30)
    demo.criar_execucao(usuario_adm, "erro_http", nome="Zzz", minutos_atras=5)
    contexto = _lista(usuario_adm)
    assert [e["fluxo_nome"] for e in contexto["execucoes"]] == ["Zzz", "Aaa"]  # -iniciada_em
    zzz = contexto["execucoes"][0]
    assert zzz["status"] == "erro" and zzz["duracao_texto"] and zzz["erro_resumo"]
    assert zzz["url_detalhe"].endswith(f"/{zzz['pk']}/")
    assert [e["fluxo_nome"] for e in _lista(usuario_adm, status="sucesso")["execucoes"]] == ["Aaa"]
    assert [e["fluxo_nome"] for e in _lista(usuario_adm, ordem="fluxo")["execucoes"]] == [
        "Aaa",
        "Zzz",
    ]
    assert _lista(usuario_adm, ordem="-fluxo")["ordenacoes"]["fluxo"]["sentido"] == "desc"
    assert [o["rotulo"] for o in contexto["filtros_status"]] == [
        "Todos",
        "Executando",
        "Sucesso",
        "Erro",
    ]


def test_valores_invalidos_sao_ignorados_e_nul_na_busca(usuario_adm):
    contexto = _lista(usuario_adm, status="x", ordem="grafo_snapshot", q="\x00", pagina="abc")
    assert contexto["status_atual"] == "" and contexto["ordem"] == "-iniciada_em"
    assert contexto["q"] == "" and contexto["page_obj"].number == 1


def test_executando_antigo_conta_como_erro_no_filtro(usuario_adm):
    from datetime import timedelta

    velha = demo.criar_execucao(usuario_adm, "sucesso", nome="Travada")
    Execucao.objects.filter(pk=velha.pk).update(
        status="executando", finalizada_em=None, iniciada_em=timezone.now() - timedelta(minutes=9)
    )
    recente = demo.criar_execucao(usuario_adm, "sucesso", nome="Rodando")
    Execucao.objects.filter(pk=recente.pk).update(status="executando", finalizada_em=None)
    nomes = lambda **p: {e["fluxo_nome"] for e in _lista(usuario_adm, **p)["execucoes"]}  # noqa: E731
    assert nomes(status="erro") == {"Travada"} and nomes(status="executando") == {"Rodando"}
    travada = next(e for e in _lista(usuario_adm)["execucoes"] if e["fluxo_nome"] == "Travada")
    assert travada["status"] == "erro" and travada["erro_resumo"] == "Execução interrompida"


def test_queries_da_lista_constantes(usuario_adm, django_assert_max_num_queries):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    demo.criar_execucao(usuario_adm)
    _lista(usuario_adm)
    with CaptureQueriesContext(connection) as base:
        _lista(usuario_adm)
    for _ in range(30):
        demo.criar_execucao(usuario_adm)
    with django_assert_max_num_queries(len(base.captured_queries)):
        _lista(usuario_adm)


def test_detalhe_sucesso(usuario_coordenador):
    fluxo = demo_fluxos.criar_fluxo(
        usuario_coordenador, "Consulta de pedidos", "ativo", demo_fluxos.grafo_exemplo()
    )
    execucao = demo.criar_execucao(usuario_coordenador, "sucesso", fluxo=fluxo)
    contexto = _detalhe(usuario_coordenador, execucao.pk)
    assert contexto["execucao"]["status"] == "sucesso" and contexto["execucao"]["duracao_texto"]
    assert [n["titulo"] for n in contexto["nos"]] == ["Início", "Buscar pedido", "Resultado"]
    http = contexto["nos"][1]
    assert (
        http["http_status"] == 200
        and {"nome": "x-request-id", "valor": "demo-123"} in http["headers_saida"]
    )
    assert '"cliente": "Maria Ficticia"' in http["corpo_texto"] and http["truncado"] is False
    assert "••••" in http["entrada_json"] and "Bearer" not in http["entrada_json"]
    assert contexto["resultado_json"] and '"status": 200' in contexto["resultado_json"]
    assert contexto["url_fluxo"].endswith(f"/{fluxo.pk}/editor/")


def test_detalhe_erro_e_nao_executado(usuario_coordenador):
    execucao = demo.criar_execucao(usuario_coordenador, "erro_http")
    nos = _detalhe(usuario_coordenador, execucao.pk)["nos"]
    assert [n["status"] for n in nos] == ["sucesso", "erro", "nao_executado"]
    assert nos[1]["erro_categoria"] == "http_5xx" and nos[1]["erro_rotulo"] == "Erro HTTP 5xx"
    assert (
        nos[1]["http_status"] == 500
        and nos[2]["duracao_texto"] == ""
        and nos[2]["http_status"] is None
    )
    assert _detalhe(usuario_coordenador, execucao.pk)["resultado_json"] == ""


def test_detalhe_url_fluxo_vazia_sem_fluxo_ou_sem_permissao(usuario_coordenador, usuario_base):
    sem_fluxo = demo.criar_execucao(usuario_coordenador)
    assert _detalhe(usuario_coordenador, sem_fluxo.pk)["url_fluxo"] == ""
    fluxo = demo_fluxos.criar_fluxo(usuario_coordenador, "F", "ativo", demo_fluxos.grafo_exemplo())
    da_base = demo.criar_execucao(usuario_base, fluxo=fluxo)
    assert _detalhe(usuario_base, da_base.pk)["url_fluxo"] == ""


def test_detalhe_fora_do_escopo_e_inexistente_404(usuario_base, usuario_coordenador):
    alheia = demo.criar_execucao(usuario_coordenador)
    with pytest.raises(Http404):
        _detalhe(usuario_base, alheia.pk)
    with pytest.raises(Http404):
        _detalhe(usuario_base, 999999)


def test_demo_cria_tres_cenarios_sem_segredo(usuario_adm):
    for cenario in ("sucesso", "erro_http", "bloqueado_ssrf"):
        execucao = demo.criar_execucao(usuario_adm, cenario)
        assert execucao.nos.count() == 3
    import json

    bruto = json.dumps([list(e.nos.values("entrada", "saida")) for e in Execucao.objects.all()])
    assert "Bearer" not in bruto


def test_semear_demo_cria_execucoes_uma_vez():
    from django.core.management import call_command

    call_command("semear_demo", senha="SenhaForte#12345")
    total = Execucao.objects.count()
    assert total == 4
    call_command("semear_demo", senha="SenhaForte#12345")
    assert Execucao.objects.count() == total


def test_outras_pessoas_nao_veem_execucao_de_base_diferente(usuario_base):
    outra = criar_usuario("outra@exemplo.test", "Outra", "Base")
    demo.criar_execucao(outra, nome="Da outra")
    assert _lista(usuario_base)["execucoes"] == []
