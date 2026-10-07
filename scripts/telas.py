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
# Banco próprio das capturas: não colide com o banco de pytest nem com outros agentes.
os.environ.setdefault("TEST_DATABASE_URL", "postgres://localhost:5432/construtor_telas")

TEMAS = ("light", "dark")
LARGURAS = {1440: 900, 390: 844}
SENHA = "SenhaDemo#12345"
URL_INEXISTENTE = "/nao-existe/"


# ---------------------------------------------------------------- preparação de dados
def _usuarios():
    from django.contrib.auth.models import Group

    from apps.contas.models import Usuario

    Usuario.objects.all().delete()
    for nome in ("Adm", "Coordenador", "Base"):
        Group.objects.get_or_create(name=nome)
    criados = {}
    for chave, email, nome, grupo in (
        ("adm", "adm@exemplo.test", "Ana Admin", "Adm"),
        ("coordenador", "coord@exemplo.test", "Caio Coordenador", "Coordenador"),
        ("base", "base@exemplo.test", "Bia Base", "Base"),
        ("sem_papel", "sem@exemplo.test", "Sem Papel", None),
    ):
        usuario = Usuario.objects.create_user(email=email, password=SENHA, nome=nome)
        if grupo:
            usuario.groups.add(Group.objects.get(name=grupo))
        criados[chave] = usuario
    return criados


def _erro_credenciais(page, base):
    page.fill("input[name=username]", "adm@exemplo.test")
    page.fill("input[name=password]", "senha-errada")
    page.click("form button[type=submit]")
    page.wait_for_load_state("networkidle")


# (id da tela, estado) -> (preparar(usuarios) -> dict de nomes para kwargs | None,
#                          acao(page, base) depois do goto | None)
PREPARADORES = {
    ("TEL-01", "padrao"): (None, None),
    ("TEL-01", "erro_credenciais"): (None, _erro_credenciais),
    ("TEL-10", "padrao"): (None, None),
    ("TEL-11", "padrao"): (None, None),
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


def _subir_servidor():
    porta = _porta_livre()
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
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{porta}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/entrar/", timeout=1)  # noqa: S310
            return proc, base
        except Exception:  # noqa: BLE001 - servidor ainda subindo
            time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("Servidor local não subiu.")


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
                preparar, acao = PREPARADORES[(tela["id"], estado)]
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
                        page.goto(base + caminho)
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
