import pytest
from django.urls import reverse

from apps.execucoes.models import Execucao
from apps.fluxos.models import Fluxo, grafo_inicial
from apps.funcoes.models import Funcao

pytestmark = [pytest.mark.modulo("m7a"), pytest.mark.django_db]


def _grafo(valor):
    grafo = grafo_inicial()
    grafo["nos"].append(
        {
            "id": "n2",
            "tipo": "editar_campos",
            "titulo": "Calc",
            "posicao": {"x": 300, "y": 120},
            "config": {
                "modo": "manual",
                "campos": [{"nome": "r", "valor": valor, "tipo": "texto"}],
                "incluir_outros": False,
            },
            "desativado": False,
            "executar_uma_vez": False,
            "em_erro": "parar",
        }
    )
    grafo["arestas"].append({"de": "n1", "saida": 0, "para": "n2", "entrada": 0})
    return grafo


@pytest.fixture
def funcao(usuario_adm, cliente_adm):
    fluxo = Fluxo.objects.create(nome="F", dono=usuario_adm, grafo=_grafo("{{ $parametros.nome }}"))
    resposta = cliente_adm.post(
        reverse("funcoes:nova"),
        {
            "nome": "Saudar",
            "fluxo": fluxo.pk,
            "liberar_para": "todos",
            "icone": "zap",
            "ativa": "on",
            "entradas": (
                '[{"nome": "nome", "rotulo": "Nome", "tipo": "texto", "obrigatoria": true}]'
            ),
        },
    )
    assert resposta.status_code == 302
    obj = Funcao.objects.get()
    cliente_adm.post(reverse("funcoes:publicar", kwargs={"pk": obj.pk}))
    obj.refresh_from_db()
    return obj


def test_publicar_congela_o_grafo(funcao, usuario_adm, cliente_adm):
    assert funcao.versao == 1 and funcao.grafo_publicado["nos"][1]["id"] == "n2"
    quebrado = _grafo("x")
    quebrado["nos"][1]["config"]["campos"] = []  # pendência: "Inclua pelo menos um campo."
    funcao.fluxo.grafo = quebrado
    funcao.fluxo.save()
    cliente_adm.post(reverse("funcoes:publicar", kwargs={"pk": funcao.pk}))
    funcao.refresh_from_db()
    assert funcao.versao == 1 and funcao.grafo_publicado["nos"][1]["config"]["campos"]
    funcao.fluxo.grafo = grafo_inicial()
    funcao.fluxo.save()
    cliente_adm.post(reverse("funcoes:publicar", kwargs={"pk": funcao.pk}))
    funcao.refresh_from_db()
    assert funcao.versao == 2 and len(funcao.grafo_publicado["nos"]) == 1
    assert funcao.publicada_por == usuario_adm


def test_executar_grava_parametros_e_resultado(funcao, cliente_base, usuario_base):
    url = reverse("funcoes:executar", kwargs={"pk": funcao.pk})
    resposta = cliente_base.post(url, {"nome": "{{ $env }}"})
    execucao = Execucao.objects.get()
    assert resposta.status_code == 302
    assert resposta.url == reverse("funcoes:resultado", kwargs={"pk": execucao.pk})
    assert execucao.modo == "para_mim" and execucao.executado_por == usuario_base
    assert execucao.parametros == {"nome": "{{ $env }}"}  # FUN-08: valor é dado, nunca avaliado
    pagina = cliente_base.get(resposta.url)
    assert pagina.context["linhas"] == [["{{ $env }}"]] and pagina.context["colunas"] == ["r"]


def test_validacao_nao_executa(funcao, cliente_base):
    resposta = cliente_base.post(reverse("funcoes:executar", kwargs={"pk": funcao.pk}), {})
    assert resposta.status_code == 200 and not Execucao.objects.exists()
    assert resposta.context["campos"][0]["erro"] == "Preencha Nome."


def test_nul_da_400(funcao, cliente_base):
    resposta = cliente_base.post(
        reverse("funcoes:executar", kwargs={"pk": funcao.pk}), {"nome": "a\x00b"}
    )
    assert resposta.status_code == 400


def test_em_execucao_bloqueia_nova(funcao, cliente_base, usuario_base):
    Execucao.objects.create(
        fluxo=funcao.fluxo,
        fluxo_nome="F",
        executado_por=usuario_base,
        funcao=funcao,
        modo="para_mim",
    )
    resposta = cliente_base.post(
        reverse("funcoes:executar", kwargs={"pk": funcao.pk}), {"nome": "x"}
    )
    assert resposta.status_code == 302 and Execucao.objects.count() == 1


def test_privacidade_para_mim(funcao, cliente_base, cliente_coordenador, cliente_adm):
    cliente_base.post(reverse("funcoes:executar", kwargs={"pk": funcao.pk}), {"nome": "x"})
    execucao = Execucao.objects.get()
    detalhe = reverse("execucoes:detalhe", kwargs={"pk": execucao.pk})
    resultado = reverse("funcoes:resultado", kwargs={"pk": execucao.pk})
    assert cliente_adm.get(detalhe).status_code == 200
    assert cliente_adm.get(resultado).context["url_detalhe"] == detalhe
    assert cliente_coordenador.get(detalhe).status_code == 404
    assert cliente_coordenador.get(resultado).status_code == 404
    assert "Saudar" not in cliente_coordenador.get(reverse("execucoes:lista")).content.decode()


def test_gerenciar_so_adm(funcao, cliente_base, cliente_coordenador, cliente_anonimo):
    for cliente, status in (
        (cliente_base, 403),
        (cliente_coordenador, 403),
        (cliente_anonimo, 302),
    ):
        assert cliente.get(reverse("funcoes:nova")).status_code == status
        assert (
            cliente.post(reverse("funcoes:publicar", kwargs={"pk": funcao.pk})).status_code
            == status
        )


def test_catalogo_por_papel_e_inativa(funcao, cliente_base, cliente_adm):
    assert "Saudar" in cliente_base.get(reverse("funcoes:catalogo")).content.decode()
    cliente_adm.post(reverse("funcoes:alternar", kwargs={"pk": funcao.pk}))
    assert "Saudar" not in cliente_base.get(reverse("funcoes:catalogo")).content.decode()
    assert (
        cliente_base.post(
            reverse("funcoes:executar", kwargs={"pk": funcao.pk}), {"nome": "x"}
        ).status_code
        == 404
    )
    assert (
        cliente_adm.post(
            reverse("funcoes:executar", kwargs={"pk": funcao.pk}), {"nome": "x"}
        ).status_code
        == 404
    )


def test_catalogo_queries_constantes(funcao, cliente_base, django_assert_num_queries, usuario_adm):
    cliente_base.get(reverse("funcoes:catalogo"))
    for i in range(5):
        Funcao.objects.create(nome=f"G{i}", fluxo=funcao.fluxo, criada_por=usuario_adm, versao=1)
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as depois:
        cliente_base.get(reverse("funcoes:catalogo"))
    Funcao.objects.filter(nome__startswith="G").delete()
    with CaptureQueriesContext(connection) as antes:
        cliente_base.get(reverse("funcoes:catalogo"))
    assert len(depois) == len(antes)
