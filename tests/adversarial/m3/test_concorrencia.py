"""Adversarial M3 · concorrência real (T-033): threads de verdade contra o live_server, banco transacional.

Caixa-preta. Só servidor LOCAL (nunca internet). Cada thread usa o próprio httpx.Client (sessão do Adm + CSRF).
Regras: GRF-07 (409 em salvamento concorrente), EXE-01/EXE-13 (duplo clique), EXE-04/EXE-05 (execuções simultâneas), EST.
"""

import copy
import json
import threading

import httpx
import pytest
from django.urls import reverse

pytestmark = [
    pytest.mark.django_db(transaction=True, serialized_rollback=True),
    pytest.mark.modulo("m3"),
]

TOKEN_CSRF = "t" * 64


def _cliente_http(live_server, cliente_django):
    cookies = {"sessionid": cliente_django.cookies["sessionid"].value, "csrftoken": TOKEN_CSRF}
    return httpx.Client(
        base_url=live_server.url,
        cookies=cookies,
        headers={"X-CSRFToken": TOKEN_CSRF, "Referer": live_server.url + "/"},
        timeout=90,
        follow_redirects=False,
    )


def _disparar(n, alvo):
    """Roda alvo(i) em n threads liberadas ao mesmo tempo. Devolve (resultados, erros)."""
    barreira = threading.Barrier(n, timeout=30)
    resultados, erros = [None] * n, []

    def _roda(i):
        try:
            barreira.wait()
            resultados[i] = alvo(i)
        except Exception as exc:  # noqa: BLE001
            erros.append(repr(exc))

    threads = [threading.Thread(target=_roda, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
    assert not any(t.is_alive() for t in threads), "thread presa (possível deadlock)"
    return resultados, erros


def test_dois_salvamentos_simultaneos_um_200_e_um_409(
    live_server, cliente_adm, fabrica_fluxo, grafo_valido
):
    """GRF-07: dois POSTs com o mesmo atualizado_em → exatamente um 200 e um 409; grafo final é o de um deles."""
    f = fabrica_fluxo(grafo=grafo_valido)
    token = f.atualizado_em.isoformat()
    url = reverse("fluxos:salvar_grafo", kwargs={"pk": f.pk})
    variantes = []
    for i in range(2):
        g = copy.deepcopy(grafo_valido)
        g["nos"][1]["titulo"] = f"Variante {i}"
        variantes.append(g)

    def alvo(i):
        with _cliente_http(live_server, cliente_adm) as c:
            return c.post(
                url,
                content=json.dumps({"grafo": variantes[i], "atualizado_em": token}),
                headers={"Content-Type": "application/json"},
            )

    respostas, erros = _disparar(2, alvo)
    assert not erros, erros
    codigos = sorted(r.status_code for r in respostas)
    assert codigos == [200, 409], codigos
    vencedor = next(i for i, r in enumerate(respostas) if r.status_code == 200)
    perdedor = respostas[1 - vencedor].json()
    assert (
        perdedor["ok"] is False and "alterado por outra pessoa" in perdedor["erros"][0]["mensagem"]
    )
    f.refresh_from_db()
    assert f.grafo == variantes[vencedor], (
        "o grafo gravado deve ser exatamente o do vencedor, sem mistura"
    )


def test_cinco_salvamentos_simultaneos_so_um_vence(
    live_server, cliente_adm, fabrica_fluxo, grafo_valido
):
    """GRF-07: com 5 concorrentes e o mesmo atualizado_em, no máximo um 200; os demais 409; nenhum 500."""
    f = fabrica_fluxo(grafo=grafo_valido)
    token = f.atualizado_em.isoformat()
    url = reverse("fluxos:salvar_grafo", kwargs={"pk": f.pk})

    def alvo(i):
        g = copy.deepcopy(grafo_valido)
        g["nos"][1]["titulo"] = f"Concorrente {i}"
        with _cliente_http(live_server, cliente_adm) as c:
            return c.post(
                url,
                content=json.dumps({"grafo": g, "atualizado_em": token}),
                headers={"Content-Type": "application/json"},
            )

    respostas, erros = _disparar(5, alvo)
    assert not erros, erros
    codigos = [r.status_code for r in respostas]
    assert codigos.count(200) == 1 and codigos.count(409) == 4, codigos
    f.refresh_from_db()
    assert f.grafo["nos"][1]["titulo"] == f"Concorrente {codigos.index(200)}"


def _grafo_local(servidor, cadeia, cfg_http, caminho="/ok"):
    return cadeia(cfg_http(f"{servidor.base}{caminho}"))


def test_duplo_clique_em_executar_nao_prende_execucao(
    live_server, cliente_adm, fabrica_fluxo, liberado, cadeia, cfg_http, modelos
):
    """EXE-01/EXE-13: 2 POSTs simultâneos de executar → sem 500, no máximo 2 execuções, todas finalizadas (nenhuma em executando)."""
    f = fabrica_fluxo(grafo=_grafo_local(liberado, cadeia, cfg_http), status="ativo")
    url = reverse("fluxos:executar", kwargs={"pk": f.pk})

    def alvo(i):
        with _cliente_http(live_server, cliente_adm) as c:
            return c.post(url)

    respostas, erros = _disparar(2, alvo)
    assert not erros, erros
    assert all(r.status_code < 500 for r in respostas), [r.status_code for r in respostas]
    execs = list(modelos.Execucao.objects.filter(fluxo=f))
    assert 1 <= len(execs) <= 2
    assert all(e.status in ("sucesso", "erro") for e in execs), [e.status for e in execs]
    assert all(e.finalizada_em is not None for e in execs)
    for e in execs:
        nos = list(modelos.ExecucaoNo.objects.filter(execucao=e))
        assert len(nos) == 3 and len({n.no_id for n in nos}) == 3, (
            "nós duplicados/faltando numa execução"
        )


def test_duplo_clique_respostas_redirecionam_para_detalhes_distintos(
    live_server, cliente_adm, fabrica_fluxo, liberado, cadeia, cfg_http, modelos
):
    """EXE-01/EXE-11: cada POST aceito redireciona para o detalhe de uma execução existente; nada de execução órfã."""
    f = fabrica_fluxo(grafo=_grafo_local(liberado, cadeia, cfg_http), status="ativo")
    url = reverse("fluxos:executar", kwargs={"pk": f.pk})

    def alvo(i):
        with _cliente_http(live_server, cliente_adm) as c:
            return c.post(url)

    respostas, erros = _disparar(2, alvo)
    assert not erros, erros
    pks = {e.pk for e in modelos.Execucao.objects.filter(fluxo=f)}
    for r in respostas:
        assert r.status_code == 302, r.status_code
        assert r.headers["location"] in {
            reverse("execucoes:detalhe", kwargs={"pk": pk}) for pk in pks
        }


def test_dez_execucoes_simultaneas_de_fluxos_diferentes(
    live_server, cliente_adm, fabrica_fluxo, liberado, cadeia, cfg_http, modelos
):
    """EXE-04/EXE-05: 10 execuções de fluxos distintos (sucesso e erro 5xx misturados) → todas terminam, sem 500, 1 execução por fluxo."""
    fluxos = []
    for i in range(10):
        caminho = "/ok" if i % 2 == 0 else "/status/503"
        fluxos.append(
            fabrica_fluxo(grafo=_grafo_local(liberado, cadeia, cfg_http, caminho), status="ativo")
        )

    def alvo(i):
        with _cliente_http(live_server, cliente_adm) as c:
            return c.post(reverse("fluxos:executar", kwargs={"pk": fluxos[i].pk}))

    respostas, erros = _disparar(10, alvo)
    assert not erros, erros
    assert [r.status_code for r in respostas] == [302] * 10, [r.status_code for r in respostas]
    for i, f in enumerate(fluxos):
        execs = list(modelos.Execucao.objects.filter(fluxo=f))
        assert len(execs) == 1, f"fluxo {i}: {len(execs)} execuções"
        e = execs[0]
        assert e.status == ("sucesso" if i % 2 == 0 else "erro"), (i, e.status)
        assert e.finalizada_em is not None
        nos = {n.no_id: n for n in modelos.ExecucaoNo.objects.filter(execucao=e)}
        assert set(nos) == {"g", "h1", "s"}
        if i % 2:
            assert nos["h1"].erro_categoria == "http_5xx" and nos["s"].status == "nao_executado"
    assert not modelos.Execucao.objects.filter(status="executando").exists()
    assert modelos.Execucao.objects.count() == 10


def test_execucoes_simultaneas_do_mesmo_fluxo_com_usuarios_diferentes(
    live_server,
    cliente_adm,
    cliente_coordenador,
    cliente_base,
    usuario_adm,
    usuario_coordenador,
    usuario_base,
    fabrica_fluxo,
    liberado,
    cadeia,
    cfg_http,
    modelos,
):
    """EXE-08/PRM-03: execuções simultâneas por 3 papéis no mesmo fluxo ativo; cada execução fica com o executor certo."""
    f = fabrica_fluxo(grafo=_grafo_local(liberado, cadeia, cfg_http), status="ativo")
    clientes = [cliente_adm, cliente_coordenador, cliente_base]
    url = reverse("fluxos:executar", kwargs={"pk": f.pk})

    def alvo(i):
        with _cliente_http(live_server, clientes[i]) as c:
            return c.post(url)

    respostas, erros = _disparar(3, alvo)
    assert not erros, erros
    assert [r.status_code for r in respostas] == [302] * 3
    emails = sorted(
        modelos.Execucao.objects.filter(fluxo=f).values_list("executado_por__email", flat=True)
    )
    esperado = sorted([usuario_adm.email, usuario_coordenador.email, usuario_base.email])
    assert emails == esperado


def test_salvar_e_executar_ao_mesmo_tempo_mantem_snapshot_integro(
    live_server, cliente_adm, fabrica_fluxo, liberado, cadeia, cfg_http, modelos
):
    """EXE-03: salvar o grafo durante uma execução não corrompe o snapshot (é exatamente o grafo antigo ou o novo)."""
    antigo = _grafo_local(liberado, cadeia, cfg_http, "/ok")
    novo = copy.deepcopy(antigo)
    novo["nos"][1]["titulo"] = "Novo título"
    f = fabrica_fluxo(grafo=antigo, status="ativo")
    token = f.atualizado_em.isoformat()
    u_exec = reverse("fluxos:executar", kwargs={"pk": f.pk})
    u_salvar = reverse("fluxos:salvar_grafo", kwargs={"pk": f.pk})

    def alvo(i):
        with _cliente_http(live_server, cliente_adm) as c:
            if i == 0:
                return c.post(u_exec)
            return c.post(
                u_salvar,
                content=json.dumps({"grafo": novo, "atualizado_em": token}),
                headers={"Content-Type": "application/json"},
            )

    respostas, erros = _disparar(2, alvo)
    assert not erros, erros
    assert respostas[0].status_code == 302 and respostas[1].status_code in (200, 409)
    e = modelos.Execucao.objects.get(fluxo=f)
    assert e.status in ("sucesso", "erro") and e.grafo_snapshot in (antigo, novo)
