"""Adversarial M8 · escopo/IDOR, escalada de papel, CSRF, método e mass assignment (CAD-01/02/13/14/15/21, permissoes.yaml, SEG-12)."""
from datetime import timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from .conftest import cnj, criar_processo, pdf_processo

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

NUM, DIG = cnj(1234)


def _u(nome, **kw):
    return reverse(f"juridico:{nome}", kwargs=kw) if kw else reverse(f"juridico:{nome}")


@pytest.fixture
def mundo(cad, enviar, rodar):
    """Um processo (da Ana, via PDF), um envio da Ana com item concluído e um item com erro; um processo excluído."""
    enviar(cad.ana, pdf_processo(NUM, "a"))
    rodar()
    ok = cad.ItemEnvio.objects.get()
    cad.dify.modo = "500"
    enviar(cad.ana, pdf_processo(cnj(2)[0], "b"))
    rodar()
    cad.dify.modo = None
    erro = cad.ItemEnvio.objects.exclude(pk=ok.pk).get()
    excl = criar_processo(cad, numero=cnj(3), excluido_em=timezone.now(), excluido_por=cad.adm_u, adverso_nome="Adverso Excluido Secreto")
    return type("M", (), {"processo": ok.processo, "ok": ok, "erro": erro, "excluido": excl})


# ---------------- sem acesso: nada, em nenhuma rota, com nenhum pk ----------------

def test_sem_acesso_nao_alcanca_nenhuma_rota_com_pk(cad, mundo):
    """CAD-02: Carla (setor sem acesso) recebe 403 em GET e POST de TODAS as rotas com pk, sem efeito colateral."""
    rotas_get = [_u("processo", pk=mundo.processo.pk), _u("envio", pk=mundo.ok.envio_id), _u("pdf", pk=mundo.ok.pk),
                 _u("status") + f"?envio={mundo.ok.envio_id}", _u("painel") + f"?p={mundo.processo.pk}"]
    for url in rotas_get:
        r = cad.carla.get(url)
        assert r.status_code == 403, url
        assert mundo.processo.numero not in r.content.decode()
    posts = [_u("processo", pk=mundo.processo.pk), _u("marcar_cadastrado", pk=mundo.processo.pk), _u("consultar_cnj", pk=mundo.processo.pk),
             _u("excluir", pk=mundo.processo.pk), _u("tentar_de_novo", pk=mundo.erro.pk), _u("resolver", pk=mundo.erro.pk),
             _u("desfazer_cadastrado", pk=mundo.processo.pk), _u("restaurar", pk=mundo.excluido.pk), _u("testar_conexao"),
             _u("config"), _u("carteira_nova"), _u("processo_novo"), _u("enviar_pdfs"), _u("enviar_cnj")]
    for url in posts:
        assert cad.carla.post(url, {"comarca": "Invadida", "nome": "Invasora", "numeros": cnj(9)[0]}).status_code == 403, url
    mundo.processo.refresh_from_db()
    mundo.erro.refresh_from_db()
    assert mundo.processo.comarca == "São Paulo" and mundo.processo.excluido_em is None and mundo.erro.status == "erro"
    assert not cad.Carteira.objects.filter(nome="Invasora").exists() and cad.Envio.objects.count() == 2


def test_anonimo_nao_alcanca_nada(cad, mundo):
    """CAD-02: anônimo é mandado ao login em GET e POST de todas as rotas, sem dados no corpo."""
    for url in (_u("painel"), _u("processo", pk=mundo.processo.pk), _u("envio", pk=mundo.ok.envio_id), _u("pdf", pk=mundo.ok.pk), _u("status"),
                _u("audiencias"), _u("config"), _u("excluidos")):
        r = cad.anonimo.get(url)
        assert r.status_code == 302 and reverse("login") in r["Location"] and mundo.processo.numero not in r.content.decode(), url
    for url in (_u("excluir", pk=mundo.processo.pk), _u("marcar_cadastrado", pk=mundo.processo.pk), _u("tentar_de_novo", pk=mundo.erro.pk),
                _u("testar_conexao"), _u("config")):
        r = cad.anonimo.post(url)
        assert r.status_code == 302 and reverse("login") in r["Location"], url


def test_usuario_inativo_perde_o_acesso_na_hora(cad, mundo):
    """CAD-02: desativar o usuário derruba a sessão existente (nenhuma rota responde 200)."""
    cad.ana_u.is_active = False
    cad.ana_u.save()
    r = cad.ana.get(_u("painel"))
    assert r.status_code in (302, 403) and mundo.processo.numero not in r.content.decode()


def test_trocar_de_setor_remove_o_acesso_sem_novo_login(cad):
    """CAD-02: mover o usuário para setor fora da lista bloqueia a sessão aberta."""
    assert cad.ana.get(_u("painel")).status_code == 200
    cad.ana_u.setor = cad.setor_b
    cad.ana_u.save()
    assert cad.ana.get(_u("painel")).status_code == 403


# ---------------- Base/Coordenador não escalam para ações de Adm ----------------

@pytest.mark.parametrize("quem", ["ana", "bruno"])
def test_acoes_de_adm_negadas_a_base_e_coordenador(cad, mundo, quem):
    """CAD-14/15/21: config, carteiras, testar conexão, restaurar e desfazer cadastrado são do Adm — 403 e nada muda."""
    c = getattr(cad, quem)
    cad.Processo._base_manager.filter(pk=mundo.processo.pk).update(status="CADASTRADO")
    antes = cad.config.dify_url
    assert c.post(_u("config"), {"dify_url": "http://127.0.0.1:1/x", "datajud_url": "http://127.0.0.1:1/y", "dify_usuario": "pwn"}).status_code == 403
    assert c.post(_u("carteira_nova"), {"nome": "Pwn", "empresa": "x"}).status_code == 403
    assert c.post(_u("carteira_editar", pk=cad.carteiras["Ativos"].pk), {"nome": "Pwn", "ativa": "on"}).status_code == 403
    assert c.post(_u("restaurar", pk=mundo.excluido.pk)).status_code == 403
    assert c.post(_u("desfazer_cadastrado", pk=mundo.processo.pk)).status_code == 403
    assert c.post(_u("testar_conexao")).status_code == 403
    assert c.get(_u("excluidos")).status_code == 403 and c.get(_u("config")).status_code == 403
    cad.config.refresh_from_db()
    mundo.processo.refresh_from_db()
    mundo.excluido.refresh_from_db()
    assert cad.config.dify_url == antes and mundo.processo.status == "CADASTRADO" and mundo.excluido.excluido_em is not None
    assert not cad.Carteira.objects.filter(nome="Pwn").exists()


def test_so_quem_enviou_ou_adm_acessa_envio_item_e_status(cad, mundo):
    """permissoes.yaml: detalhe do Envio/Item e ?envio= só de quem enviou e do Adm; Bruno (com acesso) é barrado; Carla também."""
    for outro in (cad.bruno, cad.carla):
        assert outro.get(_u("envio", pk=mundo.ok.envio_id)).status_code in (403, 404)
        assert outro.get(_u("status") + f"?envio={mundo.ok.envio_id}").status_code in (403, 404)
        assert outro.post(_u("tentar_de_novo", pk=mundo.erro.pk)).status_code in (403, 404)
    mundo.erro.refresh_from_db()
    assert mundo.erro.status == "erro"
    r = cad.bruno.get(_u("status"))
    assert r.status_code == 200 and "itens" not in r.json()


def test_status_json_sem_envio_nao_vaza_itens_de_outros(cad, mundo):
    """CAD-23 (8b): o status geral não traz itens nem nomes de arquivo de ninguém."""
    j = cad.bruno.get(_u("status")).json()
    assert "itens" not in j and "processo-a.pdf" not in str(j) and cad.ana_u.email not in str(j)


def test_nao_existe_oraculo_de_existencia_de_envio(cad, mundo):
    """CAD-02: Bruno recebe o mesmo status para um envio alheio existente e para um inexistente."""
    existente = cad.bruno.get(_u("envio", pk=mundo.ok.envio_id)).status_code
    inexistente = cad.bruno.get(_u("envio", pk=999999)).status_code
    assert existente == inexistente


# ---------------- processos excluídos ----------------

def test_excluido_some_de_todas_as_telas_e_acoes(cad, mundo):
    """CAD-21: processo excluído: 404 na conferência e nas ações, ausente de painel, ?p=, busca, contagens, audiências e status."""
    p = mundo.excluido
    cad.Processo._base_manager.filter(pk=p.pk).update(proxima_audiencia=timezone.now() + timedelta(days=2))
    for c in (cad.adm, cad.ana):
        assert c.get(_u("processo", pk=p.pk)).status_code == 404
        for acao in ("marcar_cadastrado", "consultar_cnj", "excluir"):
            assert c.post(_u(acao, pk=p.pk)).status_code == 404, acao
        assert c.post(_u("processo", pk=p.pk), {"comarca": "Zumbi"}).status_code == 404
        for url in (_u("painel"), _u("painel") + f"?p={p.pk}", _u("painel") + f"?q={p.numero_digitos}", _u("painel") + "?q=Secreto", _u("audiencias")):
            h = c.get(url).content.decode()
            assert p.numero not in h and "Adverso Excluido Secreto" not in h, url
        assert c.get(_u("painel")).context["resumo"]["total"] == 1 and c.get(_u("status")).json()["total"] == 1
    assert cad.Processo._base_manager.get(pk=p.pk).comarca == "São Paulo"


def test_excluidos_so_aparecem_ao_adm_na_configuracao(cad, mundo):
    """CAD-21: lista de excluídos só ao Adm e restaurar é idempotente (2ª vez não quebra)."""
    assert mundo.excluido.numero in cad.adm.get(_u("excluidos")).content.decode()
    assert cad.adm.post(_u("restaurar", pk=mundo.excluido.pk)).status_code == 302
    assert cad.adm.post(_u("restaurar", pk=mundo.excluido.pk)).status_code in (302, 404)
    assert cad.Processo.objects.filter(pk=mundo.excluido.pk).count() == 1


def test_restaurar_processo_que_nao_esta_excluido_e_inofensivo(cad, mundo):
    """CAD-21: restaurar um ativo não altera nada (nem quem/quando de exclusão inexistentes) e não dá 500."""
    r = cad.adm.post(_u("restaurar", pk=mundo.processo.pk))
    mundo.processo.refresh_from_db()
    assert r.status_code in (302, 404) and mundo.processo.excluido_em is None


def test_excluir_duas_vezes_nao_sobrescreve_quem_excluiu(cad, mundo):
    """CAD-21: excluir de novo (outra pessoa) não troca excluido_por/em do primeiro."""
    cad.ana.post(_u("excluir", pk=mundo.processo.pk))
    p = cad.Processo._base_manager.get(pk=mundo.processo.pk)
    primeiro, quando = p.excluido_por, p.excluido_em
    r = cad.bruno.post(_u("excluir", pk=mundo.processo.pk))
    p.refresh_from_db()
    assert r.status_code in (302, 404) and p.excluido_por == primeiro and p.excluido_em == quando


# ---------------- mass assignment / campos que ninguém pode setar pela tela ----------------

CAMPOS_PROTEGIDOS = {"status": "CADASTRADO", "cadastrado_espaider_em": "2020-01-01T00:00:00", "cadastrado_espaider_por": "1", "criado_por": "1",
                     "criado_via": "manual", "criado_em": "2000-01-01T00:00:00", "excluido_em": "2020-01-01T00:00:00", "excluido_por": "1",
                     "numero_valido": "false", "numero_digitos": "99999999999999999999", "cnj_validacao": "confere", "cnj_divergencias": "x",
                     "cnj_consultado_em": "2020-01-01T00:00:00", "origem_campos": '{"comarca": "pdf"}', "pendencias": "[]", "atualizado_por": "1",
                     "andamentos": "[]", "id": "99999", "pk": "99999"}


def test_salvar_processo_ignora_campos_protegidos(cad, mundo):
    """CAD-15 (mass assignment): POST de conferência com status/criado_por/excluido_*/cnj_*/origem… NÃO altera nada disso."""
    p = mundo.processo
    antes = {k: getattr(p, k) for k in ("status", "criado_por_id", "criado_via", "numero", "numero_digitos", "numero_valido", "cnj_validacao",
                                         "excluido_em", "cadastrado_espaider_em", "cadastrado_espaider_por_id", "pendencias", "andamentos")}
    pk_antes = p.pk
    r = cad.ana.post(_u("processo", pk=p.pk), {**CAMPOS_PROTEGIDOS, "comarca": "Nova Comarca"})
    p = cad.Processo._base_manager.get(pk=pk_antes)
    assert r.status_code in (200, 302) and p.comarca == "Nova Comarca"
    for k, v in antes.items():
        assert getattr(p, k) == v, k
    assert p.origem_campos["comarca"] == "manual" and p.origem_campos.get("comarca") != "pdf"
    assert not cad.Processo._base_manager.filter(pk=99999).exists()


def test_salvar_nao_marca_cadastrado_nem_burla_a_regra_de_pendencias(cad):
    """CAD-12/15: status=CADASTRADO enviado no POST de edição não marca; só o botão (com CONFERIR) marca."""
    p = criar_processo(cad, status="COM_PENDENCIAS", pendencias=["Verificar: Juízo"], juizo="")
    cad.ana.post(_u("processo", pk=p.pk), {"status": "CADASTRADO", "juizo": ""})
    p.refresh_from_db()
    assert p.status == "COM_PENDENCIAS" and p.cadastrado_espaider_em is None


def test_cadastro_manual_ignora_campos_protegidos(cad):
    """CAD-21: criar manual não aceita status/criado_por/criado_via/excluido_*/cnj_validacao do POST."""
    n, d = cnj(4321)
    dados = {**CAMPOS_PROTEGIDOS, "numero": d, "adverso_nome": "Manual", "tribunal": "TJSP", "comarca": "SP", "juizo": "1", "valor_causa": "1,00",
             "distribuido_em": "2022-03-15", "criado_por": str(cad.adm_u.pk), "id": "", "pk": ""}
    cad.ana.post(_u("processo_novo"), dados)
    p = cad.Processo._base_manager.get(numero_digitos=d)
    assert p.criado_por == cad.ana_u and p.criado_via == "manual" and p.status != "CADASTRADO" and p.excluido_em is None
    assert p.cadastrado_espaider_em is None and p.numero_valido is True and p.numero == n


def test_carteira_do_post_nao_aceita_pk_de_carteira_inativa_ou_invalida(cad, mundo):
    """CAD-23: carteira por pk; pk inativo/inexistente/lixo na edição do processo não grava nada estranho nem dá 500."""
    cad.Carteira.objects.filter(pk=cad.carteiras["Volvo"].pk).update(ativa=False)
    for v in (cad.carteiras["Volvo"].pk, 999999, "abc", "-1", "1; DROP TABLE x", "1e9"):
        r = cad.ana.post(_u("processo", pk=mundo.processo.pk), {"carteira": v})
        assert r.status_code < 500, v
    mundo.processo.refresh_from_db()
    assert mundo.processo.carteira_id != cad.carteiras["Volvo"].pk


def test_edicao_concorrente_de_campo_manual_nao_vira_pdf(cad, mundo):
    """CAD-11: edição pela tela vira origem manual mesmo se o POST tentar declarar origem_campos."""
    cad.ana.post(_u("processo", pk=mundo.processo.pk), {"comarca": "X", "origem_campos": '{"comarca": "pdf"}'})
    mundo.processo.refresh_from_db()
    assert mundo.processo.origem_campos["comarca"] == "manual"


# ---------------- método e CSRF ----------------

MUTACOES_PK = ["excluir", "restaurar", "marcar_cadastrado", "desfazer_cadastrado", "consultar_cnj"]
MUTACOES_ITEM = ["tentar_de_novo", "resolver"]
MUTACOES_SEM_PK = ["testar_conexao", "carteira_nova"]


def test_get_nunca_muta(cad, mundo):
    """CAD-15 (mutação só POST): GET em toda rota de ação → 405 e nada muda."""
    antes = (cad.Processo._base_manager.filter(excluido_em__isnull=False).count(), cad.ItemEnvio.objects.filter(status="erro").count(),
             cad.Processo.objects.filter(status="CADASTRADO").count())
    urls = [_u(n, pk=mundo.processo.pk) for n in MUTACOES_PK] + [_u(n, pk=mundo.erro.pk) for n in MUTACOES_ITEM] + [_u(n) for n in MUTACOES_SEM_PK] + \
           [_u("carteira_editar", pk=cad.carteiras["Ativos"].pk)]
    for url in urls:
        assert cad.adm.get(url).status_code == 405, url
    depois = (cad.Processo._base_manager.filter(excluido_em__isnull=False).count(), cad.ItemEnvio.objects.filter(status="erro").count(),
              cad.Processo.objects.filter(status="CADASTRADO").count())
    assert antes == depois


@pytest.mark.parametrize("metodo", ["put", "patch", "delete"])
def test_metodos_nao_declarados_nao_mutam(cad, mundo, metodo):
    """CAD-15: PUT/PATCH/DELETE nas rotas de ação → 405 (sem efeito)."""
    c = getattr(cad.adm, metodo)
    for url in (_u("excluir", pk=mundo.processo.pk), _u("marcar_cadastrado", pk=mundo.processo.pk), _u("processo", pk=mundo.processo.pk)):
        assert c(url).status_code in (405, 403), url
    assert cad.Processo.objects.filter(pk=mundo.processo.pk).exists()


def test_csrf_barra_toda_mutacao_ate_do_adm(cad, mundo):
    """SEG-12: sem token CSRF TODA mutação do Jurídico é recusada (403) e nada acontece — inclusive para o Adm."""
    c = Client(enforce_csrf_checks=True)
    c.force_login(cad.adm_u)
    alvos = [(_u("excluir", pk=mundo.processo.pk), {}), (_u("restaurar", pk=mundo.excluido.pk), {}), (_u("marcar_cadastrado", pk=mundo.processo.pk), {}),
             (_u("desfazer_cadastrado", pk=mundo.processo.pk), {}), (_u("consultar_cnj", pk=mundo.processo.pk), {}),
             (_u("tentar_de_novo", pk=mundo.erro.pk), {}), (_u("resolver", pk=mundo.erro.pk), {}), (_u("testar_conexao"), {}),
             (_u("processo", pk=mundo.processo.pk), {"comarca": "Csrf"}), (_u("processo_novo"), {"numero": cnj(7)[1]}),
             (_u("enviar_cnj"), {"numeros": cnj(7)[0], "carteira": ""}), (_u("carteira_nova"), {"nome": "Csrf", "empresa": "x"}),
             (_u("carteira_editar", pk=cad.carteiras["Ativos"].pk), {"nome": "Csrf"}),
             (_u("config"), {"dify_url": "http://127.0.0.1:1/x", "datajud_url": "http://127.0.0.1:1/y", "dify_usuario": "csrf"})]
    for url, dados in alvos:
        assert c.post(url, dados).status_code == 403, url
    arq = pdf_processo(cnj(7)[0])
    from .conftest import upload
    assert c.post(_u("enviar_pdfs"), {"arquivos": [upload(*arq)]}).status_code == 403
    mundo.processo.refresh_from_db()
    assert mundo.processo.comarca == "São Paulo" and cad.Envio.objects.count() == 2 and not cad.Carteira.objects.filter(nome="Csrf").exists()
    assert cad.Processo._base_manager.get(pk=mundo.excluido.pk).excluido_em is not None


# ---------------- parâmetros hostis em GET ----------------

@pytest.mark.parametrize("q", [{"pagina": "abc"}, {"pagina": "-3"}, {"pagina": "99999999999999999999"}, {"ordem": "'; DROP TABLE x;--"}, {"ordem": "-numero"},
                               {"status": "<script>"}, {"carteira": "abc"}, {"carteira": "-1"}, {"carteira": "9" * 40}, {"cnj": "%00"}, {"q": "%" * 500},
                               {"q": "\x00"}, {"q": "a" * 100_000}, {"p": "abc"}, {"p": "99999999999"}, {"p": "-1"}, {"q": "' OR 1=1 --"}])
def test_parametros_hostis_no_painel_nao_derrubam(cad, mundo, q):
    """CAD-16: filtros/ordem/página/seleção com lixo → nunca 500 (nem vazamento de erro)."""
    r = cad.ana.get(_u("painel"), q)
    assert r.status_code < 500 and "Traceback" not in r.content.decode()


@pytest.mark.parametrize("valor", ["abc", "-1", "0", "99999999999999999999", "1 OR 1=1", "%00", ""])
def test_status_e_erros_com_parametros_hostis(cad, mundo, valor):
    """CAD-23 (8b): ?envio= e ?resolvido= com lixo → 4xx limpo, nunca 500."""
    assert cad.ana.get(_u("status"), {"envio": valor}).status_code < 500
    assert cad.adm.get(_u("erros"), {"resolvido": valor, "pagina": valor}).status_code < 500
    assert cad.adm.get(_u("envios"), {"pagina": valor}).status_code < 500


@pytest.mark.parametrize("rota", ["processo", "envio", "pdf", "excluir", "marcar_cadastrado", "tentar_de_novo", "resolver", "consultar_cnj", "restaurar"])
def test_pk_inexistente_da_404_sem_500(cad, rota):
    """CAD-01: pk inexistente em qualquer rota → 404 (GET ou POST conforme a rota)."""
    url = _u(rota, pk=987654)
    r = cad.adm.get(url) if rota in ("processo", "envio", "pdf") else cad.adm.post(url)
    assert r.status_code == 404
