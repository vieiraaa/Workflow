import pytest
from django.http import QueryDict

from apps.funcoes import entradas as ent

pytestmark = pytest.mark.modulo("m7a")


def _e(nome, tipo="texto", **extra):
    return {"nome": nome, "rotulo": nome.capitalize(), "tipo": tipo, **extra}


@pytest.mark.parametrize(
    ("lista", "motivo"),
    [
        ([_e("dia"), _e("dia")], "nome repetido 'dia'"),
        ([_e("Dia")], "nome inválido"),
        ([_e(f"e{i}") for i in range(11)], "no máximo 10"),
        ([_e("x", "lista")], "opções inválidas"),
        ([_e("x", "data", padrao="31/12/2026")], "padrão inválido"),
        ([_e("x", "numero", padrao="abc")], "padrão inválido"),
        ([_e("x", "outro")], "tipo inválido"),
        ({"nome": "x"}, "precisa ser uma lista"),
    ],
)
def test_definicao_invalida(lista, motivo):
    with pytest.raises(ent.EntradaInvalida, match=motivo):
        ent.validar_definicao(lista)


def test_definicao_valida_e_padroes_relativos():
    limpa = ent.validar_definicao(
        [_e("dia", "data", padrao="ontem"), _e("cor", "lista", opcoes=["a", "b"], padrao="a")]
    )
    assert limpa[0]["padrao"] == "ontem" and limpa[1]["padrao"] == "a"
    assert ent.padrao_resolvido(limpa[0]) < ent.hoje().isoformat()


def test_validar_valores_por_tipo():
    defs = ent.validar_definicao(
        [
            _e("nome", obrigatoria=True),
            _e("qtd", "numero"),
            _e("dia", "data"),
            _e("cor", "lista", opcoes=["a"]),
            _e("ok", "booleano"),
        ]
    )
    valores, erros = ent.validar_valores(
        defs, QueryDict("nome=Ana&qtd=2,5&dia=2026-02-28&cor=a&ok=on&intruso=1")
    )
    assert erros == {}
    assert valores == {"nome": "Ana", "qtd": 2.5, "dia": "2026-02-28", "cor": "a", "ok": True}
    _, erros = ent.validar_valores(defs, QueryDict("qtd=x&dia=2026-13-01&cor=z"))
    assert erros == {
        "nome": "Preencha Nome.",
        "qtd": "Qtd: informe um número.",
        "dia": "Dia: data inválida.",
        "cor": "Cor: opção inválida.",
    }
    _, erros = ent.validar_valores(defs, QueryDict("nome=" + "a" * 501))
    assert erros["nome"] == "Nome: máximo de 500 caracteres."


def test_booleano_invalido_vira_erro_e_nunca_excecao():
    defs = ent.validar_definicao([_e("ok", "booleano")])
    for bom, esperado in (("on", True), ("true", True), ("sim", True), ("", False), ("nao", False)):
        assert ent.validar_valores(defs, QueryDict(f"ok={bom}")) == ({"ok": esperado}, {})
    assert ent.validar_valores(defs, QueryDict("ok=talvez"))[1] == {"ok": "Ok: valor inválido."}
