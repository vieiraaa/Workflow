import importlib.util
import sys

import pytest

from apps.execucoes.models import Execucao
from apps.funcoes.models import Funcao
from config.settings import base

pytestmark = [pytest.mark.modulo("m7a"), pytest.mark.django_db]


@pytest.fixture
def telas():
    caminho = base.BASE_DIR / "scripts" / "telas.py"
    spec = importlib.util.spec_from_file_location("scripts_telas", caminho)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["scripts_telas"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_preparadores_das_funcoes_criam_os_dados(telas, usuario_adm):
    usuarios = {"adm": usuario_adm}
    funcoes = telas.PREPARADORES[("TEL-23", "com_dados")][0](usuarios)
    assert Funcao.objects.count() == 4 and funcoes["rascunho"].versao == 0
    assert not funcoes["inativa"].ativa and Execucao.objects.count() == 1
    telas._limpar_dados_de_telas()
    dados = telas.PREPARADORES[("TEL-26", "truncada")][0](usuarios)
    assert dados["execucao_funcao_demo"].nos.get().itens_saida == 250
    telas._limpar_dados_de_telas()
    assert not Funcao.objects.exists()
