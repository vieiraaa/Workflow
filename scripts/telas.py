#!/usr/bin/env python
"""Captura e verificação das telas, a partir de docs/spec/telas.yaml.

  python scripts/telas.py --modulo 0      # capturas em docs/telas/m0/ (light/dark x 1440/390)
  python scripts/telas.py --verificar     # falha em console error ou overflow horizontal a 390px
  python scripts/telas.py --verificar --modulo 1

Sobe um servidor local (settings de teste, Postgres local, dados fictícios). Nunca toca a
DATABASE_URL. Para cada (tela, estado) o `PREPARADORES` abaixo monta os dados fictícios; os
módulos seguintes acrescentam as suas entradas.
"""

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings.teste"
# O Playwright síncrono roda um event loop; o ORM aqui é só preparo de dados do script.
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
# Banco próprio de cada execução (apagado no fim): não colide com pytest nem com outras execuções.
_BANCO_TELAS = f"construtor_telas_{os.getpid()}"
# Chave descartável do cofre (SEG-18): o servidor das capturas e este script usam a mesma.
if not os.environ.get("CREDENCIAIS_CHAVE"):
    from cryptography.fernet import Fernet

    os.environ["CREDENCIAIS_CHAVE"] = Fernet.generate_key().decode()
os.environ.setdefault("TEST_DATABASE_URL", f"postgres://localhost:5432/{_BANCO_TELAS}")

TEMAS = ("light", "dark")
LARGURAS = {1440: 900, 390: 844}
SENHA = "SenhaDemo#12345"
URL_INEXISTENTE = "/nao-existe/"


# ---------------------------------------------------------------- preparação de dados
def _limpar_dados_de_telas():
    """Apaga os dados fictícios de estados anteriores, dependentes primeiro (FK PROTECT)."""
    from apps.credenciais.models import Credencial
    from apps.execucoes.models import Execucao
    from apps.fluxos.models import Fluxo
    from apps.funcoes.models import Funcao

    Execucao.objects.all().delete()
    Funcao.objects.all().delete()
    Fluxo.objects.all().delete()
    Credencial.objects.all().delete()


def _apagar_usuarios_e_setores():
    from apps.contas.models import Setor, Usuario

    Usuario.objects.all().delete()
    Setor.objects.all().delete()


def _usuarios():
    from django.contrib.auth.models import Group

    from apps.contas.models import Setor, Usuario

    _limpar_dados_de_telas()
    _apagar_usuarios_e_setores()
    geral = Setor.objects.create(nome="Geral")
    for nome in ("Adm", "Coordenador", "Base"):
        Group.objects.get_or_create(name=nome)
    criados = {}
    for chave, email, nome, grupo in (
        ("adm", "adm@exemplo.test", "Ana Admin", "Adm"),
        ("coordenador", "coord@exemplo.test", "Caio Coordenador", "Coordenador"),
        ("base", "base@exemplo.test", "Bia Base", "Base"),
        ("sem_papel", "sem@exemplo.test", "Sem Papel", None),
    ):
        usuario = Usuario.objects.create_user(
            email=email, password=SENHA, nome=nome, setor=geral if grupo else None
        )
        if grupo:
            usuario.groups.add(Group.objects.get(name=grupo))
        criados[chave] = usuario
    return criados


def _erro_credenciais(page, base):
    page.fill("input[name=username]", "adm@exemplo.test")
    page.fill("input[name=password]", "senha-errada")
    page.click("form button[type=submit]")
    page.wait_for_load_state("networkidle")


def _enviar(page, seletor_form, preenchimento):
    """Preenche campos {name: valor} (select por valor) e envia o formulário do <main>."""
    for nome, valor in preenchimento.items():
        campo = page.locator(f"main form {seletor_form} [name={nome}]").first
        if campo.evaluate("e => e.tagName") == "SELECT":
            campo.select_option(valor)
        else:
            campo.fill(valor)
    page.locator(f"main form {seletor_form}").first.locator("button[type=submit]").first.click()
    page.wait_for_load_state("networkidle")


def _erro_novo(page, base):
    _enviar(
        page,
        "",
        {
            "nome": "Fulano de Tal",
            "email": "adm@exemplo.test",
            "papel": "base",
            "senha": "curta",
            "confirmacao": "diferente",
        },
    )


def _erro_editar(page, base):
    # o e-mail do Adm já existe: erro de validação sem esbarrar no `required` do navegador
    _enviar(page, "", {"email": "adm@exemplo.test"})


def _erro_trocar_senha(page, base):
    _enviar(page, "", {"senha_atual": "errada", "nova_senha": "curta", "confirmacao": "diferente"})


def _setores_demo(usuarios):
    from apps.contas.models import Setor

    for nome, ativo in (("Financeiro", True), ("Atendimento", True), ("Jurídico", False)):
        Setor.objects.create(nome=nome, ativo=ativo)


def _historico(usuarios):
    from apps.fluxos.demo import _semear_historico

    _semear_historico()


def _erro_setor(page, base):
    _enviar(page, "", {"nome": "Geral"})  # nome já existente (sem diferenciar maiúsculas)


def _usuarios_extras(quantidade):
    from django.contrib.auth.models import Group

    from apps.contas.models import Setor, Usuario

    geral = Setor.objects.get(nome="Geral")
    grupos = ["Adm", "Coordenador", "Base"]
    for i in range(quantidade):
        usuario = Usuario.objects.create_user(
            email=f"pessoa{i:02d}@exemplo.test",
            password=SENHA,
            nome=f"Pessoa Fictícia {i:02d}",
            setor=geral,
            is_active=i % 5 != 0,
        )
        usuario.groups.add(Group.objects.get(name=grupos[i % 3]))


def _com_dados(usuarios):
    _usuarios_extras(8)


def _paginado(usuarios):
    _usuarios_extras(40)


def _fluxos_demo(dono_chave, quantidade=8):
    """Fluxos fictícios variados (rascunho/ativo) para as listas."""

    def preparar(usuarios):
        from apps.fluxos import demo

        for i in range(quantidade):
            demo.criar_fluxo(
                usuarios[dono_chave],
                f"Fluxo fictício {i:02d}",
                "ativo" if i % 2 else "rascunho",
                demo.grafo_exemplo(),
                "Descrição de exemplo do fluxo." if i % 3 else "",
            )

    return preparar


def _so_rascunhos(usuarios):
    from apps.fluxos import demo

    demo.criar_fluxo(usuarios["coordenador"], "Rascunho invisível ao Base", "rascunho")


def _fluxo_demo(grafo_fabrica, status="rascunho"):
    def preparar(usuarios):
        from apps.fluxos import demo

        fluxo = demo.criar_fluxo(
            usuarios["coordenador"],
            "Consulta de pedidos",
            status,
            grafo_fabrica(),
            "Fluxo de demonstração.",
        )
        return {"fluxo_demo": fluxo}

    return preparar


def _grafos():
    from apps.fluxos import demo
    from apps.fluxos.models import grafo_inicial

    return demo, grafo_inicial


def _editor_vazio(usuarios):
    demo, grafo_inicial = _grafos()
    return _fluxo_demo(grafo_inicial)(usuarios)


def _editor_3_nos(usuarios):
    demo, _ = _grafos()
    return _fluxo_demo(demo.grafo_exemplo)(usuarios)


def _editor_erro(usuarios):
    demo, _ = _grafos()
    return _fluxo_demo(demo.grafo_com_url_invalida)(usuarios)


def _execucoes_da_base(usuarios):
    from datetime import timedelta

    from django.utils import timezone

    from apps.execucoes import demo
    from apps.execucoes.models import Execucao

    for i, cenario in enumerate(["sucesso", "erro_http", "sucesso", "bloqueado_ssrf"] * 3):
        demo.criar_execucao(
            usuarios["base"], cenario, nome=f"Fluxo fictício {i % 4:02d}", minutos_atras=3 + i * 7
        )
    demo.criar_execucao(usuarios["coordenador"], "sucesso", nome="Execução de outra pessoa")
    travada = demo.criar_execucao(usuarios["base"], "sucesso", nome="Execução travada")
    Execucao.objects.filter(pk=travada.pk).update(
        status="executando", finalizada_em=None, iniciada_em=timezone.now() - timedelta(minutes=9)
    )


def _execucao_demo(cenario):
    def preparar(usuarios):
        from apps.execucoes import demo

        return {"execucao_demo": demo.criar_execucao(usuarios["coordenador"], cenario)}

    return preparar


# ---- M7a: Funções (TEL-23..26). Papel das telas: adm (vê tudo; a "última execução" é a dele).
def _fluxo_da_funcao(usuarios, nome="Relatório de chamados (demo)"):
    from apps.fluxos import demo

    return demo.criar_fluxo(usuarios["adm"], nome, "ativo", demo.grafo_exemplo())


def _funcao(usuarios, fluxo, nome, **extra):
    from django.utils import timezone

    from apps.funcoes.models import Funcao

    publicar = extra.pop("versao", 1) >= 1
    funcao = Funcao.objects.create(
        nome=nome,
        fluxo=fluxo,
        criada_por=usuarios["adm"],
        versao=1 if publicar else 0,
        grafo_publicado=fluxo.grafo if publicar else {},
        publicada_em=timezone.now() if publicar else None,
        publicada_por=usuarios["adm"] if publicar else None,
        **extra,
    )
    return funcao


ENTRADAS_DEMO = [
    {
        "nome": "dia",
        "rotulo": "Dia do relatório",
        "tipo": "data",
        "obrigatoria": True,
        "padrao": None,
        "opcoes": [],
    },
    {
        "nome": "fila",
        "rotulo": "Fila de atendimento",
        "tipo": "lista",
        "obrigatoria": False,
        "padrao": None,
        "opcoes": ["Suporte", "Financeiro", "Comercial"],
    },
]


def _execucao_da_funcao(usuarios, funcao, cenario="sucesso"):
    """Execução `para_mim` do Adm, gravada direto (sem rodar o motor)."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.execucoes.models import Execucao, ExecucaoNo

    inicio = timezone.now() - timedelta(hours=3)
    erro = cenario == "erro"
    execucao = Execucao.objects.create(
        fluxo=funcao.fluxo,
        fluxo_nome=funcao.fluxo.nome,
        executado_por=usuarios["adm"],
        funcao=funcao,
        funcao_nome=funcao.nome,
        funcao_versao=funcao.versao,
        parametros={"dia": "2026-10-12", "fila": "Suporte"},
        modo="para_mim",
        status="erro" if erro else "sucesso",
        iniciada_em=inicio,
        finalizada_em=inicio + timedelta(milliseconds=840),
        erro_resumo="Chamados: erro HTTP 503" if erro else "",
    )
    total = 250 if cenario == "truncada" else 4
    itens = [
        {
            "json": {
                "id": 1000 + i,
                "assunto": f"Chamado fictício {i + 1}",
                "fila": "Suporte",
                "aberto": i % 2 == 0,
                "detalhes": {"prioridade": "alta"},
            }
        }
        for i in range(min(total, 200))
    ]
    ExecucaoNo.objects.create(
        execucao=execucao,
        no_id="n2",
        no_tipo="http" if erro else "editar_campos",
        no_titulo="Chamados",
        ordem=1,
        status="erro" if erro else "sucesso",
        entrada=[],
        saida=[] if erro else itens,
        itens_saida=0 if erro else total,
        erro_categoria="http_5xx" if erro else None,
        erro_mensagem="O servidor respondeu 503." if erro else "",
        duracao_ms=840,
    )
    return execucao


def _catalogo_demo(usuarios):
    fluxo = _fluxo_da_funcao(usuarios)
    funcoes = {
        "funcao_demo": _funcao(
            usuarios,
            fluxo,
            "Relatório diário de chamados",
            descricao="Lista os chamados abertos no dia escolhido, por fila de atendimento.",
            icone="bar-chart-3",
            entradas=ENTRADAS_DEMO,
        ),
        "sem_entradas": _funcao(
            usuarios,
            fluxo,
            "Atualizar painel",
            descricao="Roda com um clique, sem perguntas.",
            icone="refresh-cw",
        ),
        "rascunho": _funcao(
            usuarios,
            fluxo,
            "Envio de lembretes",
            icone="mail",
            versao=0,
            descricao="Em preparação.",
        ),
        "inativa": _funcao(usuarios, fluxo, "Conferência antiga", icone="list-checks", ativa=False),
    }
    _execucao_da_funcao(usuarios, funcoes["funcao_demo"])
    return funcoes


def _funcao_demo(usuarios):
    fluxo = _fluxo_da_funcao(usuarios)
    return {
        "funcao_demo": _funcao(
            usuarios,
            fluxo,
            "Relatório diário de chamados",
            descricao="Lista os chamados abertos no dia escolhido.",
            icone="bar-chart-3",
            entradas=ENTRADAS_DEMO,
        )
    }


def _resultado_demo(cenario):
    def preparar(usuarios):
        dados = _funcao_demo(usuarios)
        execucao = _execucao_da_funcao(usuarios, dados["funcao_demo"], cenario)
        return {**dados, "execucao_funcao_demo": execucao}

    return preparar


def _erro_funcao_nova(page, base):
    _enviar(page, "", {"nome": "", "liberar_para": "setores"})


def _erro_executar_funcao(page, base):
    page.fill("input[name=dia]", "")
    page.locator("main form button[type=submit]").last.click()
    page.wait_for_load_state("networkidle")


# ---- M5: credenciais, editor v2 e execução v2
def _credencial(usuarios, nome="Digisac", tipo="bearer", valor="TOKEN_FICTICIO_DIGISAC"):
    from apps.credenciais.models import Credencial

    credencial = Credencial(nome=nome, tipo=tipo, criado_por=usuarios["adm"])
    credencial.definir_dados({"valor": valor})
    credencial.save()
    return credencial


def _credenciais_demo(usuarios):
    _credencial(usuarios)
    _credencial(usuarios, "API de pedidos", "header", "VALOR_FICTICIO_1")
    _credencial(usuarios, "Portal interno", "basic", "SENHA_FICTICIA")


def _credencial_demo(usuarios):
    return {"credencial_demo": _credencial(usuarios)}


def _erro_credencial_duplicada(page, base):
    _enviar(page, "", {"nome": "Digisac", "valor": "OUTRO_VALOR_FICTICIO"})


def _no_v2(id_, tipo, titulo, x, y, config=None, **extra):
    return {
        "id": id_,
        "tipo": tipo,
        "titulo": titulo,
        "posicao": {"x": x, "y": y},
        "config": config or {},
        "desativado": False,
        "executar_uma_vez": False,
        "em_erro": "parar",
        **extra,
    }


def _http_v2(url, **extra):
    config = {
        "metodo": "GET",
        "url": url,
        "headers": [],
        "query": [{"nome": "pagina", "valor": "1"}],
        "corpo": {"tipo": "nenhum", "conteudo": ""},
        "credencial": "Digisac",
        "resposta": "automatica",
        "resposta_completa": False,
        "paginacao": None,
    }
    config.update(extra)
    return config


_PAGINACAO = {
    "modo": "atualizar_parametro",
    "onde": "query",
    "nome": "pagina",
    "valor": "{{ $pageCount + 1 }}",
    "parar_quando": "expressao",
    "expressao": "{{ $response.body.length < 20 }}",
    "limite_paginas": 10,
}
_CODIGO = "return items.map(i => ({ json: { id: i.json.id, titulo: i.json.titulo } }));"


def _grafo_v2(variante="ramos"):
    """Gatilho → HTTP (paginado) → Se → (Código → Saída | Sem operação); notas e dados fixos."""
    nos = [
        _no_v2("g", "gatilho", "Início", 40, 140),
        _no_v2(
            "h",
            "http",
            "Chamados do dia",
            260,
            140,
            _http_v2("https://api.exemplo.test/api/v1/tickets", paginacao=dict(_PAGINACAO)),
            em_erro="continuar" if variante == "erro_continuar" else "parar",
        ),
        _no_v2(
            "se",
            "se",
            "Tem chamados?",
            500,
            140,
            {
                "condicoes": [
                    {
                        "esquerda": "{{ $json.total }}",
                        "operador": "maior",
                        "direita": 0,
                        "tipo": "numero",
                    }
                ],
                "combinar": "e",
            },
        ),
        _no_v2(
            "c",
            "codigo",
            "Resumir",
            760,
            60,
            {"modo": "uma_vez_para_todos", "codigo": _CODIGO},
            desativado=variante == "relatorio",
        ),
        _no_v2("vazio", "sem_operacao", "Sem chamados", 760, 240),
        _no_v2("s", "saida", "Resultado", 1020, 60),
    ]
    if variante == "pendencias":
        nos[1]["config"]["url"] = ""
        nos.append(
            _no_v2(
                "seg",
                "http",
                "Com segredo",
                500,
                360,
                _http_v2(
                    "https://api.exemplo.test/x",
                    headers=[{"nome": "X-Chave", "valor": "{{ $credencial }}"}],
                ),
            )
        )
    arestas = [
        {"de": "g", "saida": 0, "para": "h", "entrada": 0},
        {"de": "h", "saida": 0, "para": "se", "entrada": 0},
        {"de": "se", "saida": 0, "para": "c", "entrada": 0},
        {"de": "se", "saida": 1, "para": "vazio", "entrada": 0},
        {"de": "c", "saida": 0, "para": "s", "entrada": 0},
    ]
    if variante == "pendencias":
        arestas.append({"de": "h", "saida": 0, "para": "seg", "entrada": 0})
    notas = [
        {
            "id": "nota1",
            "texto": "Lista os chamados de ontem e separa os que têm retorno.",
            "posicao": {"x": 260, "y": 20},
            "tamanho": {"l": 220, "a": 90},
            "cor": "amarela",
        }
    ]
    dados_fixos = {"g": [{"json": {"dia": "2026-10-12"}}]}
    return {
        "versao": 2,
        "nos": nos,
        "arestas": arestas,
        "notas": notas,
        "dados_fixos": dados_fixos,
    }


_RELATORIO = {
    "importados": ["Início", "Chamados do dia", "Tem chamados?", "Sem chamados", "Resultado"],
    "ajustes": [{"no": "Chamados do dia", "mensagem": "Opção 'timeout' do HTTP sem equivalente."}],
    "sem_equivalente": [{"no": "Avisar no Slack", "tipo_n8n": "n8n-nodes-base.slack"}],
    "expressoes_nao_suportadas": [
        {
            "no": "Chamados do dia",
            "campo": "query[0].valor",
            "expressao": "$json.itens.map(i => i.id).join(',')",
        }
    ],
    "segredos": [{"no": "Chamados do dia", "campo": "headers"}],
    "codigo_desativado": ["Resumir"],
}


def _fluxo_v2(variante):
    def preparar(usuarios):
        from apps.fluxos import demo

        _credencial(usuarios)
        fluxo = demo.criar_fluxo(
            usuarios["adm"],
            "Chamados do dia (demo v2)",
            "rascunho",
            _grafo_v2(variante),
            "Fluxo de demonstração do editor v2.",
        )
        if variante == "relatorio":
            fluxo.relatorio_importacao = _RELATORIO
            fluxo.save(update_fields=["relatorio_importacao"])
        return {"fluxo_v2_demo": fluxo}

    return preparar


def _abrir_no(titulo, rolar_ate=None):
    """Seleciona um nó no canvas para abrir o inspector; opcionalmente rola até uma seção dele.

    Falha silenciosa se o DOM mudar: a captura segue sem o inspector.
    """

    def acao(page, base):
        try:
            page.locator(".drawflow-node", has_text=titulo).first.click(timeout=3000)
            page.wait_for_timeout(300)
            if rolar_ate:
                secao = page.locator(".grupo-campos", has_text=rolar_ate).first
                secao.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(200)
        except Exception:  # noqa: BLE001
            pass

    return acao


def _item(**campos):
    return {"json": campos}


_CHAMADOS = [_item(id=i, titulo=f"Chamado fictício {i}", total=3) for i in (101, 102, 103)]


def _execucao_v2(cenario):
    def preparar(usuarios):
        from datetime import timedelta

        from django.utils import timezone

        from apps.execucoes.models import Execucao, ExecucaoNo
        from apps.fluxos import demo
        from apps.motor.mascarar import MASCARA, mascarar_grafo

        _credencial(usuarios)
        grafo = _grafo_v2("erro_continuar" if cenario == "erro_continuar" else "ramos")
        fluxo = demo.criar_fluxo(usuarios["adm"], "Chamados do dia (demo v2)", "ativo", grafo)
        pag = {"metodo": "GET", "headers": [{"nome": "Authorization", "valor": MASCARA}]}
        reqs = [
            {
                **pag,
                "url": "https://api.exemplo.test/api/v1/tickets",
                "query": [{"nome": "pagina", "valor": str(n)}],
                "corpo": "",
                "status": 200,
                "resposta": {
                    "status": 200,
                    "headers": {"content-type": "application/json"},
                    "corpo": '{"data": []}',
                    "truncado": False,
                },
            }
            for n in (1, 2)
        ]
        erro = cenario == "erro_continuar"
        teste = cenario == "teste"
        itens_http = [_item(erro={"categoria": "http_5xx", "mensagem": "Erro do servidor."})]
        # (id, tipo, título, status, entrada, saída, saidas_contagem, falha)
        passos = [
            ("g", "gatilho", "Início", "sucesso", [], [_item(dia="2026-10-12")], [1], None),
            (
                "h",
                "http",
                "Chamados do dia",
                "erro" if erro else "sucesso",
                [_item(dia="2026-10-12")],
                itens_http if erro else _CHAMADOS,
                [1] if erro else [3],
                ("http_5xx", "O servidor respondeu com erro do servidor (5xx).") if erro else None,
            ),
            (
                "se",
                "se",
                "Tem chamados?",
                "sucesso" if not erro else "sucesso",
                itens_http if erro else _CHAMADOS,
                itens_http if erro else _CHAMADOS,
                [0, 1] if erro else [3, 0],
                None,
            ),
            (
                "c",
                "codigo",
                "Resumir",
                "nao_executado" if (erro or teste) else "sucesso",
                _CHAMADOS,
                [] if (erro or teste) else [_item(total=3)],
                [0] if (erro or teste) else [1],
                None,
            ),
            (
                "vazio",
                "sem_operacao",
                "Sem chamados",
                "sucesso" if erro else "sem_itens",
                itens_http if erro else [],
                itens_http if erro else [],
                [1] if erro else [0],
                None,
            ),
            (
                "s",
                "saida",
                "Resultado",
                "nao_executado" if (erro or teste) else "sucesso",
                [],
                [] if (erro or teste) else [_item(total=3)],
                [],
                None,
            ),
        ]
        if teste:  # execução de teste: só até o nó "Tem chamados?"
            passos = [
                p if p[0] in ("g", "h", "se") else (*p[:3], "nao_executado", [], [], [0], None)
                for p in passos
            ]
        inicio = timezone.now() - timedelta(minutes=2)
        execucao = Execucao.objects.create(
            fluxo=fluxo,
            fluxo_nome=fluxo.nome,
            grafo_snapshot=mascarar_grafo(grafo),
            executado_por=usuarios["adm"],
            setor_id=fluxo.setor_id,
            status="sucesso",
            iniciada_em=inicio,
            finalizada_em=inicio + timedelta(milliseconds=640),
            teste=teste,
            arestas=[
                {"de": "g", "saida": 0, "para": "h", "entrada": 0, "itens": 1},
                {"de": "h", "saida": 0, "para": "se", "entrada": 0, "itens": 1 if erro else 3},
                {"de": "se", "saida": 0, "para": "c", "entrada": 0, "itens": 0 if erro else 3},
                {"de": "se", "saida": 1, "para": "vazio", "entrada": 0, "itens": 1 if erro else 0},
                {
                    "de": "c",
                    "saida": 0,
                    "para": "s",
                    "entrada": 0,
                    "itens": 0 if erro or teste else 1,
                },
            ],
        )
        for ordem, (id_, tipo, titulo, st, entrada, saida, contagem, falha) in enumerate(passos):
            ExecucaoNo.objects.create(
                execucao=execucao,
                no_id=id_,
                no_tipo=tipo,
                no_titulo=titulo,
                ordem=ordem,
                status=st,
                entrada=entrada,
                saida=saida,
                itens_entrada=len(entrada),
                itens_saida=len(saida),
                saidas_contagem=contagem,
                requisicoes=reqs if id_ == "h" else [],
                logs=["Resumindo 3 chamados"] if id_ == "c" and st == "sucesso" else [],
                erro_categoria=falha[0] if falha else None,
                erro_mensagem=falha[1] if falha else "",
                duracao_ms=120,
            )
        return {"execucao_v2_demo": execucao}

    return preparar


# (id da tela, estado) -> (preparar(usuarios) -> dict de nomes para kwargs | None,
#                          acao(page, base) depois do goto | None, querystring opcional)
PREPARADORES = {
    ("TEL-01", "padrao"): (None, None),
    ("TEL-01", "erro_credenciais"): (None, _erro_credenciais),
    ("TEL-10", "padrao"): (None, None),
    ("TEL-11", "padrao"): (None, None),
    ("TEL-02", "vazio_busca"): (None, None, "?q=sem-nenhum-resultado"),
    ("TEL-02", "com_dados"): (_com_dados, None),
    ("TEL-02", "paginado"): (_paginado, None),
    ("TEL-03", "padrao"): (None, None),
    ("TEL-03", "erro_validacao"): (None, _erro_novo),
    ("TEL-09", "padrao"): (None, None),
    ("TEL-09", "erro_validacao"): (None, _erro_editar),
    ("TEL-04", "vazio"): (None, None),
    ("TEL-04", "com_dados"): (_fluxos_demo("coordenador"), None),
    ("TEL-12", "vazio"): (_so_rascunhos, None),
    ("TEL-12", "com_dados"): (_fluxos_demo("coordenador"), None),
    ("TEL-05", "vazio"): (_editor_vazio, None),
    ("TEL-05", "com_3_nos"): (_editor_3_nos, None),
    ("TEL-05", "erro_validacao_no"): (_editor_erro, None),
    ("TEL-06", "vazio"): (None, None),
    ("TEL-06", "com_dados"): (_execucoes_da_base, None),
    ("TEL-07", "sucesso"): (_execucao_demo("sucesso"), None),
    ("TEL-07", "erro_http"): (_execucao_demo("erro_http"), None),
    ("TEL-07", "bloqueado_ssrf"): (_execucao_demo("bloqueado_ssrf"), None),
    ("TEL-13", "vazio"): (None, None),
    ("TEL-13", "com_dados_7d"): (_historico, None, "?periodo=7d"),
    ("TEL-13", "com_dados_24h"): (_historico, None, "?periodo=24h"),
    ("TEL-13", "com_dados_1a"): (_historico, None, "?periodo=1a"),
    ("TEL-16", "com_dados_7d"): (_historico, None, "?periodo=7d"),
    ("TEL-17", "vazio"): (None, None),
    ("TEL-17", "com_dados_7d"): (_historico, None, "?periodo=7d"),
    ("TEL-14", "com_dados"): (_setores_demo, None),
    ("TEL-15", "padrao"): (None, None),
    ("TEL-15", "erro_validacao"): (None, _erro_setor),
    ("TEL-08", "padrao"): (None, None),
    ("TEL-08", "erro_validacao"): (None, _erro_trocar_senha),
    ("TEL-18", "vazio"): (None, None),
    ("TEL-18", "com_dados"): (_credenciais_demo, None),
    ("TEL-19", "padrao"): (None, None),
    ("TEL-19", "erro_validacao"): (_credencial_demo, _erro_credencial_duplicada),
    ("TEL-20", "padrao"): (_credencial_demo, None),
    ("TEL-21", "com_ramos"): (_fluxo_v2("ramos"), None),
    ("TEL-21", "inspector_http_paginacao"): (
        _fluxo_v2("ramos"),
        _abrir_no("Chamados do dia", "Paginação"),
    ),
    ("TEL-21", "inspector_codigo"): (_fluxo_v2("ramos"), _abrir_no("Resumir")),
    ("TEL-21", "relatorio_importacao"): (_fluxo_v2("relatorio"), None),
    ("TEL-21", "pendencias_v2"): (_fluxo_v2("pendencias"), None),
    ("TEL-22", "sucesso_com_ramos"): (_execucao_v2("sucesso"), None),
    ("TEL-22", "erro_continuar"): (_execucao_v2("erro_continuar"), None),
    ("TEL-22", "teste"): (_execucao_v2("teste"), None),
    ("TEL-23", "vazio"): (None, None),
    ("TEL-23", "com_dados"): (_catalogo_demo, None),
    ("TEL-24", "padrao"): (_funcao_demo, None),
    ("TEL-24", "erro_validacao"): (_funcao_demo, _erro_funcao_nova),
    ("TEL-25", "padrao"): (_funcao_demo, None),
    ("TEL-25", "erro_campo"): (_funcao_demo, _erro_executar_funcao),
    ("TEL-26", "sucesso"): (_resultado_demo("sucesso"), None),
    ("TEL-26", "erro"): (_resultado_demo("erro"), None),
    ("TEL-26", "truncada"): (_resultado_demo("truncada"), None),
}


# ---------------------------------------------------------------- infraestrutura
def _porta_livre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _garantir_banco():
    """Cria o banco de teste local se faltar e aplica as migrations (nunca o Supabase)."""
    import django
    from django.conf import settings

    django.setup()
    from django.core.management import call_command

    config = settings.DATABASES["default"]
    import psycopg

    try:
        psycopg.connect(
            dbname=config["NAME"],
            host=config["HOST"] or None,
            port=config["PORT"] or None,
            user=config["USER"] or None,
            password=config["PASSWORD"] or None,
        ).close()
    except psycopg.OperationalError:
        admin = psycopg.connect(
            dbname="postgres",
            host=config["HOST"] or None,
            port=config["PORT"] or None,
            user=config["USER"] or None,
            password=config["PASSWORD"] or None,
            autocommit=True,
        )
        with admin:
            admin.execute(f'CREATE DATABASE "{config["NAME"]}"')
    call_command("migrate", verbosity=0, interactive=False)


def _apagar_banco():
    """Apaga o banco temporário desta execução (só se for o que o script criou)."""
    import psycopg
    from django.conf import settings
    from django.db import connections

    config = settings.DATABASES["default"]
    if config["NAME"] != _BANCO_TELAS:
        return
    connections.close_all()
    with psycopg.connect(
        dbname="postgres",
        host=config["HOST"] or None,
        port=config["PORT"] or None,
        user=config["USER"] or None,
        password=config["PASSWORD"] or None,
        autocommit=True,
    ) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{_BANCO_TELAS}" WITH (FORCE)')


ESPERA_SERVIDOR = 60  # segundos; a máquina pode estar ocupada com a suíte ou com o demo


def _ultimas_linhas(arquivo, quantidade=15):
    try:
        linhas = Path(arquivo).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(sem saída do servidor)"
    return "\n".join(linhas[-quantidade:]) or "(sem saída do servidor)"


def _subir_servidor():
    import tempfile

    porta = _porta_livre()
    log = tempfile.NamedTemporaryFile(  # noqa: SIM115 - fica aberto enquanto o servidor roda
        prefix="telas_runserver_", suffix=".log", delete=False
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "manage.py",
            "runserver",
            f"127.0.0.1:{porta}",
            "--noreload",
            "--insecure",
        ],
        cwd=RAIZ,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.teste"},
        stdout=subprocess.DEVNULL,
        stderr=log,
    )
    base = f"http://127.0.0.1:{porta}"
    limite = time.monotonic() + ESPERA_SERVIDOR
    pausa = 0.2
    while time.monotonic() < limite:
        if proc.poll() is not None:  # morreu ao subir: erro de código/configuração
            raise RuntimeError(
                "Servidor local falhou ao iniciar. Últimas linhas do runserver:\n"
                + _ultimas_linhas(log.name)
            )
        try:
            urllib.request.urlopen(base + "/entrar/", timeout=2)  # noqa: S310
            return proc, base
        except Exception:  # noqa: BLE001 - servidor ainda subindo
            time.sleep(pausa)
            pausa = min(pausa * 1.5, 2.0)
    proc.terminate()
    raise RuntimeError(
        f"Servidor local não subiu em {ESPERA_SERVIDOR} s (tempo esgotado). "
        "Últimas linhas do runserver:\n" + _ultimas_linhas(log.name)
    )


def _cookie_de_sessao(usuario):
    from django.conf import settings
    from django.test import Client

    cliente = Client()
    cliente.force_login(usuario)
    return settings.SESSION_COOKIE_NAME, cliente.cookies[settings.SESSION_COOKIE_NAME].value


def _carregar_telas(modulo):
    import yaml

    spec = yaml.safe_load((RAIZ / "docs/spec/telas.yaml").read_text(encoding="utf-8"))
    telas = spec["telas"]
    if modulo is not None:
        telas = [t for t in telas if t["modulo"] == f"m{modulo}"]
    return telas


def _url_da_tela(tela, contexto):
    from django.urls import NoReverseMatch, reverse

    if tela["rota"] == "url_inexistente":
        return URL_INEXISTENTE
    kwargs = {k: getattr(contexto.get(v), "pk", v) for k, v in (tela.get("kwargs") or {}).items()}
    try:
        return reverse(tela["rota"], kwargs=kwargs)
    except NoReverseMatch:
        return None


def _plano(telas, estritos):
    """Lista de (tela, estado) com preparador conhecido; sem preparador/rota: erro ou aviso."""
    itens, avisos = [], []
    for tela in telas:
        for estado in tela["estados"]:
            if (tela["id"], estado) not in PREPARADORES:
                avisos.append(f"{tela['id']}/{estado}: sem preparador de dados em scripts/telas.py")
                continue
            itens.append((tela, estado))
    return itens, avisos


def executar(modulo, verificar):
    from playwright.sync_api import Error as ErroPlaywright
    from playwright.sync_api import sync_playwright

    telas = _carregar_telas(modulo)
    itens, avisos = _plano(telas, estritos=modulo is not None)
    problemas, capturas = [], 0
    _garantir_banco()
    servidor, base = _subir_servidor()
    try:
        with sync_playwright() as pw:
            try:
                navegador = pw.chromium.launch()
            except ErroPlaywright as erro:
                print(
                    f"AMBIENTE: navegador do Playwright indisponível ({str(erro).splitlines()[0]})."
                )
                print("Rode: .venv/bin/python -m playwright install chromium")
                return 2
            for tela, estado in itens:
                usuarios = _usuarios()
                preparar, acao, *resto = PREPARADORES[(tela["id"], estado)]
                consulta = resto[0] if resto else ""
                contexto = {**{f"usuario_{k}": v for k, v in usuarios.items()}}
                if preparar:
                    contexto.update(preparar(usuarios) or {})
                caminho = _url_da_tela(tela, contexto)
                if caminho is None:
                    avisos.append(f"{tela['id']}/{estado}: rota '{tela['rota']}' ainda não existe")
                    continue
                papel = tela["papel"]
                for tema in TEMAS:
                    for largura, altura in LARGURAS.items():
                        ctx = navegador.new_context(
                            viewport={"width": largura, "height": altura},
                            color_scheme=tema,
                            base_url=base,
                        )
                        ctx.add_init_script(
                            f"try {{ localStorage.setItem('tema', '{tema}'); }} catch (e) {{}}"
                        )
                        if papel != "anonimo":
                            nome, valor = _cookie_de_sessao(usuarios[papel])
                            ctx.add_cookies([{"name": nome, "value": valor, "url": base}])
                        page = ctx.new_page()
                        erros = []
                        page.on("pageerror", lambda e, erros=erros: erros.append(f"pageerror: {e}"))
                        alvo = base + caminho
                        page.on(
                            "console",
                            lambda m, erros=erros, alvo=alvo: (
                                erros.append(f"console.error: {m.text}")
                                if m.type == "error"
                                and "favicon" not in (m.location.get("url") or "")
                                # 403/404 do documento é o estado esperado (TEL-10/11)
                                and (m.location.get("url") or "") != alvo
                                else None
                            ),
                        )
                        page.goto(base + caminho + consulta)
                        page.wait_for_load_state("networkidle")
                        if acao:
                            acao(page, base)
                        etiqueta = f"{tela['id']}/{estado}/{tema}/{largura}"
                        problemas += [f"{etiqueta}: {e}" for e in erros]
                        if largura == 390 and page.evaluate(
                            "document.documentElement.scrollWidth > window.innerWidth + 1"
                        ):
                            problemas.append(f"{etiqueta}: overflow horizontal em 390px")
                        if not verificar:
                            pasta = RAIZ / "docs" / "telas" / f"m{modulo}"
                            pasta.mkdir(parents=True, exist_ok=True)
                            page.screenshot(
                                path=str(pasta / f"{tela['id']}_{estado}_{tema}_{largura}.png"),
                                full_page=True,
                            )
                            capturas += 1
                        ctx.close()
            navegador.close()
    finally:
        servidor.terminate()
        servidor.wait()
        _apagar_banco()
    for aviso in avisos:
        print(f"aviso: {aviso}")
    if modulo is not None and not verificar:
        print(f"{capturas} captura(s) em docs/telas/m{modulo}/")
    if problemas:
        print("Problemas nas telas:")
        for p in problemas:
            print(f"- {p}")
        return 1
    print("Telas OK (sem console error, sem overflow horizontal em 390px)." if verificar else "OK.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--modulo", type=int, help="número do módulo (0, 1, ...)")
    parser.add_argument("--verificar", action="store_true", help="só verifica; não grava capturas")
    args = parser.parse_args()
    if args.modulo is None and not args.verificar:
        parser.error("informe --modulo N e/ou --verificar")
    return executar(args.modulo, args.verificar)


if __name__ == "__main__":
    sys.exit(main())
