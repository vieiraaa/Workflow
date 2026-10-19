"""Render das telas do Jurídico (M8, TEL-27..35) com contexto de exemplo (contrato CAD-19/CAD-23), sem depender das views."""

import json
import re

import pytest
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.test import RequestFactory

pytestmark = pytest.mark.modulo("m8")

HOSTIL = '<script>alert(1)</script>'


@pytest.fixture
def pedido(usuario_adm):
    req = RequestFactory().get("/juridico/")
    req.user = usuario_adm
    req.session = {}
    return req


def pagina(itens, por=25):
    return Paginator(itens, por).page(1)


def tela(pedido, nome, **ctx):
    return render_to_string(nome, ctx, request=pedido)


def proc(pk=1, **extra):
    base = {
        "pk": pk, "numero": f"000{pk}655-91.2025.8.16.0024", "adverso": f"Fulano {HOSTIL}", "cpf_cnpj_mascarado": "***.456.789-**",
        "carteira": "Ativos", "comarca": "Curitiba", "valor_texto": "R$ 1.234,56", "status": "CONFERIR", "status_rotulo": "Conferir",
        "cnj_situacao": "confere", "audiencia_texto": "18/09/2026 10:00", "audiencia_proxima": True, "selecionado": pk == 1,
        "url_painel": f"/juridico/?p={pk}", "url_detalhe": f"/juridico/processos/{pk}/", "url_excluir": f"/juridico/processos/{pk}/excluir/",
        "pode_excluir": True,
    }
    base.update(extra)
    return base


RESUMO = {"total": 3, "com_pendencias": 1, "conferir": 1, "cadastrados": 1, "na_fila": 2, "erros": 0}
CARTEIRAS = [
    {"chave": "todos", "nome": "Todos", "total": 3, "ativa": True, "ativo": True, "url": "?"},
    {"chave": "1", "nome": "Ativos", "total": 3, "ativa": True, "ativo": False, "url": "?carteira=1"},
    {"chave": "outros", "nome": "Outros", "total": 0, "ativa": True, "ativo": False, "url": "?carteira=outros"},
]


def contexto_painel(**extra):
    base = {
        "titulo_lista": "Processos · Todos", "consulta": "", "resumo": RESUMO, "carteiras": CARTEIRAS, "filtros": {"status": "", "carteira": "", "tribunal": "", "cnj": "", "q": "", "ordem": ""},
        "processos": pagina([proc(1), proc(2, selecionado=False, status="COM_PENDENCIAS", status_rotulo="Com pendências", cnj_situacao="divergente")]),
        "processo_sel": {
            "pk": 1, "numero": "0008655-91.2025.8.16.0024", "status": "CONFERIR", "status_rotulo": "Conferir", "carteira": "Ativos",
            "tribunal": "TJPR", "pendencias": ["Verificar: Juízo"], "url_detalhe": "/juridico/processos/1/", "url_marcar": "/juridico/processos/1/marcar/",
            "pode_marcar": True, "pode_editar": True,
            "grupos": [{"titulo": "PARTES", "campos": [{"rotulo": "Adverso", "valor": HOSTIL}]}],
            "andamentos": [{"data": "18/08/2026", "evento": "Petição", "fonte": "cnj"}],
        },
        "aviso_datajud": "", "atualizar_auto": False, "url_status": "/juridico/status/", "ultimos_envios": [],
        "pode_enviar": True, "pode_editar": True, "pode_configurar": True, "url_enviar_pdfs": "/juridico/enviar-pdfs/", "url_enviar_cnj": "/juridico/enviar-cnj/",
        "url_processo_novo": "/juridico/processos/novo/", "url_erros": "/juridico/erros/", "url_envios": "/juridico/envios/", "url_config": "/juridico/config/",
        "url_audiencias": "/juridico/audiencias/", "audiencias_n": 5, "audiencias_urgente": True,
    }
    base.update(extra)
    return base


def test_painel_tres_colunas_escapa_e_tem_menu(pedido):
    html = tela(pedido, "juridico/painel.html", **contexto_painel())
    assert HOSTIL not in html and "&lt;script&gt;" in html
    sem_tags = re.sub(r"<[^>]+>", "", html)
    assert "3 processos · 1 com pendências · 1 cadastrados" in sem_tags
    for trecho in ("Painel de Processos", "CLIENTES", "Processos · Todos (2)", "DETALHES DO PROCESSO", "PARTES", "Audiências (5)", "botao--destrutivo botao--alerta",
                   "Enviar PDFs para leitura", "Cadastrar pelo nº (CNJ)", "Log de erros e desempenho", "Configuração",
                   "***.456.789-**", "R$ 1.234,56", "18/09/2026 10:00", "Marcar cadastrado no Espaider", "Verificar: Juízo", "Ele some do painel; o histórico fica guardado.", "Confirmar exclusão", 'data-resumo="com_pendencias"'):
        assert trecho in html, trecho
    assert 'data-href-desktop="/juridico/?p=2"' in html and 'href="/juridico/processos/2/"' in html
    assert "data-status-url" not in html  # sem fila, sem auto-atualização


def test_painel_com_fila_liga_auto_atualizacao(pedido):
    html = tela(pedido, "juridico/painel.html", **contexto_painel(atualizar_auto=True))
    assert 'data-status-url="/juridico/status/"' in html and "data-painel-aviso" in html


def test_painel_vazio_e_filtrado(pedido):
    vazio = tela(pedido, "juridico/painel.html", **contexto_painel(processos=pagina([]), processo_sel=None))
    assert "Nenhum processo cadastrado ainda. Envie os PDFs ou cadastre pelo número." in vazio and "Nenhum processo selecionado" in vazio
    filtrado = tela(pedido, "juridico/painel.html", **contexto_painel(
        processos=pagina([]), processo_sel=None, filtros={"status": "CONFERIR", "carteira": "", "tribunal": "", "cnj": "", "q": "zz", "ordem": ""}))
    assert "Nenhum processo encontrado" in filtrado and "Limpar filtros" in filtrado
    assert 'aria-current="true"' in filtrado  # cartão do filtro em uso


def test_painel_sem_permissoes_esconde_acoes_do_menu(pedido):
    html = tela(pedido, "juridico/painel.html", **contexto_painel(
        pode_enviar=False, pode_editar=False, pode_configurar=False,
        processo_sel={**contexto_painel()["processo_sel"], "pode_marcar": False, "pode_editar": False}, audiencias_urgente=False))
    assert "Enviar PDFs para leitura" not in html and "Cadastro manual" not in html and "Configuração" not in html
    assert "Marcar cadastrado" not in html


def test_painel_aviso_datajud_so_com_texto(pedido):
    html = tela(pedido, "juridico/painel.html", **contexto_painel(aviso_datajud="Chave do DataJud recusada."))
    assert "Chave do DataJud recusada." in html and 'data-estado="aviso_datajud"' in html


def grupos_form(form):
    return [{"titulo": "Identificação", "campos": [{"nome": "numero", "rotulo": "Número", "campo": form["numero"], "origem": "pdf"}]},
            {"titulo": "Pedidos", "campos": [{"nome": "pedidos", "rotulo": "Pedidos", "campo": form["pedidos"], "origem": "manual"}]}]


@pytest.fixture
def form_processo():
    from django import forms

    class F(forms.Form):
        numero = forms.CharField(label="Número")
        pedidos = forms.CharField(label="Pedidos", widget=forms.Textarea, required=False)

    return F


def test_conferencia_origem_pendencias_cnj_e_acoes(pedido, form_processo):
    form = form_processo({"numero": "", "pedidos": HOSTIL})
    form.is_valid()
    html = tela(pedido, "juridico/processo.html", processo={"pk": 1, "numero": "0001", "status": "COM_PENDENCIAS", "status_rotulo": "Com pendências",
                "carteira": "Ativos"}, form=form, grupos=grupos_form(form), pendencias=["Verificar: Juízo"],
                cnj={"situacao": "divergente", "divergencias": ["Comarca (PDF: x · CNJ: y)"], "consultado_em": "19/10/2026 10:00"},
                envios=[{"quando": "19/10/2026 09:00", "usuario": "Ana", "origem": "PDF", "descricao": ""}], pode_editar=True, pode_marcar=True,
                pode_desfazer=True, url_pdf="/juridico/itens/9/pdf/")
    assert HOSTIL not in html
    for trecho in ("Validação no CNJ", "Comarca (PDF: x · CNJ: y)", "origem--pdf", "origem--manual", "Verificar: Juízo", "Baixar PDF",
                   "Consultar CNJ de novo", "Marcar como cadastrado no Espaider", "Desfazer cadastrado", "Histórico de envios", "Este campo é obrigatório.", "Salvar"):
        assert trecho in html, trecho


def test_conferencia_somente_leitura_sem_flags(pedido, form_processo):
    form = form_processo()
    html = tela(pedido, "juridico/processo.html", processo={"pk": 1, "numero": "0001", "status": "CADASTRADO", "status_rotulo": "Cadastrado no Espaider", "carteira": ""},
                form=form, grupos=grupos_form(form), pendencias=[], cnj={"situacao": "nao_consultado", "divergencias": []}, envios=[],
                pode_editar=False, pode_marcar=False, pode_desfazer=False, url_pdf="")
    assert "Marcar como cadastrado" not in html and "Baixar PDF" not in html and "Nenhum envio tocou" in html
    assert 'type="submit"' not in html.split("Histórico")[0].split("data-form-processo")[1]


def test_cadastro_manual_mostra_duplicidade_e_erro_de_campo(pedido, form_processo):
    form = form_processo({"numero": ""})
    form.is_valid()
    html = tela(pedido, "juridico/processo_novo.html", form=form, grupos=grupos_form(form), aviso_duplicidade="Este processo já existia: cadastrado por Ana.",
                url_duplicado="/juridico/processos/3/")
    assert "Este processo já existia" in html and 'href="/juridico/processos/3/"' in html and "Cadastrar processo" in html


def test_enviar_pdfs_dropzone_e_limites(pedido):
    from django import forms

    class F(forms.Form):
        carteira = forms.ChoiceField(label="Carteira", required=False, choices=[("", "Outra / não sei"), ("1", "Ativos")])

    html = tela(pedido, "juridico/enviar_pdfs.html", form=F(), erros_arquivos=["Escolha ao menos um PDF."])
    for trecho in ('enctype="multipart/form-data"', "data-dropzone", 'name="arquivos"', "multiple", 'data-max-arquivos="10"', 'data-max-mb="30"',
                   "Arraste os PDFs aqui", "Escolha ao menos um PDF.", "csrfmiddlewaretoken"):
        assert trecho in html, trecho


def test_enviar_cnj_padrao_e_confirmacao(pedido):
    from django import forms

    class F(forms.Form):
        numeros = forms.CharField(widget=forms.Textarea)
        carteira = forms.ChoiceField(choices=[("", "Outra / não sei")])

    padrao = tela(pedido, "juridico/enviar_cnj.html", form=F(), confirmacao=None)
    assert "Números de processo" in padrao and "confirmar" not in padrao
    conf = tela(pedido, "juridico/enviar_cnj.html", form=F({"numeros": "1", "carteira": ""}), confirmacao=[
        {"numero": "0001", "valido": True, "ja_existe": {"url": "/juridico/processos/2/", "excluido": True, "aviso": "Este processo tinha sido excluído por Ana e foi restaurado."}},
        {"numero": "0002", "valido": True, "ja_existe": None}, {"numero": "x", "valido": False, "ja_existe": None}])
    assert 'name="confirmar"' in conf and "Já existe" in conf and "restaurado" in conf and "Excluído" in conf and "Novo" in conf and "Número inválido" in conf and "Confirmar e enviar" in conf


def test_envios_vazio_e_com_dados(pedido):
    vazio = tela(pedido, "juridico/envios.html", envios=pagina([]))
    assert "Nenhum envio ainda" in vazio
    cheio = tela(pedido, "juridico/envios.html", envios=pagina([{"pk": 5, "quando": "19/10/2026 09:00", "origem": "PDF", "casos": 3, "erros": 1,
                                                                 "duracao_texto": "12 s", "motivo": HOSTIL, "url": "/juridico/envios/5/"}]))
    assert HOSTIL not in cheio and 'data-href="/juridico/envios/5/"' in cheio and "1 erro" in cheio


def itens_envio():
    return [{"pk": 1, "nome": f"a{HOSTIL}.pdf", "status": "processando", "status_rotulo": "Processando", "acao": None, "motivo": "", "etapa": "",
             "aviso_duplicidade": "", "processo_url": "", "url_tentar": "", "pode_tentar": False},
            {"pk": 2, "nome": "b.pdf", "status": "ignorado", "status_rotulo": "Ignorado", "acao": None, "motivo": "", "etapa": "",
             "aviso_duplicidade": "Já temos este arquivo: processo 0001 · enviado por Ana.", "processo_url": "/juridico/processos/1/", "url_tentar": "", "pode_tentar": False},
            {"pk": 3, "nome": "c.pdf", "status": "erro", "status_rotulo": "Erro", "acao": None, "motivo": "A IA não respondeu", "etapa": "IA (Dify)",
             "aviso_duplicidade": "", "processo_url": "", "url_tentar": "/juridico/itens/3/tentar-de-novo/", "pode_tentar": True}]


def test_envio_em_andamento_duplicado_e_erro(pedido):
    html = tela(pedido, "juridico/envio.html", envio={"pk": 5, "quando": "19/10/2026 09:00", "origem": "PDF", "enviado_por": "Ana", "carteira": "Ativos"},
                itens=itens_envio(), url_status="/juridico/status/?envio=5")
    assert HOSTIL not in html
    for trecho in ('data-status-url="/juridico/status/?envio=5"', "Já temos este arquivo", "Abrir o processo", "Tentar de novo", "IA (Dire)".replace("Dire", "Dify"),
                   "badge--executando", "badge--erro", "A IA não respondeu"):
        assert trecho in html, trecho


def contexto_erros(vazio=False):
    return {
        "cartoes": {"ultima": None if vazio else {"quando": "19/10/2026 09:00", "origem": "PDF", "casos": 3, "erros": 1}, "execucoes": {"envios": 0 if vazio else 2, "casos": 0 if vazio else 5},
                    "casos_erro": {"n": 0 if vazio else 1, "pct": "0%" if vazio else "20%"}, "tempo_medio": {"execucao": "12 s", "caso": "4 s"}, "erros_pendentes": 0 if vazio else 1},
        "casos_por_dia": [] if vazio else [{"dia": "18/10", "rotulo": "18/10", "ok": 4, "sucesso": 4, "erro": 1, "tempo_medio_s": 9, "tempo_medio_texto": "9 s"}],
        "erros_por_etapa": [] if vazio else [{"etapa": "IA (Dify)", "rotulo": "IA (Dify)", "total": 1}],
        "envios": [] if vazio else [{"pk": 5, "quando": "19/10/2026 09:00", "origem": "PDF", "casos": 3, "erros": 1, "duracao_texto": "12 s", "motivo": "x", "url": "/juridico/envios/5/"}],
        "itens": pagina([] if vazio else [{"pk": 3, "quando": "19/10/2026 09:00", "nome": f"c{HOSTIL}.pdf", "etapa": "IA (Dify)", "motivo": "A IA não respondeu",
                                           "resolvido": False, "url_resolvido": "/juridico/itens/3/resolvido/", "url_tentar": "/juridico/itens/3/tentar-de-novo/"}]),
        "filtro_resolvido": False,
    }


def test_log_de_erros_com_dados_e_vazio(pedido):
    html = tela(pedido, "juridico/erros.html", **contexto_erros())
    assert HOSTIL not in html
    for trecho in ("Última execução", "Casos por dia", "Erros pendentes por etapa", "data-grafico", "Resolvido", "Tentar de novo", "Mostrar resolvidos", "20%"):
        assert trecho in html, trecho
    assert json.loads(html.split('id="juridico-casos" type="application/json">')[1].split("</script>")[0])[0]["sucesso"] == 4
    vazio = tela(pedido, "juridico/erros.html", **contexto_erros(True))
    assert "Nenhum erro pendente" in vazio and "Sem envios nos últimos 30 dias." in vazio and "Nenhum envio no período" in vazio


def test_audiencias_vazio_e_com_dados(pedido):
    vazio = tela(pedido, "juridico/audiencias.html", processos=[])
    assert "Nenhuma audiência marcada" in vazio
    cheio = tela(pedido, "juridico/audiencias.html", processos=[proc()])
    assert "18/09/2026 10:00" in cheio and "chip--erro" in cheio and HOSTIL not in cheio


def test_configuracao_campos_carteiras_e_teste(pedido):
    from django import forms

    class F(forms.Form):
        dify_url = forms.URLField(label="URL do Dify")
        dify_credencial = forms.ChoiceField(label="Credencial do Dify", choices=[("", "—"), ("dify", "dify")])
        dify_usuario = forms.CharField(label="Usuário do Dify")
        dify_ca_pem = forms.CharField(label="CA (PEM)", required=False, widget=forms.Textarea)
        datajud_url = forms.URLField(label="URL do DataJud")
        datajud_credencial = forms.ChoiceField(label="Credencial do DataJud", choices=[("", "—")])
        setores_com_acesso = forms.MultipleChoiceField(label="Setores", choices=[("1", "Jurídico")], widget=forms.CheckboxSelectMultiple, required=False)

    html = tela(pedido, "juridico/config.html", form=F(), carteiras=[{"pk": 1, "nome": "Ativos", "empresa": "ATIVOS S.A.", "ativa": True}], excluidos=[],
                resultado_teste="Dify: ok · DataJud: falhou (timeout)")
    for trecho in ("Dify: ok · DataJud: falhou (timeout)", "Testar conexão", "Carteiras", "Setores com acesso", "Jurídico", 'value="Ativos"', "Adicionar"):
        assert trecho in html, trecho


def test_excluidos_lista_e_vazio(pedido):
    vazio = tela(pedido, "juridico/excluidos.html", processos=[])
    assert "Nenhum processo excluído" in vazio
    cheio = tela(pedido, "juridico/excluidos.html", processos=[{"pk": 1, "numero": "0001", "adverso": HOSTIL, "excluido_em": "19/10/2026", "excluido_por": "Ana",
                                                                "url_restaurar": "/juridico/processos/1/restaurar/"}])
    assert HOSTIL not in cheio and "Restaurar" in cheio


def test_menu_mostra_cabecalho_do_grupo_uma_vez(pedido):
    itens = [{"rotulo": "Início", "url": "/", "icone": "house", "ativo": False, "grupo": ""},
             {"rotulo": "Cadastro de processos", "url": "/juridico/", "icone": "scale", "ativo": True, "grupo": "Jurídico"},
             {"rotulo": "Outro", "url": "/x/", "icone": "scale", "ativo": False, "grupo": "Jurídico"}]
    html = render_to_string("base.html", {"menu": itens}, request=pedido)
    assert html.count('class="sidebar__grupo"') == 1 and "Jurídico" in html and "scale" in html
