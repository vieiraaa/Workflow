"""Aceite M8 · enviar PDFs e guarda do arquivo (CAD-03, CAD-04, TEL-29). Só pela spec."""
import re
from pathlib import Path

import pytest
from django.urls import reverse

from .conftest import cnj, pdf_bytes, pdf_processo, upload

pytestmark = [pytest.mark.django_db, pytest.mark.modulo("m8")]

URL = "juridico:enviar_pdfs"


def _post(c, arquivos, carteira=""):
    return c.post(reverse(URL), {"arquivos": [upload(b, n) for b, n in arquivos], "carteira": carteira})


def test_tela_de_envio_abre_com_o_campo_arquivos(cad, ver):
    """TEL-29: formulário com o campo múltiplo `arquivos` e `carteira`."""
    r = cad.ana.get(reverse(URL))
    assert r.status_code == 200 and 'name="arquivos"' in ver.html(r) and "multiple" in ver.html(r) and 'name="carteira"' in ver.html(r)


def test_envio_ok_cria_envio_itens_na_fila_e_redireciona(cad, ver):
    """CAD-03: ok → Envio + Itens na_fila, redirect para juridico:envio com 'N PDF(s) na fila…'."""
    arqs = [pdf_processo(cnj(1)[0], "a"), pdf_processo(cnj(2)[0], "b")]
    r = _post(cad.ana, arqs, cad.carteiras["Ativos"].pk)
    envio = cad.Envio.objects.get()
    assert r.status_code == 302 and r["Location"] == reverse("juridico:envio", kwargs={"pk": envio.pk})
    assert envio.enviado_por == cad.ana_u and envio.origem == "pdf" and envio.carteira == cad.carteiras["Ativos"]
    itens = list(cad.ItemEnvio.objects.filter(envio=envio).order_by("pk"))
    assert [i.status for i in itens] == ["na_fila", "na_fila"] and [i.nome_arquivo for i in itens] == ["processo-a.pdf", "processo-b.pdf"]
    assert all(len(i.sha256) == 64 for i in itens)
    r2 = cad.ana.get(r["Location"])
    assert re.search(r"2 PDF(\(s\)|s) na fila\. Os dados aparecem no painel em alguns minutos\.", ver.texto(r2))


def test_carteira_e_opcional_no_envio_de_pdf(cad):
    """CAD-03: carteira vazia é aceita."""
    r = _post(cad.ana, [pdf_processo(cnj(1)[0])])
    assert r.status_code == 302 and cad.Envio.objects.get().carteira is None


def test_sem_arquivo(cad, ver):
    """CAD-03: sem arquivo → 200 'Escolha ao menos um PDF.' e nada criado."""
    r = cad.ana.post(reverse(URL), {"carteira": ""})
    assert r.status_code == 200 and "Escolha ao menos um PDF." in ver.texto(r)
    assert cad.Envio.objects.count() == 0 and cad.ItemEnvio.objects.count() == 0


def test_mais_de_10_arquivos(cad, ver):
    """CAD-03: 11 arquivos → 'Envie no máximo 10 PDFs por vez.' e nada criado; 10 passam."""
    onze = [pdf_processo(cnj(i)[0], str(i)) for i in range(1, 12)]
    r = _post(cad.ana, onze)
    assert r.status_code == 200 and "Envie no máximo 10 PDFs por vez." in ver.texto(r)
    assert cad.Envio.objects.count() == 0 and cad.ItemEnvio.objects.count() == 0
    assert _post(cad.ana, onze[:10]).status_code == 302 and cad.ItemEnvio.objects.count() == 10


def test_arquivo_maior_que_30mb(cad, ver):
    """CAD-03: acima de 30 MB → '<nome>: maior que 30 MB.'; abaixo do limite passa."""
    grande = pdf_bytes("x") + b"0" * (31 * 1024 * 1024)
    r = _post(cad.ana, [(grande, "enorme.pdf")])
    assert r.status_code == 200 and "enorme.pdf: maior que 30 MB." in ver.texto(r)
    assert cad.Envio.objects.count() == 0
    quase = pdf_bytes("x") + b"0" * (29 * 1024 * 1024)
    assert _post(cad.ana, [(quase, "quase.pdf")]).status_code == 302


@pytest.mark.parametrize("conteudo", [b"isto nao e um pdf", b"", b" %PDF-1.4 com espaco antes", b"<html>%PDF-</html>", b"PK\x03\x04zip"])
def test_arquivo_que_nao_e_pdf_mesmo_com_extensao_pdf(cad, ver, conteudo):
    """CAD-03: só aceita o que COMEÇA com '%PDF-'; o nome/extensão não basta."""
    r = _post(cad.ana, [(conteudo, "falso.pdf")])
    assert r.status_code == 200 and "falso.pdf: não é um PDF." in ver.texto(r)
    assert cad.Envio.objects.count() == 0 and cad.ItemEnvio.objects.count() == 0


def test_pdf_verdadeiro_com_outra_extensao_e_aceito(cad):
    """CAD-03: começa com %PDF- → aceito mesmo se o nome não termina em .pdf."""
    assert _post(cad.ana, [(pdf_processo(cnj(1)[0])[0], "peticao.dat")]).status_code == 302


def test_um_arquivo_invalido_impede_o_envio_inteiro(cad, ver):
    """CAD-03: 'nada criado' — um inválido no meio do lote barra o lote, e a mensagem cita o arquivo."""
    r = _post(cad.ana, [pdf_processo(cnj(1)[0], "a"), (b"lixo", "ruim.pdf"), pdf_processo(cnj(2)[0], "b")])
    assert r.status_code == 200 and "ruim.pdf: não é um PDF." in ver.texto(r)
    assert cad.Envio.objects.count() == 0 and cad.ItemEnvio.objects.count() == 0


def test_envio_exige_acesso_e_login(cad):
    """cadastro.enviar: sem acesso 403, anônimo login; nada criado."""
    assert _post(cad.carla, [pdf_processo(cnj(1)[0])]).status_code == 403
    r = _post(cad.anonimo, [pdf_processo(cnj(1)[0])])
    assert r.status_code == 302 and reverse("login") in r["Location"]
    assert cad.Envio.objects.count() == 0


def test_base_e_coordenador_com_acesso_podem_enviar(cad):
    """cadastro.enviar: Base e Coordenador do setor com acesso enviam."""
    assert _post(cad.ana, [pdf_processo(cnj(1)[0], "a")]).status_code == 302
    assert _post(cad.bruno, [pdf_processo(cnj(2)[0], "b")]).status_code == 302
    assert {e.enviado_por_id for e in cad.Envio.objects.all()} == {cad.ana_u.pk, cad.bruno_u.pk}


# ---------------- CAD-04 · guarda do PDF ----------------

def test_pdf_guardado_em_disco_privado_com_caminho_uuid(cad, settings):
    """CAD-04: arquivo em MEDIA_ROOT/juridico/AAAA/MM/<uuid>.pdf; conteúdo idêntico ao enviado; nome original fica no item."""
    conteudo, nome = pdf_processo(cnj(1)[0])
    _post(cad.ana, [(conteudo, "Meu Processo.pdf")])
    item = cad.ItemEnvio.objects.get()
    rel = item.arquivo.name
    assert re.fullmatch(r"juridico/\d{4}/\d{2}/[0-9a-f-]{32,36}\.pdf", rel), rel
    assert Path(item.arquivo.path).read_bytes() == conteudo
    assert item.nome_arquivo == "Meu Processo.pdf" and "Meu Processo" not in rel


def test_arquivo_fica_sob_media_root(cad, settings):
    """CAD-04: o PDF vai para o MEDIA_ROOT configurado (privado) — isolamento: sobrescrever MEDIA_ROOT redireciona a gravação."""
    _post(cad.ana, [pdf_processo(cnj(1)[0])])
    item = cad.ItemEnvio.objects.get()
    assert Path(item.arquivo.path).is_relative_to(Path(settings.MEDIA_ROOT)), item.arquivo.path


def test_pdf_nunca_e_servido_por_url_estatica(cad, settings, client):
    """CAD-04: o arquivo não é acessível por MEDIA_URL/estático (nem anônimo, nem logado)."""
    _post(cad.ana, [pdf_processo(cnj(1)[0])])
    rel = cad.ItemEnvio.objects.get().arquivo.name
    base = settings.MEDIA_URL or "/media/"
    for c in (client, cad.ana, cad.adm):
        assert c.get(f"{base}{rel}").status_code in (404, 403, 302)
        assert c.get(f"/static/{rel}").status_code in (404, 403, 302)


def test_pdf_nao_e_gravado_no_banco(cad):
    """CAD-04: o banco guarda só o caminho; nenhum campo do item contém os bytes do PDF."""
    conteudo, _ = pdf_processo(cnj(1)[0])
    _post(cad.ana, [(conteudo, "a.pdf")])
    item = cad.ItemEnvio.objects.get()
    for f in item._meta.get_fields():
        v = getattr(item, f.name, None) if getattr(f, "concrete", False) else None
        assert not isinstance(v, (bytes, memoryview)) and not (isinstance(v, str) and "%PDF-1.4" in v), f.name


def test_baixar_pdf_pela_view_com_cadastro_ver(cad):
    """CAD-04: juridico:pdf (pk do ItemEnvio) entrega o arquivo como attachment para quem tem cadastro.ver."""
    conteudo, _ = pdf_processo(cnj(1)[0])
    _post(cad.ana, [(conteudo, "relatorio.pdf")])
    item = cad.ItemEnvio.objects.get()
    for c in (cad.ana, cad.bruno, cad.adm):
        r = c.get(reverse("juridico:pdf", kwargs={"pk": item.pk}))
        assert r.status_code == 200 and b"".join(r.streaming_content if r.streaming else [r.content]) == conteudo
        assert r["Content-Disposition"].startswith("attachment") and "relatorio.pdf" in r["Content-Disposition"]


def test_baixar_pdf_sem_acesso_ou_anonimo(cad):
    """CAD-04/02: sem acesso 403; anônimo login."""
    _post(cad.ana, [pdf_processo(cnj(1)[0])])
    item = cad.ItemEnvio.objects.get()
    assert cad.carla.get(reverse("juridico:pdf", kwargs={"pk": item.pk})).status_code == 403
    r = cad.anonimo.get(reverse("juridico:pdf", kwargs={"pk": item.pk}))
    assert r.status_code == 302 and reverse("login") in r["Location"]


@pytest.mark.parametrize("nome", ['../../etc/passwd.pdf', 'a"b\r\nSet-Cookie: x=1.pdf', "..\\..\\win.pdf", "não/ok:?.pdf"])
def test_nome_original_e_saneado_no_download(cad, nome):
    """CAD-04: nome original saneado — sem barras, aspas ou CR/LF no Content-Disposition (sem header injection)."""
    _post(cad.ana, [(pdf_processo(cnj(1)[0])[0], nome)])
    item = cad.ItemEnvio.objects.get()
    r = cad.ana.get(reverse("juridico:pdf", kwargs={"pk": item.pk}))
    cd = r["Content-Disposition"]
    assert r.status_code == 200 and "\r" not in cd and "\n" not in cd and "../" not in cd and "..\\" not in cd
    assert "Set-Cookie" not in r.headers or r.headers.get("Set-Cookie", "").find("x=1") < 0


def test_pdf_inexistente_da_404(cad):
    """CAD-04: item inexistente → 404 (com tela do produto)."""
    assert cad.adm.get(reverse("juridico:pdf", kwargs={"pk": 999999})).status_code == 404
