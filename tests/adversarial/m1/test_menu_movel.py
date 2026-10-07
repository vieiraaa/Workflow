"""Adversarial M1 (achado visual da T-012): menu lateral no celular. Playwright contra o live_server a 390px."""

import pytest
from django.urls import reverse

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.modulo("m1")]


def test_menu_abre_no_celular_e_item_e_clicavel(navegador_movel):
    """PRM-06/TEL (T-012 item 1): clicar em 'Abrir menu' a 390px deixa o aside visível e um item navega."""
    pagina = navegador_movel
    pagina.goto(pagina.live_url + reverse("contas:trocar_senha"))
    aside = pagina.locator("aside")
    assert aside.bounding_box()["x"] < 0, "pré-condição: menu fechado a 390px"

    pagina.get_by_role("button", name="Abrir menu").click()
    pagina.wait_for_timeout(600)  # transição

    caixa = aside.bounding_box()
    assert caixa["x"] >= 0, f"aside continua fora da tela após o clique (x={caixa['x']})"
    item = aside.get_by_role("link", name="Execuções")
    assert item.is_visible()
    item.click()
    pagina.wait_for_url("**" + reverse("execucoes:lista"))
