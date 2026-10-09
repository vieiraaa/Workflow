import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]


def _modulo(nome):
    spec = importlib.util.spec_from_file_location(nome, RAIZ / "scripts" / f"{nome}.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(nome, modulo)
    spec.loader.exec_module(modulo)
    return modulo


def test_servidor_lento_e_ambiente_mas_crash_na_subida_e_codigo():
    check = _modulo("check")
    lento = "RuntimeError: Servidor local não subiu em 60 s (tempo esgotado)."
    assert check._classificar(lento) == check.AMBIENTE
    crash = "RuntimeError: Servidor local falhou ao iniciar. Últimas linhas:\nImportError: x"
    assert check._classificar(crash) == check.CODIGO


def test_ultimas_linhas_do_runserver(tmp_path):
    telas = _modulo("telas")
    log = tmp_path / "saida.log"
    log.write_text("\n".join(f"linha {i}" for i in range(40)), encoding="utf-8")
    assert telas._ultimas_linhas(log, 3) == "linha 37\nlinha 38\nlinha 39"
    assert telas._ultimas_linhas(tmp_path / "nao-existe") == "(sem saída do servidor)"
