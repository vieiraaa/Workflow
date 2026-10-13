"""Editor v2 (EDV-01..03): paleta agrupada, alças rotuladas, notas, inspector por tipo, copiar/colar."""

import pytest
from django.urls import reverse

from apps.fluxos.models import Fluxo, grafo_inicial

pytestmark = [
    pytest.mark.modulo("m5"),
    pytest.mark.django_db(transaction=True, serialized_rollback=True),
]


@pytest.fixture
def editor(pagina_motores, live_server, usuario_coordenador):
    fluxo = Fluxo.objects.create(nome="V2", dono=usuario_coordenador, grafo=grafo_inicial())
    pagina_motores.goto(live_server.url + reverse("fluxos:editor", kwargs={"pk": fluxo.pk}))
    pagina_motores.wait_for_selector(".drawflow-node")
    return pagina_motores


def _grafo(pagina):
    return pagina.evaluate("window.editorFlux.extrair()")


def _rotulos(pagina, tipo):
    return pagina.evaluate(
        f"[...document.querySelectorAll('.drawflow-node.no-{tipo} .output')].map(e => e.dataset.rotulo)"
    )


def test_paleta_agrupada_com_busca(editor):
    grupos = editor.locator(".paleta__grupo-titulo").all_inner_texts()
    assert grupos == ["Gatilhos", "Ações", "Dados", "Fluxo", "Saída", "Canvas"]
    assert editor.locator(".paleta__item").count() == 20  # 19 nós + Nota
    editor.fill("[data-paleta-busca]", "duplic")
    visiveis = editor.locator(".paleta__item:visible")
    assert visiveis.count() == 1 and "duplicados" in visiveis.first.inner_text()
    editor.fill("[data-paleta-busca]", "zzzz")
    assert editor.locator("[data-paleta-vazia]").is_visible()


def test_alcas_multiplas_rotuladas(editor):
    editor.click("[data-paleta-tipo=se]")
    assert _rotulos(editor, "se") == ["verdadeiro", "falso"]
    editor.click("[data-paleta-tipo=escolher]")
    assert _rotulos(editor, "escolher") == ["regra 1", "regra 2", "outros"]
    editor.click("[data-paleta-tipo=repetir_em_lotes]")
    assert _rotulos(editor, "no-repetir_em_lotes".replace("no-", "")) == ["loop", "pronto"]
    # Modo "saída de erro" acrescenta a alça "erro" ao HTTP.
    editor.click("[data-paleta-tipo=http]")
    editor.locator(".drawflow-node.no-http").click(position={"x": 60, "y": 20})
    editor.locator(".inspector__secao-titulo", has_text="Configurações do nó").click()
    editor.select_option("#insp-em_erro", "saida_de_erro")
    assert _rotulos(editor, "http") == ["", "erro"]
    saidas = [n for n in _grafo(editor)["nos"] if n["tipo"] == "http"][0]
    assert saidas["em_erro"] == "saida_de_erro"


def test_inspector_se_e_escolher(editor):
    editor.click("[data-paleta-tipo=se]")
    editor.fill("#insp-condicoes-0-esquerda", "{{ $json.n }}")
    editor.select_option("#insp-condicoes-0-operador", "maior")
    editor.fill("#insp-condicoes-0-direita", "10")
    no = [n for n in _grafo(editor)["nos"] if n["tipo"] == "se"][0]
    assert no["config"]["condicoes"][0] == {
        "esquerda": "{{ $json.n }}", "operador": "maior", "direita": "10", "tipo": "texto"
    }
    editor.click("text=Adicionar condição")
    assert editor.locator("#insp-combinar").count() == 1
    editor.click("[data-paleta-tipo=escolher]")
    editor.click("text=Adicionar regra")
    assert _rotulos(editor, "escolher") == ["regra 1", "regra 2", "regra 3", "outros"]


def test_campo_de_expressao_destaque_e_variaveis(editor):
    editor.click("[data-paleta-tipo=http]")
    editor.fill("#insp-url", "https://x.test/{{ $json.id }}")
    assert editor.locator(".expr__espelho .expr__chave").count() == 2
    assert editor.locator(".expr__espelho .expr__variavel").count() == 1
    # Chip de variável insere no campo focado.
    editor.click("#insp-url")
    editor.locator(".variaveis__titulo").first.click()
    editor.click(".variaveis__chip:has-text('$itemIndex')")
    assert "$itemIndex" in editor.input_value("#insp-url")


def test_editor_de_codigo_so_leitura_sem_permissao(editor):
    """Só Adm edita o nó Código (NOV-06): o Coordenador vê o editor, mas travado e com aviso."""
    editor.click("[data-paleta-tipo=codigo]")
    assert editor.locator("#insp-codigo").get_attribute("readonly") is not None
    assert "Só administradores" in editor.locator(".inspector__form").inner_text()
    assert editor.locator(".editor-codigo__linhas span").count() == 1


def test_nota_sticky_no_grafo_v2(editor):
    editor.click("[data-paleta-tipo=nota]")
    assert editor.locator(".nota").count() == 1
    editor.fill("#insp-nota-texto", "Atenção: <b>teste</b>")
    assert editor.locator(".nota__texto").inner_text() == "Atenção: <b>teste</b>"
    assert editor.locator(".nota b").count() == 0
    editor.click("[data-acao=ajustar]")
    alca = editor.locator(".nota__alca").bounding_box()
    editor.mouse.move(alca["x"] + 4, alca["y"] + 4)
    editor.mouse.down()
    editor.mouse.move(alca["x"] + 84, alca["y"] + 64, steps=5)
    editor.mouse.up()
    grafo = _grafo(editor)
    assert grafo["versao"] == 2 and len(grafo["notas"]) == 1
    assert grafo["notas"][0]["tamanho"]["l"] > 240 and grafo["notas"][0]["texto"].startswith("Atenção")
    assert [n["tipo"] for n in grafo["nos"]] == ["gatilho"]


def test_duplicar_desativar_e_colar(editor):
    editor.click("[data-paleta-tipo=http]")
    editor.fill("#insp-titulo", "Buscar")
    editor.click("[data-acao-no=duplicar]")
    titulos = [n["titulo"] for n in _grafo(editor)["nos"]]
    assert titulos.count("Buscar") == 1 and "Buscar 2" in titulos
    editor.locator(".inspector__secao-titulo", has_text="Configurações do nó").click()
    editor.locator(".toggle:has-text('Desativado')").click()
    assert editor.locator(".drawflow-node.no--desativado").count() == 1
    # Copiar/colar pelo evento de colagem (JSON do grafo v2).
    trecho = (
        '{"formato":"construtor-workflows-trecho","versao":2,"nos":[{"id":"x","tipo":"se","titulo":"Se",'
        '"posicao":{"x":10,"y":10},"config":{"condicoes":[],"combinar":"e"}}],"arestas":[],"notas":[]}'
    )
    editor.evaluate("document.activeElement.blur()")
    editor.evaluate(
        """(t) => { const d = new DataTransfer(); d.setData('text/plain', t);
        document.dispatchEvent(new ClipboardEvent('paste', {clipboardData: d, bubbles: true, cancelable: true})); }""",
        trecho,
    )
    assert "se" in [n["tipo"] for n in _grafo(editor)["nos"]]


def test_gatilho_unico_e_dados_fixos_no_grafo(editor):
    editor.click("[data-paleta-tipo=gatilho]")
    assert [n["tipo"] for n in _grafo(editor)["nos"]].count("gatilho") == 1
    editor.evaluate(
        """() => { const g = window.editorFlux.extrair(); g.dados_fixos = {[g.nos[0].id]: [{json: {a: 1}}]};
        window.editorFlux.carregar(g); }"""
    )
    grafo = _grafo(editor)
    assert grafo["dados_fixos"][grafo["nos"][0]["id"]] == [{"json": {"a": 1}}]
    assert editor.locator(".no__fixo:visible").count() == 1


def test_contagem_nas_arestas_apos_teste(editor):
    editor.click("[data-paleta-tipo=saida]")
    grafo = _grafo(editor)
    de, para = grafo["nos"][0]["id"], grafo["nos"][1]["id"]
    editor.evaluate(
        """([de, para]) => { const g = window.editorFlux.extrair();
        g.arestas = [{de, saida: 0, para, entrada: 0}]; window.editorFlux.carregar(g);
        window.editorFlux.aplicarResultado({nos: {[de]: {status: 'sucesso', itens_entrada: 0, itens_saida: 3, saida: []}},
        arestas: [{de, saida: 0, para, entrada: 0, itens: 3}]}); }""",
        [de, para],
    )
    assert editor.locator(".aresta-rotulo text").text_content() == "3 itens"
    assert "3 itens" in editor.locator(".drawflow-node").first.inner_text()


def test_corpo_http_formulario_vira_lista_e_volta_a_texto(editor):
    editor.click("[data-paleta-tipo=http]")
    editor.select_option("#insp-corpo-tipo", "formulario")
    editor.click("text=Adicionar")  # primeiro "Adicionar" do formulário: parâmetros de consulta
    http = [n for n in _grafo(editor)["nos"] if n["tipo"] == "http"][0]
    assert http["config"]["corpo"] == {"tipo": "formulario", "conteudo": []}
    editor.locator(".campo:has-text('Campos do formulário') >> text=Adicionar").click()
    editor.locator(".campo:has-text('Campos do formulário') input").first.fill("a")
    editor.locator(".campo:has-text('Campos do formulário') input").nth(1).fill("1")
    http = [n for n in _grafo(editor)["nos"] if n["tipo"] == "http"][0]
    assert http["config"]["corpo"]["conteudo"] == [{"nome": "a", "valor": "1"}]
    editor.select_option("#insp-corpo-tipo", "json")
    http = [n for n in _grafo(editor)["nos"] if n["tipo"] == "http"][0]
    assert http["config"]["corpo"] == {"tipo": "json", "conteudo": ""}
