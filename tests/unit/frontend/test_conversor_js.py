"""Roda o teste Node do conversor Drawflow <-> grafo canônico (pula se não houver node)."""

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.modulo("m2")


def test_conversor_grafo_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("node não instalado")
    script = Path(__file__).parent / "conversor.test.js"
    resultado = subprocess.run([node, str(script)], capture_output=True, text=True, check=False)
    assert resultado.returncode == 0, resultado.stderr or resultado.stdout
    assert "ok" in resultado.stdout
