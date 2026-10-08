"""Adversarial M1: IDOR, escalada, auto-proteção, CSRF, XSS, entrada inválida, sessão, login."""
import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m1")]

U = get_user_model()
XSS = ['<script>alert(1)</script>', '"><img src=x onerror=alert(1)>', "'><svg/onload=alert(1)>",
       "</title><script>alert(1)</script>"]


def _h(r):
    return r.content.decode()


def _editar(pk):
    return reverse("contas:usuario_editar", kwargs={"pk": pk})


def _redef(pk):
    return reverse("contas:usuario_redefinir_senha", kwargs={"pk": pk})


def _papeis(u):
    return sorted(u.groups.values_list("name", flat=True))


# ---------- IDOR e escalada ----------

@pytest.mark.parametrize("cliente", ["cliente_coordenador", "cliente_base", "cliente_anonimo", "cliente_sem_papel"])
@pytest.mark.parametrize("metodo", ["get", "post"])
def test_nao_adm_em_todas_as_rotas_de_usuarios(request, cliente, metodo, usuario_base, dados_usuario):
    """PRM-01/02: nenhuma rota de usuários responde 200/redireciona-sucesso a quem não é Adm; nada muda."""
    c = request.getfixturevalue(cliente)
    antes = U.objects.count()
    rotas = [reverse("contas:usuarios"), reverse("contas:usuario_novo"), _editar(usuario_base.pk),
             _redef(usuario_base.pk)]
    for url in rotas:
        r = getattr(c, metodo)(url, dados_usuario(email="atk@exemplo.test", papel="adm") if metodo == "post" else {})
        if cliente == "cliente_anonimo":
            assert r.status_code == 302 and reverse("login") in r.url, url
        else:
            assert r.status_code in (403, 405), (url, r.status_code)
    assert U.objects.count() == antes
    assert not U.objects.filter(email="atk@exemplo.test").exists()


def test_base_forja_post_para_virar_adm(cliente_base, usuario_base, dados_usuario):
    """Escalada: Base posta na própria edição com papel=adm e is_superuser/is_staff/groups."""
    d = dados_usuario(nome=usuario_base.nome, email=usuario_base.email, papel="adm", com_senha=False)
    d.update({"is_superuser": "on", "is_staff": "on", "groups": [Group.objects.get(name="Adm").pk]})
    r = cliente_base.post(_editar(usuario_base.pk), d)
    assert r.status_code in (403, 405)
    usuario_base.refresh_from_db()
    assert _papeis(usuario_base) == ["Base"]
    assert not usuario_base.is_superuser and not usuario_base.is_staff


def test_base_redefine_senha_do_adm(cliente_base, fabrica_usuario):
    """IDOR: Base tenta redefinir a senha do Adm."""
    usuario_adm = fabrica_usuario(papel="Adm")
    senha_padrao = "Senha-Forte-Ficticia-91"
    r = cliente_base.post(_redef(usuario_adm.pk), {"nova_senha": "Invasora-Forte-88", "confirmacao": "Invasora-Forte-88"})
    assert r.status_code == 403
    usuario_adm.refresh_from_db()
    assert usuario_adm.check_password(senha_padrao)


def test_adm_nao_altera_campos_nao_editaveis(cliente_adm, fabrica_usuario, dados_usuario):
    """Mass assignment: is_superuser/is_staff/groups/password/last_login/date_joined no POST são ignorados."""
    alvo = fabrica_usuario(papel="Base")
    hash_antes = alvo.password
    d = dados_usuario(nome=alvo.nome, email=alvo.email, papel="base", com_senha=False)
    d.update({"is_superuser": "on", "is_staff": "on", "password": "pbkdf2_sha256$1$x$y",
              "groups": [Group.objects.get(name="Adm").pk], "date_joined": "2000-01-01 00:00:00",
              "criado_em": "2000-01-01 00:00:00", "user_permissions": "1", "id": "99999", "pk": "99999"})
    cliente_adm.post(_editar(alvo.pk), d)
    alvo.refresh_from_db()
    assert not alvo.is_superuser and not alvo.is_staff
    assert alvo.password == hash_antes
    assert _papeis(alvo) == ["Base"]
    assert alvo.pk != 99999


def test_adm_criar_nao_aceita_superuser(cliente_adm, dados_usuario):
    """Mass assignment na criação."""
    d = dados_usuario(email="mass@exemplo.test", papel="base")
    d.update({"is_superuser": "on", "is_staff": "on", "groups": [Group.objects.get(name="Adm").pk]})
    cliente_adm.post(reverse("contas:usuario_novo"), d)
    u = U.objects.get(email="mass@exemplo.test")
    assert not u.is_superuser and not u.is_staff and _papeis(u) == ["Base"]


def test_usuario_tem_exatamente_um_papel_apos_edicoes(cliente_adm, fabrica_usuario, dados_usuario):
    """PAP-02: editar papel várias vezes não acumula grupos."""
    alvo = fabrica_usuario(papel="Base")
    for papel in ("coordenador", "adm", "base"):
        cliente_adm.post(_editar(alvo.pk), dados_usuario(nome=alvo.nome, email=alvo.email, papel=papel, com_senha=False))
    assert _papeis(alvo) == ["Base"]


def test_admin_django_fechado_para_papeis(cliente_adm, cliente_coordenador, cliente_base):
    """PAP-03: /admin/ restrito a is_staff; Adm do produto sem is_staff não entra."""
    for c in (cliente_adm, cliente_coordenador, cliente_base):
        r = c.get("/admin/")
        assert r.status_code in (302, 403, 404)
        if r.status_code == 302:
            assert "/admin/login" in r.url or reverse("login") in r.url


# ---------- auto-proteção ----------

def test_unico_adm_nao_se_rebaixa_nem_desativa_por_nenhuma_rota(cliente_adm, usuario_adm, dados_usuario):
    """USR-07/08: todas as combinações de auto-sabotagem via editar são recusadas."""
    for papel, ativo in (("coordenador", True), ("base", True), ("adm", False), ("base", False)):
        r = cliente_adm.post(_editar(usuario_adm.pk), dados_usuario(
            nome=usuario_adm.nome, email=usuario_adm.email, papel=papel, ativo=ativo, com_senha=False))
        assert r.status_code == 200, (papel, ativo)
        usuario_adm.refresh_from_db()
        assert usuario_adm.is_active and _papeis(usuario_adm) == ["Adm"]


def test_dois_adm_se_rebaixando_em_sequencia_nunca_zeram(usuario_adm, fabrica_usuario, dados_usuario):
    """USR-08: A rebaixa B; depois B (já Coordenador) não consegue mais agir; sempre sobra 1 Adm ativo."""
    b = fabrica_usuario(papel="Adm")
    ca, cb = Client(), Client()
    ca.force_login(usuario_adm)
    cb.force_login(b)
    ra = ca.post(_editar(b.pk), dados_usuario(nome=b.nome, email=b.email, papel="coordenador", com_senha=False))
    rb = cb.post(_editar(usuario_adm.pk), dados_usuario(
        nome=usuario_adm.nome, email=usuario_adm.email, papel="coordenador", com_senha=False))
    assert ra.status_code == 302
    assert rb.status_code == 403
    assert U.objects.filter(is_active=True, groups__name="Adm").count() == 1


def test_adm_nao_zera_adm_ativo_desativando_o_outro_e_depois_si(usuario_adm, fabrica_usuario, dados_usuario):
    """USR-08: desativar o outro Adm é ok; desativar-se em seguida é recusado."""
    b = fabrica_usuario(papel="Adm")
    c = Client()
    c.force_login(usuario_adm)
    c.post(_editar(b.pk), dados_usuario(nome=b.nome, email=b.email, papel="adm", ativo=False, com_senha=False))
    r = c.post(_editar(usuario_adm.pk), dados_usuario(
        nome=usuario_adm.nome, email=usuario_adm.email, papel="adm", ativo=False, com_senha=False))
    assert r.status_code == 200
    assert U.objects.filter(is_active=True, groups__name="Adm").exists()


def test_nao_ha_rota_de_exclusao_por_metodos(cliente_adm, usuario_base):
    """USR-09: DELETE/PUT/PATCH em editar não apagam."""
    for m in ("delete", "put", "patch"):
        r = getattr(cliente_adm, m)(_editar(usuario_base.pk))
        assert r.status_code in (403, 405, 400)
    assert U.objects.filter(pk=usuario_base.pk).exists()


# ---------- CSRF ----------

def _csrf_client(u):
    c = Client(enforce_csrf_checks=True)
    c.force_login(u)
    return c


def test_todo_post_do_m1_exige_csrf(usuario_adm, usuario_base, dados_usuario):
    """SEG-12/PRM-08: POST sem token em todas as rotas de mutação do M1 → 403, nada muda."""
    c = _csrf_client(usuario_adm)
    n = U.objects.count()
    alvo_nome = usuario_base.nome
    assert c.post(reverse("contas:usuario_novo"), dados_usuario(email="csrf@exemplo.test")).status_code == 403
    assert c.post(_editar(usuario_base.pk), dados_usuario(nome="Hackeado", email=usuario_base.email,
                                                           com_senha=False)).status_code == 403
    assert c.post(_redef(usuario_base.pk), {"nova_senha": "Invasora-Forte-88",
                                              "confirmacao": "Invasora-Forte-88"}).status_code == 403
    assert c.post(reverse("contas:trocar_senha"), {"senha_atual": "x", "nova_senha": "y", "confirmacao": "y"}).status_code == 403
    assert c.post(reverse("logout")).status_code == 403
    usuario_base.refresh_from_db()
    assert usuario_base.nome == alvo_nome and U.objects.count() == n


def test_login_sem_csrf(fabrica_usuario, senha_padrao):
    """SEG-12: POST de login sem token CSRF é recusado."""
    u = fabrica_usuario()
    c = Client(enforce_csrf_checks=True)
    r = c.post(reverse("login"), {"username": u.email, "password": senha_padrao})
    assert r.status_code == 403
    assert "_auth_user_id" not in c.session


def test_csrf_token_invalido(usuario_adm, dados_usuario):
    """SEG-12: token CSRF forjado é recusado."""
    c = _csrf_client(usuario_adm)
    d = dados_usuario(email="csrf2@exemplo.test")
    d["csrfmiddlewaretoken"] = "x" * 64
    assert c.post(reverse("contas:usuario_novo"), d).status_code == 403


def test_cabecalhos_de_seguranca(cliente_adm):
    """SEG-12: X-Frame-Options DENY e nosniff."""
    r = cliente_adm.get(reverse("contas:usuarios"))
    assert r.headers.get("X-Frame-Options", "").upper() == "DENY"
    assert r.headers.get("X-Content-Type-Options", "").lower() == "nosniff"


# ---------- XSS ----------

@pytest.mark.parametrize("payload", XSS)
def test_xss_nome_em_lista_edicao_menu_e_titulo(cliente_adm, fabrica_usuario, payload):
    """USR-12/SEG-13: nome malicioso escapado na lista, edição e no shell do próprio usuário."""
    u = fabrica_usuario(papel="Adm", nome=payload)
    c = Client()
    c.force_login(u)
    for url in (reverse("contas:usuarios"), _editar(u.pk), reverse("contas:trocar_senha")):
        h = _h(c.get(url))
        assert payload not in h, url
    h = _h(cliente_adm.get(reverse("contas:usuarios")))
    assert payload not in h


@pytest.mark.parametrize("payload", XSS)
def test_xss_nome_no_toast_de_criacao_e_redefinicao(cliente_adm, dados_usuario, payload):
    """USR-12/SEG-13: toasts 'Usuário <nome> criado.' e 'Senha de <nome> redefinida.' escapam."""
    r = cliente_adm.post(reverse("contas:usuario_novo"),
                         dados_usuario(nome=payload, email="xss1@exemplo.test"), follow=True)
    assert payload not in _h(r)
    u = U.objects.get(email="xss1@exemplo.test")
    r = cliente_adm.post(_redef(u.pk), {"nova_senha": "Redefinida-Forte-31", "confirmacao": "Redefinida-Forte-31"},
                         follow=True)
    assert payload not in _h(r)


@pytest.mark.parametrize("payload", XSS)
def test_xss_em_busca_refletida(cliente_adm, payload):
    """SEG-13: ?q= refletido no campo de busca/estado vazio é escapado."""
    assert payload not in _h(cliente_adm.get(reverse("contas:usuarios"), {"q": payload}))


@pytest.mark.parametrize("payload", XSS)
def test_xss_em_valores_de_formulario_reexibidos(cliente_adm, dados_usuario, payload):
    """SEG-13: valores re-renderizados após erro de validação são escapados."""
    r = cliente_adm.post(reverse("contas:usuario_novo"),
                         dados_usuario(nome=payload, email=payload, confirmacao="diferente-diferente"))
    assert r.status_code == 200
    assert payload not in _h(r)


def test_xss_no_email_exibido(cliente_adm, fabrica_usuario):
    """USR-12: e-mail com aspas/HTML (se aceito) é escapado."""
    try:
        u = fabrica_usuario(email='a"><script>alert(1)</script>@exemplo.test')
    except Exception:
        pytest.skip("modelo recusa o e-mail na criação direta")
    assert "<script>alert(1)" not in _h(cliente_adm.get(reverse("contas:usuarios")))
    assert "<script>alert(1)" not in _h(cliente_adm.get(_editar(u.pk)))


# ---------- entrada inválida ----------

def test_email_enorme_nao_da_500(cliente_adm, dados_usuario):
    """Entrada: e-mail de 5 KB recusado sem 500."""
    r = cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(email="a" * 5000 + "@exemplo.test"))
    assert r.status_code == 200
    assert not U.objects.filter(email__startswith="aaaa").exists()


def test_nome_10kb_nao_da_500(cliente_adm, dados_usuario):
    """Entrada/modelo (max 120): nome de 10 KB recusado."""
    r = cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(nome="n" * 10240, email="big@exemplo.test"))
    assert r.status_code == 200
    assert not U.objects.filter(email="big@exemplo.test").exists()


@pytest.mark.parametrize("nome", ["Zero​Width", "Mária", "テスト用户", "😀 Emoji", "a\x00b", "  \t  "])
def test_unicode_e_controle_no_nome_nunca_500(cliente_adm, dados_usuario, nome):
    """Entrada: unicode/zero-width/NUL/espaços no nome nunca causam 500."""
    r = cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(nome=nome, email="uni@exemplo.test"))
    assert r.status_code in (200, 302)
    if not nome.strip():
        assert not U.objects.filter(email="uni@exemplo.test").exists()


def test_email_duplicado_com_zero_width_ou_unicode_equivalente(cliente_adm, usuario_base, dados_usuario):
    """USR-05: e-mail com espaços/maiúsculas ao redor ainda é duplicado."""
    n = U.objects.count()
    r = cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(email=f"  {usuario_base.email.upper()}  "))
    assert r.status_code == 200 and U.objects.count() == n


@pytest.mark.parametrize("papel", ["root", "ADM", "Adm", "adm,base", "../adm", "", "0", "-1", "adm\x00"])
def test_papel_invalido(cliente_adm, dados_usuario, papel):
    """USR-14: qualquer valor fora de adm|coordenador|base é recusado."""
    r = cliente_adm.post(reverse("contas:usuario_novo"), dados_usuario(email="pp@exemplo.test", papel=papel))
    assert r.status_code == 200
    assert not U.objects.filter(email="pp@exemplo.test").exists()


def test_papel_multivalorado_nao_da_dois_grupos(cliente_adm, dados_usuario):
    """PAP-02: papel repetido no POST nunca vira mais de um grupo."""
    d = dados_usuario(email="multi@exemplo.test")
    d["papel"] = ["adm", "base"]
    cliente_adm.post(reverse("contas:usuario_novo"), d)
    u = U.objects.filter(email="multi@exemplo.test").first()
    assert u is None or len(_papeis(u)) == 1


@pytest.mark.parametrize("pk", ["abc", "-1", "0", "1.5", "99999999999999999999", "%00", "1 OR 1=1"])
def test_pk_malformado_ou_inexistente(cliente_adm, pk):
    """Entrada: pk não numérico/gigante → 404, nunca 500."""
    for url in (f"/usuarios/{pk}/editar/", f"/usuarios/{pk}/"):
        assert cliente_adm.get(url).status_code in (404, 405)
    for nome in ("contas:usuario_editar", "contas:usuario_redefinir_senha"):
        try:
            url = reverse(nome, kwargs={"pk": pk})
        except Exception:
            continue
        r = cliente_adm.post(url, {}) if "redefinir" in nome else cliente_adm.get(url)
        assert r.status_code == 404, (nome, pk, r.status_code)


@pytest.mark.parametrize("params", [
    {"pagina": "-1"}, {"pagina": "abc"}, {"pagina": "9999"}, {"pagina": "99999999999999999999"}, {"pagina": ["1", "x"]},
    {"ordem": "senha"}, {"ordem": "-password"}, {"ordem": "groups__name"}, {"ordem": "nome,email"},
    {"ordem": "?"}, {"papel": "adm' OR '1'='1"}, {"ativo": "1;DROP"}, {"q": "x" * 10240}, {"q": "\x00"},
    {"q": "%_\\"}, {"q": "'; DROP TABLE contas_usuario;--"},
])
def test_parametros_da_lista_malformados(cliente_adm, params):
    """USR-02/03: filtros/ordem/página/busca hostis nunca dão 500."""
    assert cliente_adm.get(reverse("contas:usuarios"), params).status_code == 200


def test_ordem_nao_vaza_hash_de_senha(cliente_adm, usuario_base):
    """Ordenação por campo sensível é ignorada e o hash nunca é exibido."""
    h = _h(cliente_adm.get(reverse("contas:usuarios"), {"ordem": "password"}))
    assert "pbkdf2" not in h and usuario_base.password not in h
    assert "pbkdf2" not in _h(cliente_adm.get(_editar(usuario_base.pk)))


def test_trocar_senha_corpo_enorme_e_campos_ausentes(cliente_base):
    """Entrada: POST vazio ou com senha de 1 MB não dá 500."""
    assert cliente_base.post(reverse("contas:trocar_senha"), {}).status_code == 200
    r = cliente_base.post(reverse("contas:trocar_senha"),
                          {"senha_atual": "x" * 1_000_000, "nova_senha": "y" * 1_000_000, "confirmacao": "y" * 1_000_000})
    assert r.status_code in (200, 400, 413)


def test_redefinir_senha_campos_ausentes(cliente_adm, fabrica_usuario, senha_padrao):
    """Entrada: POST sem campos re-renderiza (200) e preserva a senha."""
    usuario_base = fabrica_usuario(papel="Base")
    assert cliente_adm.post(_redef(usuario_base.pk), {}).status_code == 200
    usuario_base.refresh_from_db()
    assert usuario_base.check_password(senha_padrao)


# ---------- sessão ----------

def test_desativado_com_sessao_aberta_perde_acesso_em_todas_as_rotas(fabrica_usuario):
    """PAP-04: desativado → 302 para login em qualquer rota protegida e sessão encerrada."""
    u = fabrica_usuario(papel="Adm")
    c = Client()
    c.force_login(u)
    u.is_active = False
    u.save()
    for url in (reverse("contas:usuarios"), reverse("contas:trocar_senha"), reverse("inicio")):
        r = c.get(url)
        assert r.status_code == 302 and reverse("login") in r.url, url
    # PAP-04: a sessão é ENCERRADA; reativar o usuário não pode ressuscitar a sessão antiga.
    u.is_active = True
    u.save()
    r = c.get(reverse("contas:trocar_senha"))
    assert r.status_code == 302 and reverse("login") in r.url


def test_desativado_nao_executa_post_com_sessao_antiga(fabrica_usuario, dados_usuario):
    """PAP-04: desativado com sessão antiga não cria usuário por POST."""
    u = fabrica_usuario(papel="Adm")
    c = Client()
    c.force_login(u)
    u.is_active = False
    u.save()
    r = c.post(reverse("contas:usuario_novo"), dados_usuario(email="fantasma@exemplo.test"))
    assert r.status_code == 302
    assert not U.objects.filter(email="fantasma@exemplo.test").exists()


def test_rebaixado_perde_acesso_imediatamente_em_post(fabrica_usuario, dados_usuario):
    """USR-11: Adm rebaixado não consegue mais POST em usuários (sem cache de papel)."""
    u = fabrica_usuario(papel="Adm")
    c = Client()
    c.force_login(u)
    u.groups.set([Group.objects.get(name="Base")])
    r = c.post(reverse("contas:usuario_novo"), dados_usuario(email="tarde@exemplo.test"))
    assert r.status_code == 403
    assert not U.objects.filter(email="tarde@exemplo.test").exists()


def test_promovido_ganha_acesso_na_proxima_requisicao(fabrica_usuario):
    """USR-11: promoção também vale sem novo login."""
    u = fabrica_usuario(papel="Base")
    c = Client()
    c.force_login(u)
    assert c.get(reverse("contas:usuarios")).status_code == 403
    u.groups.set([Group.objects.get(name="Adm")])
    assert c.get(reverse("contas:usuarios")).status_code == 200


def test_logout_get_nao_encerra_e_post_invalida_sessao_antiga(fabrica_usuario):
    """SEG-15: GET → 405; depois do POST, o cookie de sessão antigo não vale mais."""
    u = fabrica_usuario()
    c = Client()
    c.force_login(u)
    assert c.get(reverse("logout")).status_code == 405
    assert c.get(reverse("contas:trocar_senha")).status_code == 200
    cookie = c.cookies["sessionid"].value
    c.post(reverse("logout"))
    c2 = Client()
    c2.cookies["sessionid"] = cookie
    r = c2.get(reverse("contas:trocar_senha"))
    assert r.status_code == 302 and reverse("login") in r.url


def test_redefinicao_de_senha_invalida_sessao_do_alvo(cliente_adm, fabrica_usuario):
    """Sessão: após o Adm redefinir a senha, a sessão antiga do alvo deixa de valer (hash da sessão)."""
    alvo = fabrica_usuario(papel="Coordenador")
    c = Client()
    c.force_login(alvo)
    assert c.get(reverse("contas:trocar_senha")).status_code == 200
    cliente_adm.post(_redef(alvo.pk), {"nova_senha": "Redefinida-Forte-31", "confirmacao": "Redefinida-Forte-31"})
    r = c.get(reverse("contas:trocar_senha"))
    assert r.status_code == 302 and reverse("login") in r.url


def test_cookies_de_sessao_httponly(client, fabrica_usuario, senha_padrao):
    """SEG-12: cookie de sessão HttpOnly."""
    u = fabrica_usuario()
    client.post(reverse("login"), {"username": u.email, "password": senha_padrao})
    assert client.cookies["sessionid"]["httponly"]


# ---------- login ----------

def test_enumeracao_de_email_mesma_resposta(client, fabrica_usuario):
    """SEG-15: e-mail existente (senha errada), inexistente e inativo → mesmo status e mesma mensagem."""
    ativo = fabrica_usuario()
    inativo = fabrica_usuario(ativo=False)
    respostas = []
    for email in (ativo.email, "naoexiste@exemplo.test", inativo.email):
        r = Client().post(reverse("login"), {"username": email, "password": "errada-errada-123"})
        respostas.append((r.status_code, "E-mail ou senha inválidos." in _h(r)))
    assert len(set(respostas)) == 1 and respostas[0] == (200, True)


def test_inativo_com_senha_correta_mesma_mensagem(fabrica_usuario, senha_padrao):
    """SEG-15/PAP-04: inativo com senha certa não revela que a conta existe."""
    u = fabrica_usuario(ativo=False)
    r = Client().post(reverse("login"), {"username": u.email, "password": senha_padrao})
    assert r.status_code == 200
    assert "E-mail ou senha inválidos." in _h(r)


@pytest.mark.parametrize("destino", ["https://externo.test/x", "//externo.test/x", "http://externo.test",
                                      "javascript:alert(1)", "/\\externo.test", "https:externo.test"])
def test_open_redirect_via_next(fabrica_usuario, senha_padrao, destino):
    """Login: ?next= externo nunca é seguido."""
    u = fabrica_usuario()
    r = Client().post(reverse("login") + "?next=" + destino, {"username": u.email, "password": senha_padrao,
                                                              "next": destino})
    assert r.status_code == 302
    assert "externo.test" not in r.url and not r.url.lower().startswith("javascript")
    assert r.url.startswith("/")


def test_next_interno_e_respeitado(fabrica_usuario, senha_padrao):
    """Login: ?next= interno continua funcionando (controle negativo do open redirect)."""
    u = fabrica_usuario()
    destino = reverse("contas:trocar_senha")
    r = Client().post(reverse("login") + "?next=" + destino, {"username": u.email, "password": senha_padrao})
    assert r.status_code == 302 and r.url == destino


def test_login_forca_bruta_nao_vaza_nem_da_500(fabrica_usuario):
    """Login: 30 tentativas erradas seguidas respondem sempre sem 500 e sem sessão."""
    u = fabrica_usuario()
    c = Client()
    for i in range(30):
        r = c.post(reverse("login"), {"username": u.email, "password": f"errada-{i}-xxxx"})
        assert r.status_code in (200, 403, 429)
    assert "_auth_user_id" not in c.session


def test_login_payloads_hostis(client):
    """Login: SQLi/unicode/enorme em username e password nunca dão 500."""
    for user in ("' OR 1=1 --", "a" * 10000, "\x00", "😀@exemplo.test"):
        r = client.post(reverse("login"), {"username": user, "password": "x" * 10000})
        assert r.status_code == 200
        assert "_auth_user_id" not in client.session


def test_pagina_de_login_logado_nao_vaza_dados(cliente_adm):
    """Login: GET do login por quem já está logado não dá 500."""
    assert cliente_adm.get(reverse("login")).status_code in (200, 302)
