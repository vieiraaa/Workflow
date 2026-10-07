import json
from pathlib import Path

import pytest

from apps.motor import placeholders as ph
from apps.motor.placeholders import ErroPlaceholder

pytestmark = pytest.mark.modulo("m3")

ANTERIOR = {
    "status": 200,
    "headers": {"content-type": "application/json", "x-id": "7"},
    "corpo": {
        "id": 42,
        "nome": 'Ana "A" <b>',
        "ativo": True,
        "nada": None,
        "preco": 9.5,
        "itens": [{"sku": "a-1"}, {"sku": "b/2"}],
        "obj": {"k": [1, 2]},
        "multi": "linha1\nlinha2",
        "perigo": "x/../y?z=1#f@h",
        "unicode": "ção 😀",
    },
}


def r(texto, contexto="valor"):
    return {"url": ph.resolver_url, "valor": ph.resolver_valor, "corpo": ph.resolver_corpo}[
        contexto
    ](texto, ANTERIOR)


# ---- PLH-01: sintaxe
@pytest.mark.parametrize(
    "texto",
    [
        "{{ anterior.status }}",
        "{{anterior.status}}",
        "{{   anterior.status   }}",
        "{{\tanterior.status\t}}",
    ],
)
def test_espacos_internos_sao_opcionais(texto):
    assert r(texto) == "200"


def test_texto_sem_placeholder_passa_igual_e_literais_ao_redor_ficam():
    assert r("sem nada") == "sem nada"
    assert r("a {{ anterior.status }} b {{ anterior.headers.x-id }} c") == "a 200 b 7 c"
    assert r("aberto {{ sem fechar") == "aberto {{ sem fechar"


@pytest.mark.parametrize(
    "texto",
    [
        "{{ anterior }}",
        "{{ anterior. }}",
        "{{ anterior..status }}",
        "{{ anterior.status.}}",
        "{{ outro.status }}",
        "{{ status }}",
        "{{ anterior.status | upper }}",
        "{{ anterior.corpo.nome + 1 }}",
        "{{ anterior['status'] }}",
        "{{ anterior.status() }}",
        "{{ anterior.__class__ }}",
        "{{ 7*7 }}",
        "{{ anterior.sta tus }}",
        "{{ }}",
        "{{ anterior.status\n}}",
        "{% if x %}",
    ],
)
def test_sintaxe_fora_do_formato_e_erro(texto):
    if texto == "{% if x %}":
        assert r(texto) == texto  # não é placeholder: segue literal
        return
    with pytest.raises(ErroPlaceholder) as erro:
        r(texto)
    assert erro.value.categoria == "placeholder"


def test_dunder_e_atributos_nunca_sao_alcancados():
    for caminho in ("__class__", "__dict__", "corpo.__class__", "headers.keys", "corpo.nome.upper"):
        with pytest.raises(ErroPlaceholder):
            r(f"{{{{ anterior.{caminho} }}}}")


# ---- PLH-02/03: caminhos
def test_caminhos_dict_lista_e_indice():
    assert r("{{ anterior.corpo.id }}") == "42"
    assert r("{{ anterior.corpo.itens.1.sku }}") == "b/2"
    assert r("{{ anterior.corpo.obj.k.0 }}") == "1"
    assert r("{{ anterior.headers.content-type }}") == "application/json"


@pytest.mark.parametrize(
    "caminho",
    [
        "corpo.naoexiste",
        "corpo.itens.2",
        "corpo.itens.x",
        "corpo.itens.-1",
        "corpo.id.mais",
        "corpo.nome.0",
        "naoexiste",
    ],
)
def test_caminho_inexistente_mensagem_com_o_caminho(caminho):
    with pytest.raises(ErroPlaceholder) as erro:
        r(f"{{{{ anterior.{caminho} }}}}")
    assert f"anterior.{caminho}" in erro.value.mensagem
    assert erro.value.categoria == "placeholder"


def test_indice_numerico_em_dict_e_chave_de_texto():
    assert ph.resolver_caminho({"0": "zero"}, "0") == "zero"
    with pytest.raises(ErroPlaceholder):
        ph.resolver_caminho([1], "00x")


@pytest.mark.parametrize(
    ("caminho", "esperado"),
    [
        ("corpo.ativo", "true"),
        ("corpo.nada", "null"),
        ("corpo.preco", "9.5"),
        ("corpo.obj", '{"k":[1,2]}'),
        ("corpo.itens.0", '{"sku":"a-1"}'),
    ],
)
def test_tipos_viram_texto(caminho, esperado):
    assert r(f"{{{{ anterior.{caminho} }}}}") == esperado


def test_nao_finito_nao_vira_texto():
    with pytest.raises(ErroPlaceholder):
        ph.como_texto(float("nan"))


# ---- PLH-04: inserção por contexto
def test_url_percent_encode_nao_injeta():
    url = r("https://api.exemplo.test/p/{{ anterior.corpo.perigo }}", "url")
    assert url == "https://api.exemplo.test/p/x%2F..%2Fy%3Fz%3D1%23f%40h"
    for caractere in "?#@":
        assert caractere not in url.split("/p/")[1]
    assert r("https://e.test/{{ anterior.corpo.unicode }}", "url").endswith(
        "%C3%A7%C3%A3o%20%F0%9F%98%80"
    )
    assert r("https://e.test/?a={{ anterior.corpo.nome }}", "url").count("?") == 1


def test_url_objeto_vira_json_compacto_codificado():
    assert r("https://e.test/{{ anterior.corpo.obj }}", "url") == (
        "https://e.test/%7B%22k%22%3A%5B1%2C2%5D%7D"
    )


def test_header_e_query_recusam_crlf():
    assert r("v={{ anterior.corpo.id }}") == "v=42"
    with pytest.raises(ErroPlaceholder):
        r("{{ anterior.corpo.multi }}")
    with pytest.raises(ErroPlaceholder):
        r("x{{ anterior.corpo.multi }}", "valor")


def test_corpo_escapa_como_string_json():
    texto = r('{"nome": "{{ anterior.corpo.nome }}", "m": "{{ anterior.corpo.multi }}"}', "corpo")
    dados = json.loads(texto)  # continua JSON válido, sem injeção de chaves
    assert dados == {"nome": 'Ana "A" <b>', "m": "linha1\nlinha2"}
    assert json.loads(r('{"x": "{{ anterior.corpo.unicode }}"}', "corpo"))["x"] == "ção 😀"


def test_corpo_injecao_de_chave_nao_acontece():
    anterior = {"corpo": '", "admin": true, "x": "'}
    texto = ph.resolver_corpo('{"nome": "{{ anterior.corpo }}"}', anterior)
    assert json.loads(texto) == {"nome": '", "admin": true, "x": "'}


def test_corpo_objeto_vira_json_compacto_dentro_da_string():
    texto = r('{"d": "{{ anterior.corpo.obj }}"}', "corpo")
    assert json.loads(texto) == {"d": '{"k":[1,2]}'}


def test_valor_resolvido_enorme_e_recusado():
    grande = {"corpo": "x" * 600_000}
    with pytest.raises(ErroPlaceholder):
        ph.resolver_valor("{{ anterior.corpo }}{{ anterior.corpo }}", grande)


def test_resultado_nao_e_reinterpretado_como_placeholder():
    anterior = {"corpo": "{{ anterior.status }}"}
    assert ph.resolver_valor("{{ anterior.corpo }}", anterior) == "{{ anterior.status }}"


def test_tem_placeholder():
    assert ph.tem_placeholder("a {{ anterior.x }}")
    assert not ph.tem_placeholder("a { b }")
    assert not ph.tem_placeholder(None)


def test_o_modulo_nao_usa_eval_exec_nem_engine_de_template():
    fonte = Path("apps/motor/placeholders.py").read_text(encoding="utf-8")
    for proibido in (
        "eval(",
        "exec(",
        "compile(",
        "getattr(",
        "django.template",
        "jinja",
        "Template(",
    ):
        assert proibido not in fonte, proibido
