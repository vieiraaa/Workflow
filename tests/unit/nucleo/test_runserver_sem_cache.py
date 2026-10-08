from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.test import RequestFactory


def test_estaticos_do_runserver_vao_com_no_cache():
    from apps.nucleo.management.commands.runserver import Command

    handler = Command().get_handler(use_static_handler=True, insecure_serving=True)
    assert isinstance(handler, StaticFilesHandler)
    resposta = handler.serve(RequestFactory().get("/static/css/app.css"))
    assert resposta.status_code == 200
    assert resposta["Cache-Control"] == "no-cache"


def test_dev_e_demo_usam_o_runserver_do_nucleo_e_producao_nao():
    from config.settings import base, demo, dev

    for modulo in (dev, demo):
        assert modulo.INSTALLED_APPS.index("apps.nucleo") < modulo.INSTALLED_APPS.index(
            "django.contrib.staticfiles"
        )
    assert base.INSTALLED_APPS.index("apps.nucleo") > base.INSTALLED_APPS.index(
        "django.contrib.staticfiles"
    )
