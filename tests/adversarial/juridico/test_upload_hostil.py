"""Adversarial M8 · upload e PDF hostis (CAD-03, CAD-04, CAD-07, CAD-13, SEG-12). Sem internet; o worker nunca pode cair nem travar."""
import time
import zlib

import pytest
from django.urls import reverse

from .conftest import (
    cnj,
    pdf_arvore_ciclica,
    pdf_bomba_flate,
    pdf_bytes,
    pdf_custom,
    pdf_muitas_paginas,
    pdf_processo,
    texto_processo,
    upload,
)

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

URL = "juridico:enviar_pdfs"
NUM, DIG = cnj(1234)


def _post(c, arquivos, **extra):
    return c.post(reverse(URL), {"arquivos": [upload(b, n) for b, n in arquivos], "carteira": "", **extra})


# ---------------- o que NÃO é PDF ----------------

@pytest.mark.parametrize("conteudo", [b"PK\x03\x04" + b"0" * 100, b"\x89PNG\r\n\x1a\n" + b"0" * 100, b"MZ\x90\x00" + b"0" * 100, b"<?php system($_GET[0]); ?>",
                                      b"#!/bin/sh\nrm -rf /", b"%PDF", b"%pdf-1.4", b"\xef\xbb\xbf%PDF-1.4", b"\x00%PDF-1.4"])
def test_nao_pdf_com_extensao_pdf_e_recusado(cad, conteudo):
    """CAD-03: zip/png/exe/script/'%PDF' truncado/BOM antes do cabeçalho com nome .pdf → 'não é um PDF.' e nada criado."""
    r = _post(cad.ana, [(conteudo, "documento.pdf")])
    assert r.status_code == 200 and "documento.pdf: não é um PDF." in r.content.decode().replace("&#x27;", "'")
    assert cad.Envio.objects.count() == 0 and cad.ItemEnvio.objects.count() == 0


def test_pdf_poliglota_com_zip_e_aceito_mas_nunca_extraido(cad, rodar_com_prazo, tmp_path):
    """CAD-03/04: começa com %PDF- e traz um ZIP colado: aceito como PDF, guardado SEM extração (nada novo aparece no disco)."""
    import io
    import zipfile
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("../../../evil.txt", "pwn")
    conteudo = pdf_processo(NUM)[0] + z.getvalue()
    assert _post(cad.ana, [(conteudo, "poliglota.pdf")]).status_code == 302
    rodar_com_prazo()
    assert not list(tmp_path.rglob("evil.txt")) and not (tmp_path.parent / "evil.txt").exists()


@pytest.mark.parametrize("nome", ["../../../etc/passwd.pdf", "..\\..\\windows\\x.pdf", "/etc/cron.d/x.pdf", "a\x00b.pdf", "a\r\nSet-Cookie: x=1.pdf",
                                  "a\tb\x07\x1b[31m.pdf", "gpj.fdp", "x" * 5000 + ".pdf", "CON.pdf", ".pdf", "   ", "<svg onload=alert(1)>.pdf",
                                  "'; DROP TABLE juridico_itemenvio; --.pdf", "nome com\nquebra.pdf"])
def test_nome_de_arquivo_hostil_nunca_derruba_nem_define_o_caminho(cad, nome, settings):
    """CAD-03/04: nome com ../, NUL, CR/LF, RTL, 5000 caracteres, vazio… → aceita saneado ou recusa com erro; nunca 500; o caminho no disco é sempre juridico/AAAA/MM/<uuid>.pdf."""
    import re
    r = _post(cad.ana, [(pdf_processo(NUM)[0], nome)])
    assert r.status_code in (200, 302, 400)
    for item in cad.ItemEnvio.objects.all():
        assert re.fullmatch(r"juridico/\d{4}/\d{2}/[0-9a-f-]{32,36}\.pdf", item.arquivo.name), item.arquivo.name
        assert len(item.nome_arquivo) <= 255 and "\x00" not in item.nome_arquivo and "\n" not in item.nome_arquivo and "\r" not in item.nome_arquivo
        d = cad.ana.get(reverse("juridico:pdf", kwargs={"pk": item.pk}))
        assert d.status_code == 200 and "\n" not in d["Content-Disposition"] and "\r" not in d["Content-Disposition"]
        assert d["Content-Disposition"].startswith("attachment")


def test_download_do_pdf_nao_e_renderizado_no_site(cad):
    """CAD-04/SEG-12: o PDF baixado é 'attachment', com nosniff e Content-Type application/pdf (nunca text/html)."""
    html_malicioso = b"%PDF-1.4\n<html><script>alert(1)</script></html>\n%%EOF"
    _post(cad.ana, [(html_malicioso, "x.html")])
    item = cad.ItemEnvio.objects.get()
    r = cad.ana.get(reverse("juridico:pdf", kwargs={"pk": item.pk}))
    assert r["Content-Disposition"].startswith("attachment") and r["Content-Type"].startswith("application/pdf")
    assert r.headers.get("X-Content-Type-Options", "").lower() == "nosniff"


def test_arquivo_nao_e_acessivel_por_url_adivinhada(cad, settings):
    """CAD-04: nem o caminho em disco nem variantes dele respondem 200 por URL pública."""
    _post(cad.ana, [pdf_processo(NUM)])
    rel = cad.ItemEnvio.objects.get().arquivo.name
    base = (settings.MEDIA_URL or "/media/")
    for url in (f"{base}{rel}", f"/{rel}", f"/static/{rel}", f"{base}../{rel}", f"/media//{rel}", f"/juridico/{rel}", f"/juridico/media/{rel}"):
        assert cad.anonimo.get(url).status_code in (301, 302, 403, 404), url
        assert cad.adm.get(url).status_code in (301, 302, 403, 404), url


def test_download_exige_cadastro_ver_e_nao_aceita_traversal_no_pk(cad):
    """CAD-04: pk do juridico:pdf só inteiro; 403 sem acesso."""
    _post(cad.ana, [pdf_processo(NUM)])
    item = cad.ItemEnvio.objects.get()
    assert cad.carla.get(reverse("juridico:pdf", kwargs={"pk": item.pk})).status_code == 403
    for ruim in ("../1", "1%2f..%2f1", "1;ls", "abc"):
        assert cad.adm.get(f"/juridico/pdf/{ruim}/").status_code in (404, 400, 301, 302)


# ---------------- limites do envio ----------------

def test_centenas_de_arquivos_no_mesmo_post(cad):
    """CAD-03: 150 arquivos → recusa limpa (200/400/413), nada criado (nem fila parcial)."""
    arqs = [(pdf_bytes(f"x{i}"), f"{i}.pdf") for i in range(150)]
    r = _post(cad.ana, arqs)
    assert r.status_code in (200, 400, 413) and cad.Envio.objects.count() == 0 and cad.ItemEnvio.objects.count() == 0


def test_dez_arquivos_passam_e_o_11o_barra_tudo(cad):
    """CAD-03: exatamente 10 ok; 11 → nada criado."""
    dez = [pdf_processo(cnj(i)[0], str(i)) for i in range(1, 11)]
    assert _post(cad.ana, dez).status_code == 302 and cad.ItemEnvio.objects.count() == 10
    assert _post(cad.ana, dez + [pdf_processo(cnj(50)[0], "x")]).status_code == 200
    assert cad.ItemEnvio.objects.count() == 10 and cad.Envio.objects.count() == 1


def test_arquivo_de_exatos_30mb_e_30mb_mais_1(cad):
    """CAD-03: 30 MB passa; 30 MB + 1 byte é recusado (fronteira exata, MB = 1024²)."""
    base = pdf_bytes("x")
    limite = 30 * 1024 * 1024
    assert _post(cad.ana, [(base + b"0" * (limite - len(base)), "no_limite.pdf")]).status_code == 302
    r = _post(cad.ana, [(base + b"0" * (limite - len(base) + 1), "estourou.pdf")])
    assert r.status_code == 200 and "estourou.pdf: maior que 30 MB." in r.content.decode()
    assert cad.ItemEnvio.objects.count() == 1


def test_campo_arquivos_com_mesmo_arquivo_repetido_no_lote(cad, rodar):
    """CAD-06a/(b): o mesmo arquivo 10× no mesmo lote → um único processo e nenhum item com erro (os repetidos atualizam, sem duplicar)."""
    a = pdf_processo(NUM)
    _post(cad.ana, [a] * 10)
    rodar()
    assert cad.Processo.objects.count() == 1
    assert not cad.ItemEnvio.objects.filter(status="erro").exists()


def test_content_type_mentiroso_nao_decide_nada(cad):
    """CAD-03: o que vale é o conteúdo; PDF com Content-Type image/png passa, texto com application/pdf não."""
    from django.core.files.uploadedfile import SimpleUploadedFile
    r1 = cad.ana.post(reverse(URL), {"arquivos": [SimpleUploadedFile("a.pdf", pdf_processo(NUM)[0], content_type="image/png")], "carteira": ""})
    r2 = cad.ana.post(reverse(URL), {"arquivos": [SimpleUploadedFile("b.pdf", b"texto simples", content_type="application/pdf")], "carteira": ""})
    assert r1.status_code == 302 and r2.status_code == 200 and cad.ItemEnvio.objects.count() == 1


@pytest.mark.parametrize("carteira", ["abc", "-1", "999999", "1;2", "1\x00", "%s", "1e3"])
def test_carteira_hostil_no_envio_de_pdf(cad, carteira):
    """CAD-03/23: carteira inválida no envio → erro de campo ou ignorada; nunca 500 e nunca uma carteira que não existe."""
    r = cad.ana.post(reverse(URL), {"arquivos": [upload(*pdf_processo(NUM))], "carteira": carteira})
    assert r.status_code in (200, 302)
    for e in cad.Envio.objects.all():
        assert e.carteira is None or cad.Carteira.objects.filter(pk=e.carteira_id).exists()


def test_carteira_inativa_nao_serve_para_envio(cad):
    """CAD-05/14: carteira desativada não pode ser escolhida (o formulário só lista ativas)."""
    cad.Carteira.objects.filter(pk=cad.carteiras["Volvo"].pk).update(ativa=False)
    r = cad.ana.post(reverse(URL), {"arquivos": [upload(*pdf_processo(NUM))], "carteira": cad.carteiras["Volvo"].pk})
    assert r.status_code == 200 and cad.Envio.objects.count() == 0


# ---------------- PDFs que tentam atacar o servidor (worker) ----------------

def _processar(cad, rodar_com_prazo, conteudo, nome="hostil.pdf", seg=60):
    _post(cad.ana, [(conteudo, nome)])
    inicio = time.monotonic()
    rodar_com_prazo(seg)
    item = cad.ItemEnvio.objects.order_by("pk").last()
    item.refresh_from_db()
    assert item.status in ("concluido", "erro", "ignorado"), item.status
    return item, time.monotonic() - inicio


def test_pdf_com_javascript_e_acao_de_abertura_nao_executa_nada(cad, rodar_com_prazo, tmp_path):
    """CAD-07: /OpenAction com /JavaScript e /Launch, /AA na página, URI: o servidor só lê texto; nada é executado/baixado/aberto."""
    marcador = tmp_path / "executou.txt"
    js = f"app.alert(1); this.exportDataObject({{cName:'x', nLaunch:2}}); util.printf('{marcador}');".encode()
    catalogo = (b"/OpenAction << /S /JavaScript /JS (" + js.replace(b"(", b"[").replace(b")", b"]") + b") >> "
                b"/AA << /WC << /S /Launch /F (cmd.exe) >> >> /Names << /JavaScript << /Names [(a) << /S /JavaScript /JS (app.alert\\(1\\)) >>] >> >>")
    pdf = pdf_custom(texto_processo(NUM), catalogo=catalogo, paginas_extra=b"/AA << /O << /S /URI /URI (http://169.254.169.254/latest) >> >>")
    pdf = pdf.replace(b"%PDF-1.7\n", b"%PDF-1.7\n% NUM:" + NUM.encode() + b"\n", 1)
    item, _ = _processar(cad, rodar_com_prazo, pdf)
    assert not marcador.exists() and cad.srv.hits("/latest") == []
    assert item.status in ("concluido", "erro")


def test_pdf_com_anexo_embutido_executavel_nao_e_extraido(cad, rodar_com_prazo, tmp_path):
    """CAD-04/07: EmbeddedFile (.exe) dentro do PDF não é extraído para o disco nem tratado como segundo documento."""
    anexo = b"<< /Type /EmbeddedFile /Length 4 >>\nstream\nMZ!!\nendstream"
    spec = b"<< /Type /Filespec /F (../../evil.exe) /UF (../../evil.exe) /EF << /F 6 0 R >> >>"
    pdf = pdf_custom(texto_processo(NUM), catalogo=b"/Names << /EmbeddedFiles << /Names [(evil.exe) 7 0 R] >> >>", extras=[anexo, spec])
    item, _ = _processar(cad, rodar_com_prazo, pdf)
    assert not list(tmp_path.rglob("*.exe")) and not (tmp_path.parent / "evil.exe").exists()
    assert len(cad.dify.chats) <= 1


def test_bomba_de_descompressao_nao_derruba_nem_trava_o_worker(cad, rodar_com_prazo):
    """CAD-07/13: fluxo FlateDecode que infla para 200 MB → item termina (concluido via upload ou erro de leitura) em tempo razoável."""
    item, dur = _processar(cad, rodar_com_prazo, pdf_bomba_flate(200, NUM), seg=90)
    assert dur < 90 and (item.status == "concluido" or item.etapa_erro in ("Leitura do PDF", "Envio do PDF", "IA (Dify)"))
    assert len(item.motivo or "") <= 500 and "Traceback" not in (item.motivo or "")


def test_bomba_de_paginas_nao_trava_o_worker(cad, rodar_com_prazo):
    """CAD-07/13: 100.000 referências de página → termina no prazo; o texto enviado ao Dify respeita o corte (≤ ~40.100)."""
    item, dur = _processar(cad, rodar_com_prazo, pdf_muitas_paginas(100_000, NUM), seg=90)
    assert dur < 90 and all(len(c.get("query") or "") <= 40_200 for c in cad.dify.chats)


def test_arvore_de_paginas_ciclica_nao_trava(cad, rodar_com_prazo):
    """CAD-07/13: /Pages que contém a si mesma → sem recursão infinita; item em estado final."""
    item, dur = _processar(cad, rodar_com_prazo, pdf_arvore_ciclica(NUM), seg=60)
    assert dur < 60


@pytest.mark.parametrize("conteudo", [b"%PDF-1.4\n", b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog", b"%PDF-1.7\n" + b"\x00" * 2000 + b"\n%%EOF",
                                      b"%PDF-1.4\n" + zlib.compress(b"lixo" * 1000), b"%PDF-1.4\ntrailer\n<< /Root 99 0 R /Encrypt 98 0 R >>\n%%EOF",
                                      b"%PDF-1.4\n1 0 obj\n<< /Length 99999999 >>\nstream\nabc\n"])
def test_pdf_corrompido_ou_truncado_vira_item_com_motivo(cad, rodar_com_prazo, conteudo):
    """CAD-13: PDF quebrado/truncado/'criptografado' → item final (erro com motivo legível, ou concluído via upload); worker não cai."""
    item, _ = _processar(cad, rodar_com_prazo, conteudo)
    if item.status == "erro":
        assert item.etapa_erro in ("Leitura do PDF", "Envio do PDF", "IA (Dify)") and item.motivo and len(item.motivo) <= 500
        assert "Traceback" not in item.motivo and "File \"" not in item.motivo


def test_texto_gigante_de_30mb_e_cortado_antes_do_dify(cad, rodar_com_prazo):
    """CAD-07: uma linha de texto de ~25 MB → ao Dify vai no máximo 25.000 + marcador + 15.000, e o worker não estoura memória/tempo."""
    texto = f"{NUM} " + "palavra " * 3_000_000
    item, _ = _processar(cad, rodar_com_prazo, pdf_bytes(texto, numero=NUM), seg=90)
    assert cad.dify.chats and len(cad.dify.chats[0]["query"]) <= 40_100


def test_pdf_com_texto_hostil_so_vira_dado(cad, rodar_com_prazo):
    """CAD-18: texto do PDF com HTML/JS/instruções vira DADO — enviado ao Dify como texto, sem avaliação; nada executa."""
    texto = texto_processo(NUM) + " <script>alert(1)</script> {{7*7}} ${7*7} ';DROP TABLE x;-- "
    item, _ = _processar(cad, rodar_com_prazo, pdf_bytes(texto, numero=NUM))
    assert item.status == "concluido" and "<script>alert(1)</script>" in cad.dify.chats[0]["query"]
