"""Fixtures do ADVERSARIAL do M8 (T-080). Só pela spec: juridico-cadastro.yaml (CAD-01..23), seguranca.yaml, permissoes.yaml.

Reaproveita o cenário do aceite (`cad`: Dify e DataJud FALSOS em servidor local, liberado só via MOTOR_SSRF_LIBERAR; usuários
adm, ana/Base, bruno/Coordenador, carla/Base sem acesso) e acrescenta: PDFs hostis, worker com prazo e navegador. Nada de internet.
"""
import json
import signal
import zlib
from contextlib import contextmanager

import pytest
from django.apps import apps
from django.core.management import call_command
from django.urls import reverse

from tests.acceptance.juridico.conftest import *  # noqa: F401,F403
from tests.acceptance.juridico.conftest import (  # noqa: F401
    SEGREDO_DATAJUD,
    SEGREDO_DIFY,
    _esc,
    cnj,
    pdf_bytes,
)

PAYLOADS_XSS = [
    "<script>window.__pwn=1</script>",
    "</script><script>window.__pwn=1</script>",
    "<img src=x onerror=window.__pwn=1>",
    '"><svg onload=window.__pwn=1>',
    "'-window.__pwn=1-'",
    "</title><script>window.__pwn=1</script>",
    "</textarea><script>window.__pwn=1</script>",
    "<iframe srcdoc='<script>parent.__pwn=1</script>'>",
    "{{ 7*7 }}{% load x %}${7*7}",
]
CRUS = ("<script>window.__pwn", "<img src=x onerror", "<svg onload", "<iframe srcdoc", "</textarea><script", "</title><script")


@contextmanager
def prazo(segundos):
    """Estoura TimeoutError se o bloco passar de `segundos` (worker travado = achado). Só no thread principal (SIGALRM)."""
    def _estouro(*_):
        raise TimeoutError(f"travou por mais de {segundos}s")
    antigo = signal.signal(signal.SIGALRM, _estouro)
    signal.alarm(segundos)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, antigo)


@pytest.fixture
def rodar_com_prazo():
    """Roda o worker em uma passada com prazo; qualquer exceção do worker é falha (ele nunca pode cair por causa de um item)."""
    def _r(segundos=60):
        with prazo(segundos):
            call_command("processar_cadastros", "--uma-vez")
    return _r


def pdf_custom(texto="", catalogo=b"", extras=(), paginas_extra=b""):
    """PDF com objetos extras. `catalogo` entra dentro do /Catalog; `extras` são objetos 6, 7, … (bytes do corpo de cada um)."""
    linhas = texto.split("\n") if texto else []
    fluxo = (b"BT /F1 10 Tf 12 TL 20 800 Td " + b" T* ".join(b"(" + _esc(x.encode("cp1252", "replace")) + b") Tj" for x in linhas) + b" ET") if linhas else b""
    objs = [b"<< /Type /Catalog /Pages 2 0 R " + catalogo + b" >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> " + paginas_extra + b" >>",
            b"<< /Length " + str(len(fluxo)).encode() + b" >>\nstream\n" + fluxo + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>", *extras]
    return _montar(objs)


def _montar(objs):
    out = bytearray(b"%PDF-1.7\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def pdf_bomba_flate(inflado_mb=200, numero=None):
    """Fluxo de conteúdo FlateDecode que infla para `inflado_mb` MB (bomba de descompressão)."""
    dados = zlib.compress(b"BT /F1 10 Tf (x) Tj ET" + b" " * (inflado_mb * 1024 * 1024))
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(dados)).encode() + b" /Filter /FlateDecode >>\nstream\n" + dados + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    return _montar(objs).replace(b"%PDF-1.7\n", b"%PDF-1.7\n% NUM:" + (numero or "").encode() + b"\n", 1)


def pdf_muitas_paginas(n=100_000, numero=None):
    """Árvore de páginas com `n` referências à mesma página (bomba de páginas)."""
    kids = b" ".join([b"3 0 R"] * n)
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(n).encode() + b" >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length 36 >>\nstream\nBT /F1 10 Tf 20 800 Td (pagina) Tj ET\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    return _montar(objs).replace(b"%PDF-1.7\n", b"%PDF-1.7\n% NUM:" + (numero or "").encode() + b"\n", 1)


def pdf_arvore_ciclica(numero=None):
    """/Pages que contém a si mesma em /Kids."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [2 0 R 3 0 R] /Count 2 /Parent 2 0 R >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>"]
    return _montar(objs).replace(b"%PDF-1.7\n", b"%PDF-1.7\n% NUM:" + (numero or "").encode() + b"\n", 1)


def tudo_que_o_usuario_pode_ver(cad, cliente=None, com_json=True):
    """HTML de todas as telas GET do Jurídico (+ JSON de status se com_json), concatenados (para varrer segredos/payloads)."""
    cliente = cliente or cad.adm
    partes = []
    pk_p = cad.Processo._base_manager.values_list("pk", flat=True)[:3]
    pk_e = cad.Envio.objects.values_list("pk", flat=True)[:3]
    for nome in ("painel", "enviar_pdfs", "enviar_cnj", "envios", "erros", "audiencias", "processo_novo", "config", "excluidos", *(("status",) if com_json else ())):
        partes.append(cliente.get(reverse(f"juridico:{nome}")).content.decode())
    partes.append(cliente.get(reverse("juridico:erros") + "?resolvido=1").content.decode())
    for pk in pk_p:
        partes.append(cliente.get(reverse("juridico:processo", kwargs={"pk": pk})).content.decode())
        partes.append(cliente.get(reverse("juridico:painel") + f"?p={pk}").content.decode())
    for pk in pk_e:
        partes.append(cliente.get(reverse("juridico:envio", kwargs={"pk": pk})).content.decode())
        if com_json:
            partes.append(cliente.get(reverse("juridico:status") + f"?envio={pk}").content.decode())
    return "\n".join(partes)


def tudo_no_banco():
    """Todos os campos de texto/JSON de todos os modelos do Jurídico, como uma única string."""
    out = []
    for M in apps.get_app_config("juridico").get_models():
        for obj in M._base_manager.all():
            for f in M._meta.concrete_fields:
                v = getattr(obj, f.attname, None)
                if v not in (None, ""):
                    out.append(json.dumps(v, default=str, ensure_ascii=False))
    return "\n".join(out)


def sem_cru(h):
    for c in CRUS:
        assert c not in h, c


@pytest.fixture(params=["chromium", "webkit"])
def abrir_pagina(request, live_server):
    """abrir_pagina(cliente_django) → página Playwright (1280x800) com a sessão do cliente. Fecha tudo no fim.
    Coleta `pagina.dialogos` e `pagina.erros_js`. Roda em chromium e webkit."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    navegador = getattr(pw, request.param).launch()
    abertas = []

    def _abrir(cliente):
        ctx = navegador.new_context(viewport={"width": 1280, "height": 800})
        ctx.add_cookies([{"name": "sessionid", "value": cliente.cookies["sessionid"].value, "url": live_server.url}])
        p = ctx.new_page()
        p.live_url = live_server.url
        p.dialogos, p.erros_js = [], []
        p.on("dialog", lambda d: (p.dialogos.append(d.message), d.dismiss()))
        p.on("pageerror", lambda e: p.erros_js.append(str(e)))
        abertas.append(ctx)
        return p

    yield _abrir
    for c in abertas:
        c.close()
    navegador.close()
    pw.stop()


@pytest.fixture(autouse=True)
def semente_apos_flush(db):
    """Testes de navegador (live_server) são transacionais e o flush ao fim apaga a semente das migrações: recompõe papéis e setor Geral."""
    from django.contrib.auth.models import Group
    for nome in ("Adm", "Coordenador", "Base"):
        Group.objects.get_or_create(name=nome)
    Setor = apps.get_model("contas", "Setor")
    Setor.objects.get_or_create(nome="Geral")
