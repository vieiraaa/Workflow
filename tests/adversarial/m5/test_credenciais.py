"""Adversarial M5: cofre de credenciais (CRD-01/02, SEG-18, MV2-18 C1–C4, C9). Só dados fictícios, servidor local."""

import json
import logging

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m5")]

SEGREDO = "SEGREDO-CRED-ADV-7c41f9"
NOVO = "SEGREDO-CRED-NOVO-b83d02"


@pytest.fixture
def cadeia_cred(h, liberado):
    """gatilho → HTTP /reflete (usa a credencial `nome`) — o servidor devolve o Authorization no corpo E num header."""

    def _g(nome="Digisac", rota="/reflete", **extra):
        return h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}{rota}", credencial=nome, **extra), x=1, titulo="HTTP"))

    return _g


@pytest.fixture
def reflete(servidor):
    def _r(req):
        auth = req["headers"].get("authorization", "")
        return 200, {"auth": auth, "hdrs": req["headers"], "path": req["path"]}, {"X-Eco-Auth": auth}

    servidor.rotas["/reflete"] = _r
    return servidor


def _tudo_gravado(e, fluxo=None):
    from django.apps import apps
    partes = [e.erro_resumo, json.dumps(e.grafo_snapshot, default=str)]
    for n in apps.get_model("execucoes", "ExecucaoNo").objects.filter(execucao=e):
        partes += [n.erro_mensagem or "", json.dumps([n.entrada, n.saida, n.requisicoes, n.logs], default=str)]
    if fluxo is not None:
        fluxo.refresh_from_db()
        partes.append(json.dumps(fluxo.grafo))
    return "\n".join(partes)


def _htmls(clientes, e):
    saida = []
    for c in clientes:
        for url in (reverse("execucoes:detalhe", kwargs={"pk": e.pk}), reverse("execucoes:lista"), reverse("inicio")):
            saida.append(c.get(url).content.decode())
    return "\n".join(saida)


# ---------------- vazamento do valor por qualquer caminho ----------------

def test_valor_da_credencial_nao_vaza_em_nenhum_lugar(cliente_adm, cliente_coordenador, criar_cred, executar, cadeia_cred, reflete, no,
                                                      caplog, imp, fabrica_fluxo, h, modelos):
    """SEG-18/CRD-02/C4: o servidor devolve o Authorization no corpo e num header. O valor não fica em claro em: saída, entrada,
    requisicoes[].resposta (headers e corpo), snapshot, erro, logs (caplog), detalhe/lista/Home, export nativo e export n8n."""
    criar_cred(valor=SEGREDO)
    with caplog.at_level(logging.DEBUG):
        _, e, f = executar(cliente_adm, cadeia_cred())
    assert e.status == "sucesso"
    assert reflete.requisicoes[-1]["headers"]["authorization"] == f"Bearer {SEGREDO}"  # o servidor recebeu o valor real
    assert SEGREDO not in _tudo_gravado(e, f)
    assert SEGREDO not in caplog.text
    assert SEGREDO not in _htmls([cliente_adm, cliente_coordenador], e)
    assert SEGREDO not in imp.exportar(cliente_adm, f).content.decode()
    assert SEGREDO not in cliente_adm.get(reverse("fluxos:exportar_n8n", kwargs={"pk": f.pk})).content.decode()
    # telas do cofre
    from django.apps import apps
    c = apps.get_model("credenciais", "Credencial").objects.get()
    assert SEGREDO not in cliente_adm.get(reverse("credenciais:lista")).content.decode()
    assert SEGREDO not in cliente_adm.get(reverse("credenciais:editar", kwargs={"pk": c.pk})).content.decode()


def test_valor_nao_vaza_em_erro_http_4xx_e_na_mensagem(cliente_adm, criar_cred, executar, cadeia_cred, servidor, no):
    """SEG-18/MV2-22: com erro HTTP 4xx cujo corpo repete o token, a resposta gravada e o detalhe saem mascarados."""
    criar_cred(valor=SEGREDO)
    servidor.rotas["/eco401"] = lambda req: (401, {"erro": "token inválido", "recebido": req["headers"].get("authorization")}, None)
    _, e, f = executar(cliente_adm, cadeia_cred(rota="/eco401"))
    assert no(e, "h").status == "erro" and no(e, "h").erro_categoria == "http_4xx"
    assert SEGREDO not in _tudo_gravado(e, f) and SEGREDO not in _htmls([cliente_adm], e)


def test_valor_nao_vaza_no_log_do_codigo(cliente_adm, criar_cred, executar, h, liberado, reflete, no):
    """SEG-18: um Código depois do HTTP que loga os itens recebidos (que refletiram a credencial) não grava o valor em `logs`."""
    criar_cred(valor=SEGREDO)
    g = h.cadeia2(h.no2("h", "http", h.cfg_http2(f"{liberado.base}/reflete", credencial="Digisac"), x=1, titulo="HTTP"),
                  h.no2("cod", "codigo", {"modo": "uma_vez_para_todos", "codigo": "console.log(JSON.stringify($input.all())); return $input.all();"}, x=2, titulo="Cod"))
    _, e, f = executar(cliente_adm, g)
    assert e.status == "sucesso"
    assert SEGREDO not in _tudo_gravado(e, f)


def test_valor_nao_vaza_na_previa_nem_em_executar_no(cliente_adm, criar_cred, fabrica_fluxo, cadeia_cred, reflete, modelos, no):
    """SEG-18/MV2-23: executar_no (teste) e a prévia de expressão sobre a resposta refletida não revelam o valor."""
    criar_cred(valor=SEGREDO)
    f = fabrica_fluxo(grafo=cadeia_cred(), status="rascunho")
    r = cliente_adm.post(reverse("fluxos:executar_no", kwargs={"pk": f.pk}), {"no_id": "h"}, HTTP_ACCEPT="application/json")
    assert r.status_code == 200
    e = modelos.Execucao.objects.get(teste=True)
    assert SEGREDO not in _tudo_gravado(e, f) and SEGREDO not in _htmls([cliente_adm], e)
    for expr in ("{{ $('HTTP').first().json.auth }}", "{{ $('HTTP').first().json }}", "{{ JSON.stringify($('HTTP').first().json) }}",
                 "{{ $('HTTP').first().json.hdrs.authorization }}", "{{ $json.auth }}"):
        pr = cliente_adm.post(reverse("fluxos:previa_expressao", kwargs={"pk": f.pk}),
                              json.dumps({"no_id": "h", "campo": "x", "expressao": expr}), content_type="application/json")
        assert SEGREDO not in pr.content.decode(), expr


def test_chave_ausente_ou_trocada_da_erro_sem_500_e_sem_revelar_valor_nem_chave(cliente_adm, criar_cred, executar, cadeia_cred, reflete, settings, no):
    """MV2-18 C2: sem chave / chave diferente → erro `credencial` mencionando "chave"; nunca 500; nenhuma requisição sai; nem o valor
    nem a chave aparecem na mensagem."""
    from cryptography.fernet import Fernet
    criar_cred(valor=SEGREDO)
    chave_original = settings.CREDENCIAIS_CHAVE
    for chave in ("", Fernet.generate_key().decode()):
        settings.CREDENCIAIS_CHAVE = chave
        antes = len(reflete.requisicoes)
        _, e, f = executar(cliente_adm, cadeia_cred())
        n = no(e, "h")
        assert n.status == "erro" and n.erro_categoria == "credencial" and "chave" in n.erro_mensagem.lower()
        assert len(reflete.requisicoes) == antes
        bruto = _tudo_gravado(e, f) + _htmls([cliente_adm], e)
        assert SEGREDO not in bruto and chave_original not in bruto and (not chave or chave not in bruto)


# ---------------- IDOR / escopo ----------------

def test_credencial_de_outro_setor_nao_resolve_por_nome(logar, setor_a, setor_b, criar_cred, fluxo_no_setor, cadeia_cred, reflete, modelos, no):
    """CRD-02/MV2-18: credencial do setor B usada por fluxo do setor A (por NOME) → erro `credencial`; nenhuma requisição sai."""
    criar_cred(nome="Do B", valor=SEGREDO, setor=setor_b.pk)
    coord_a, _ = logar("Coordenador", setor_a)
    f = fluxo_no_setor(setor_a, grafo=cadeia_cred(nome="Do B"), status="rascunho")
    coord_a.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
    e = modelos.Execucao.objects.get(fluxo=f)
    assert no(e, "h").status == "erro" and no(e, "h").erro_categoria == "credencial"
    assert reflete.requisicoes == [] and SEGREDO not in _tudo_gravado(e, f)


def test_credencial_global_e_a_do_proprio_setor_funcionam_mas_nao_a_de_outro(logar, setor_a, setor_b, criar_cred, fluxo_no_setor, cadeia_cred, reflete, modelos, no):
    """CRD-01/02 (controle): global (setor nulo) e do próprio setor resolvem."""
    criar_cred(nome="Global", valor="G" * 12)
    criar_cred(nome="Do A", valor="A" * 12, setor=setor_a.pk)
    coord_a, _ = logar("Coordenador", setor_a)
    for nome in ("Global", "Do A"):
        f = fluxo_no_setor(setor_a, grafo=cadeia_cred(nome=nome), status="rascunho")
        coord_a.post(reverse("fluxos:executar", kwargs={"pk": f.pk}))
        assert no(modelos.Execucao.objects.get(fluxo=f), "h").status == "sucesso", nome


@pytest.mark.parametrize("nome", ["digisac", "DIGISAC", "Digisac ", " Digisac", "Digisac​", "Digi%sac", "Digisac' OR '1'='1",
                                   "Dígisac", "Digisac;--"])
def test_nome_parecido_nao_resolve_outra_credencial_nem_derruba(nome, cliente_adm, criar_cred, executar, cadeia_cred, reflete, no):
    """CRD-02: variações do nome (caixa, espaço, zero-width, NUL, aspas) nunca resolvem OUTRA credencial por acaso nem dão 500.
    Caixa/espaço nas pontas podem resolver a MESMA (o nome é único sem diferenciar maiúsculas, C3); o resto = erro `credencial`."""
    criar_cred(valor=SEGREDO)
    _, e, f = executar(cliente_adm, cadeia_cred(nome=nome))
    assert e is not None
    n = no(e, "h")
    if nome.strip().lower() == "digisac":  # caixa/espaços nas pontas normalizam para a MESMA credencial (nunca outra)
        assert n.status in ("sucesso", "erro")
    else:
        assert n.status == "erro" and n.erro_categoria == "credencial", (n.status, n.erro_categoria)
        assert reflete.requisicoes == []
    assert SEGREDO not in _tudo_gravado(e, f)


@pytest.mark.parametrize("quem", ["cliente_coordenador", "cliente_base", "cliente_anonimo"])
def test_nao_adm_nao_le_nao_cria_nao_edita_nem_exclui_e_nao_vaza_nada(quem, request, criar_cred, Credencial):
    """CRD-01/MV2-18 C3: Coordenador/Base/anônimo: nenhuma tela do cofre, nenhuma mutação, e a resposta nunca contém o valor/nome."""
    criar_cred(nome="Segredo Interno", valor=SEGREDO)
    c = request.getfixturevalue(quem)
    cred = Credencial.objects.get()
    dados = {"nome": "Invasor", "tipo": "bearer", "valor": "x" * 10, "setor": ""}
    respostas = [c.get(reverse("credenciais:lista")), c.get(reverse("credenciais:nova")),
                 c.get(reverse("credenciais:editar", kwargs={"pk": cred.pk})),
                 c.post(reverse("credenciais:nova"), dados),
                 c.post(reverse("credenciais:editar", kwargs={"pk": cred.pk}), {**dados, "nome": "Mudado"}),
                 c.post(reverse("credenciais:excluir", kwargs={"pk": cred.pk}))]
    for r in respostas:
        assert r.status_code in (302, 403), r.status_code
        corpo = r.content.decode()
        assert SEGREDO not in corpo and "Segredo Interno" not in corpo
    assert Credencial.objects.count() == 1 and Credencial.objects.get().nome == "Segredo Interno"


def test_csrf_e_obrigatorio_em_criar_editar_excluir(usuario_adm, criar_cred, Credencial):
    """MV2-18 C3/SEG-12: POST sem token CSRF (cliente que o exige) → 403 e nada muda."""
    criar_cred(valor=SEGREDO)
    cred = Credencial.objects.get()
    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_adm)
    dados = {"nome": "Sem Token", "tipo": "bearer", "valor": "y" * 10, "setor": ""}
    assert c.post(reverse("credenciais:nova"), dados).status_code == 403
    assert c.post(reverse("credenciais:editar", kwargs={"pk": cred.pk}), {**dados, "nome": "Mudado"}).status_code == 403
    assert c.post(reverse("credenciais:excluir", kwargs={"pk": cred.pk})).status_code == 403
    assert Credencial.objects.count() == 1 and Credencial.objects.get().nome == "Digisac"


# ---------------- troca de valor, formulários hostis ----------------

def test_trocar_valor_nao_revela_o_antigo_e_vazio_mantem(cliente_adm, criar_cred, Credencial, executar, cadeia_cred, reflete):
    """CRD-01/C3: editar com valor vazio mantém o atual (o servidor segue recebendo o antigo); com valor novo passa a enviar o novo;
    em nenhum caso a resposta ou a tela de edição mostram o antigo/novo."""
    criar_cred(valor=SEGREDO)
    cred = Credencial.objects.get()
    url = reverse("credenciais:editar", kwargs={"pk": cred.pk})
    r = cliente_adm.post(url, {"nome": "Digisac", "tipo": "bearer", "valor": "", "setor": ""}, follow=True)
    assert SEGREDO not in r.content.decode()
    executar(cliente_adm, cadeia_cred())
    assert reflete.requisicoes[-1]["headers"]["authorization"] == f"Bearer {SEGREDO}"
    r = cliente_adm.post(url, {"nome": "Digisac", "tipo": "bearer", "valor": NOVO, "setor": ""}, follow=True)
    corpo = r.content.decode() + cliente_adm.get(url).content.decode() + cliente_adm.get(reverse("credenciais:lista")).content.decode()
    assert SEGREDO not in corpo and NOVO not in corpo
    executar(cliente_adm, cadeia_cred())
    assert reflete.requisicoes[-1]["headers"]["authorization"] == f"Bearer {NOVO}"


def test_erro_de_validacao_do_formulario_nao_reexibe_o_valor_digitado(cliente_adm):
    """SEG-18: erro de validação (nome vazio) não devolve o valor digitado no HTML re-renderizado."""
    r = cliente_adm.post(reverse("credenciais:nova"), {"nome": "", "tipo": "bearer", "valor": SEGREDO, "setor": ""})
    assert r.status_code == 200 and SEGREDO not in r.content.decode()


@pytest.mark.parametrize("campos", [
    {"tipo": "header", "header_nome": "X-A\r\nX-Evil: 1", "valor": "v" * 8},
    {"tipo": "header", "header_nome": "X A", "valor": "v" * 8},
    {"tipo": "header", "header_nome": "", "valor": "v" * 8},
    {"tipo": "basic", "usuario": "", "valor": "v" * 8},
    {"tipo": "bearer", "valor": "abc\r\nX-Evil: 1"},
    {"tipo": "bearer", "valor": "\x00" * 8},
    {"tipo": "smtp", "valor": "v" * 8, "host": "h\r\nX: 1", "porta": "99999999"},
    {"tipo": "bearer", "valor": "v" * 8, "setor": "999999"},
    {"tipo": "bearer", "valor": "v" * 8, "setor": "abc"},
    {"tipo": "../../etc", "valor": "v" * 8},
])
def test_formulario_hostil_nao_da_500_e_nao_injeta_header(campos, cliente_adm, Credencial, executar, cadeia_cred, reflete):
    """MV2-18 C3: campos hostis (CRLF em nome/valor de header, tipo/setor inválidos, NUL) → erro de campo (200) ou salvo; nunca 500, e
    uma credencial salva nunca faz o servidor receber header extra injetado."""
    dados = {"nome": "Hostil", "tipo": "bearer", "valor": "v" * 8, "setor": "", **campos}
    r = cliente_adm.post(reverse("credenciais:nova"), dados)
    assert r.status_code in (200, 302)
    if Credencial.objects.filter(nome="Hostil").exists():
        executar(cliente_adm, cadeia_cred(nome="Hostil"))
        for req in reflete.requisicoes:
            assert "x-evil" not in req["headers"], req["headers"]


@pytest.mark.parametrize("nome", ["<script>window.__pwn=1</script>", '"><img src=x onerror=1>', "a" * 81, "n\x00ome", "‮rtl", ""])
def test_nome_hostil_da_credencial_e_escapado_ou_recusado(nome, cliente_adm, Credencial):
    """MV2-18 C3: nome com HTML é escapado nas telas; > 80 caracteres/vazio/NUL recusados; nunca 500."""
    r = cliente_adm.post(reverse("credenciais:nova"), {"nome": nome, "tipo": "bearer", "valor": "v" * 8, "setor": ""}, follow=True)
    assert r.status_code == 200
    for url in (reverse("credenciais:lista"),):
        assert "<script>window.__pwn=1</script>" not in cliente_adm.get(url).content.decode()
        assert '"><img src=x onerror=1>' not in cliente_adm.get(url).content.decode()
    if len(nome) > 80 or nome == "":
        assert not Credencial.objects.exists()


def test_nome_unico_sem_diferenciar_caixa_e_excluir_so_por_post(cliente_adm, criar_cred, Credencial):
    """MV2-18 C3: 'digisac' duplica 'Digisac' (recusado com mensagem); excluir por GET = 405."""
    criar_cred(nome="Digisac")
    r = criar_cred(nome="digisac")
    assert r.status_code == 200 and "Já existe uma credencial com este nome." in r.content.decode()
    assert Credencial.objects.count() == 1
    assert cliente_adm.get(reverse("credenciais:excluir", kwargs={"pk": Credencial.objects.get().pk})).status_code == 405


def test_excluir_credencial_em_uso_nao_vaza_e_o_no_passa_a_dar_erro(cliente_adm, criar_cred, Credencial, executar, cadeia_cred, reflete, no):
    """CRD-02: após excluir a credencial, o nó que a usava dá erro `credencial` (não envia sem autenticação silenciosamente)."""
    criar_cred(valor=SEGREDO)
    cliente_adm.post(reverse("credenciais:excluir", kwargs={"pk": Credencial.objects.get().pk}))
    _, e, f = executar(cliente_adm, cadeia_cred())
    assert no(e, "h").erro_categoria == "credencial" and reflete.requisicoes == []
