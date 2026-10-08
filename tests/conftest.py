import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.contas.models import Usuario


def pytest_addoption(parser):
    parser.addoption(
        "--modulo-ate",
        type=int,
        default=None,
        help="roda só testes marcados com modulo('mN') até N (sem marcador sempre roda)",
    )


def pytest_collection_modifyitems(config, items):
    limite = config.getoption("--modulo-ate")
    if limite is None:
        return
    selecionados, descartados = [], []
    for item in items:
        marca = item.get_closest_marker("modulo")
        numero = int(marca.args[0].lstrip("m")) if marca and marca.args else None
        (descartados if numero is not None and numero > limite else selecionados).append(item)
    config.hook.pytest_deselected(items=descartados)
    items[:] = selecionados


SENHA_TESTE = "SenhaForte#12345"


def criar_usuario(email, nome, grupo=None, **extra):
    usuario = Usuario.objects.create_user(email=email, password=SENHA_TESTE, nome=nome, **extra)
    if grupo:
        usuario.groups.add(Group.objects.get(name=grupo))
    return usuario


def _cliente_logado(usuario):
    cliente = Client()
    cliente.force_login(usuario)
    return cliente


@pytest.fixture
def senha_teste():
    return SENHA_TESTE


@pytest.fixture
def usuario_adm(db):
    return criar_usuario("adm@exemplo.test", "Ana Admin", "Adm")


@pytest.fixture
def usuario_coordenador(db):
    return criar_usuario("coord@exemplo.test", "Caio Coordenador", "Coordenador")


@pytest.fixture
def usuario_base(db):
    return criar_usuario("base@exemplo.test", "Bia Base", "Base")


@pytest.fixture
def usuario_sem_papel(db):
    return criar_usuario("sem@exemplo.test", "Sem Papel")


@pytest.fixture
def cliente_anonimo():
    return Client()


@pytest.fixture
def cliente_adm(usuario_adm):
    return _cliente_logado(usuario_adm)


@pytest.fixture
def cliente_coordenador(usuario_coordenador):
    return _cliente_logado(usuario_coordenador)


@pytest.fixture
def cliente_base(usuario_base):
    return _cliente_logado(usuario_base)


@pytest.fixture
def cliente_sem_papel(usuario_sem_papel):
    return _cliente_logado(usuario_sem_papel)
