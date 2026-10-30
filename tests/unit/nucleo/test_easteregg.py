"""Easter egg (D-045): vídeo só para quem está na lista; os demais nem recebem o endereço."""

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.modulo("m1"), pytest.mark.django_db]


@pytest.fixture
def pasta(settings, tmp_path):
    (tmp_path / "video.mp4").write_bytes(b"\x00\x00\x00\x20ftypisom")
    (tmp_path / "usuarios.txt").write_text(
        "# comentário\nadm\n  BASE@exemplo.test  \n", encoding="utf-8"
    )
    settings.EASTEREGG_DIR = tmp_path
    return tmp_path


@pytest.mark.parametrize("cliente", ["cliente_adm", "cliente_base"])
def test_quem_esta_na_lista_recebe_o_video(request, pasta, cliente):
    c = request.getfixturevalue(cliente)
    html = c.get(reverse("inicio")).content.decode()
    assert f'data-easteregg="{reverse("easteregg_video")}"' in html and 'data-inicio="/"' in html
    r = c.get(reverse("easteregg_video"))
    assert r.status_code == 200 and r["Content-Type"] == "video/mp4"


def test_fora_da_lista_nem_ve_o_endereco_e_recebe_404(pasta, cliente_coordenador):
    assert "data-easteregg" not in cliente_coordenador.get(reverse("inicio")).content.decode()
    assert cliente_coordenador.get(reverse("easteregg_video")).status_code == 404


def test_anonimo_vai_para_o_login(pasta, cliente_anonimo):
    r = cliente_anonimo.get(reverse("easteregg_video"))
    assert r.status_code == 302 and reverse("login") in r.url


def test_sem_arquivo_de_lista_ninguem_tem(settings, tmp_path, cliente_adm):
    settings.EASTEREGG_DIR = tmp_path
    assert cliente_adm.get(reverse("easteregg_video")).status_code == 404
