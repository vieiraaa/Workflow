"""Aceite M3: execução. Fontes: EXE-01..07, EXE-11, EXE-12, PRM-01/02/03/08, SEG-07."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def _h(r):
    return r.content.decode()


@pytest.mark.modulo("m3")
def test_execucao_sucesso_redireciona_para_detalhe_com_toast(cliente_coordenador, liberado, executar, cadeia, cfg_http):
    """EXE-01/EXE-11: sucesso → redirect execucoes:detalhe + toast 'Execução concluída.'"""
    g = cadeia(cfg_http(f"{liberado.base}/ok"))
    r, e, _ = executar(cliente_coordenador, g, follow=True)
    assert r.redirect_chain[-1][0] == reverse("execucoes:detalhe", kwargs={"pk": e.pk})
    assert "Execução concluída." in _h(r)
    assert e.status == "sucesso" and e.finalizada_em is not None


@pytest.mark.modulo("m3")
def test_execucao_com_erro_toast_de_erro(cliente_coordenador, liberado, executar, cadeia, cfg_http):
    """EXE-11: erro → redirect para o detalhe + 'A execução terminou com erro.'"""
    r, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/status/500")), follow=True)
    assert r.redirect_chain[-1][0] == reverse("execucoes:detalhe", kwargs={"pk": e.pk})
    assert "A execução terminou com erro." in _h(r)
    assert e.status == "erro" and e.erro_resumo


@pytest.mark.modulo("m3")
def test_um_execucao_no_por_no_em_ordem_com_duracao(cliente_coordenador, liberado, executar, nos_de, cadeia, cfg_http):
    """EXE-04: um ExecucaoNo por nó, em ordem a partir do gatilho, com duracao_ms inteiro ≥ 0."""
    g = cadeia(cfg_http(f"{liberado.base}/ok"), cfg_http(f"{liberado.base}/ok"))
    _, e, _ = executar(cliente_coordenador, g)
    nos = nos_de(e)
    assert [n.no_id for n in nos] == ["g", "h1", "h2", "s"]
    assert [n.ordem for n in nos] == sorted(n.ordem for n in nos)
    assert [n.no_tipo for n in nos] == ["gatilho", "http", "http", "saida"]
    assert all(n.status == "sucesso" for n in nos)
    assert all(isinstance(n.duracao_ms, int) and n.duracao_ms >= 0 for n in nos)
    assert nos[1].no_titulo == "H1"


@pytest.mark.modulo("m3")
def test_formato_gravado_do_no_http(cliente_coordenador, liberado, executar, no, cadeia, cfg_http):
    """EXE-12: entrada {metodo,url,headers,query,corpo} e saída {status,headers(minúsculos),corpo,truncado}."""
    g = cadeia(cfg_http(f"{liberado.base}/eco", "POST", [{"nome": "X-Meu", "valor": "v1"}], [{"nome": "q", "valor": "1"}], '{"a": 1}'))
    _, e, _ = executar(cliente_coordenador, g)
    h1 = no(e, "h1")
    assert {"metodo", "url", "headers", "query", "corpo"} <= set(h1.entrada)
    assert h1.entrada["metodo"] == "POST" and h1.entrada["headers"] == [{"nome": "X-Meu", "valor": "v1"}]
    assert h1.entrada["query"] == [{"nome": "q", "valor": "1"}]
    assert h1.saida["status"] == 200 and h1.saida["truncado"] is False
    assert all(k == k.lower() for k in h1.saida["headers"])
    assert h1.saida["corpo"]["metodo"] == "POST"
    assert h1.saida["corpo"]["query"] == {"q": ["1"]}
    assert h1.saida["corpo"]["headers"]["x-meu"] == "v1"
    assert h1.saida["corpo"]["corpo"] == '{"a": 1}'


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("metodo", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_todos_os_metodos(cliente_coordenador, liberado, executar, no, metodo, cadeia, cfg_http):
    """GRF-04/EXE-04: o método configurado é o enviado."""
    corpo = '{"a": 1}' if metodo in ("POST", "PUT", "PATCH") else ""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/eco", metodo, corpo=corpo)))
    assert e.status == "sucesso"
    assert no(e, "h1").saida["corpo"]["metodo"] == metodo


@pytest.mark.modulo("m3")
def test_corpo_texto_nao_json_e_gravado_como_texto(cliente_coordenador, liberado, executar, no, cadeia, cfg_http):
    """EXE-12: corpo não-JSON da resposta é gravado como texto."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/texto")))
    assert no(e, "h1").saida["corpo"] == "texto simples, nao json"


@pytest.mark.modulo("m3")
def test_gatilho_grava_saida_plh02(cliente_coordenador, usuario_coordenador, liberado, executar, no, cadeia, cfg_http):
    """PLH-02/EXE-12: saída do gatilho = {disparado_em ISO-8601, executado_por email}."""
    from datetime import datetime

    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/ok")))
    s = no(e, "g").saida
    assert s["executado_por"] == usuario_coordenador.email
    datetime.fromisoformat(s["disparado_em"])
    assert e.executado_por_id == usuario_coordenador.pk


@pytest.mark.modulo("m3")
def test_saida_e_a_saida_completa_do_anterior(cliente_coordenador, liberado, executar, no, cadeia, cfg_http):
    """EXE-07: o nó saída grava a saída completa do nó anterior."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/ok")))
    assert no(e, "s").saida == no(e, "h1").saida


@pytest.mark.modulo("m3")
@pytest.mark.parametrize("codigo,categoria", [(400, "http_4xx"), (404, "http_4xx"), (429, "http_4xx"), (500, "http_5xx"), (503, "http_5xx")])
def test_http_4xx_5xx_e_erro_do_no_mas_grava_a_resposta(cliente_coordenador, liberado, executar, no, nos_de, codigo, categoria, cadeia, cfg_http):
    """EXE-06/EXE-05: 4xx/5xx = erro do nó com categoria; status, headers e corpo ficam na saída; seguintes nao_executado."""
    g = cadeia(cfg_http(f"{liberado.base}/status/{codigo}"), cfg_http(f"{liberado.base}/ok"))
    _, e, _ = executar(cliente_coordenador, g)
    h1 = no(e, "h1")
    assert h1.status == "erro" and h1.erro_categoria == categoria and h1.erro_mensagem
    assert h1.saida["status"] == codigo
    assert h1.saida["corpo"]["codigo"] == codigo and "content-type" in h1.saida["headers"]
    assert e.status == "erro"
    assert [n.status for n in nos_de(e)] == ["sucesso", "erro", "nao_executado", "nao_executado"]
    assert liberado.contagem("/ok") == 0


@pytest.mark.modulo("m3")
def test_falha_mantem_o_que_ja_rodou(cliente_coordenador, liberado, executar, no, cadeia, cfg_http):
    """EXE-05: o que rodou antes da falha é mantido."""
    g = cadeia(cfg_http(f"{liberado.base}/ok"), cfg_http(f"{liberado.base}/status/500"))
    _, e, _ = executar(cliente_coordenador, g)
    assert no(e, "h1").status == "sucesso" and no(e, "h1").saida["status"] == 200
    assert no(e, "h2").status == "erro"
    assert no(e, "s").status == "nao_executado"


@pytest.mark.modulo("m3")
def test_pendencias_nao_criam_execucao(cliente_coordenador, executar, modelos):
    """EXE-02/EXE-11: grafo com pendências → nenhuma execução, volta com erro."""
    g = {"versao": 1, "nos": [], "arestas": []}
    r, e, f = executar(cliente_coordenador, g, status="rascunho", follow=True)
    assert e is None and modelos.Execucao.objects.count() == 0
    assert r.status_code == 200
    assert "Este fluxo tem pendências. Corrija no editor antes de executar." in r.content.decode()


@pytest.mark.modulo("m3")
def test_adm_e_coordenador_executam_rascunho_valido(cliente_adm, cliente_coordenador, liberado, executar, cadeia, cfg_http):
    """PRM (fluxos.executar todos): Adm e Coordenador executam também rascunho."""
    g = cadeia(cfg_http(f"{liberado.base}/ok"))
    for c in (cliente_adm, cliente_coordenador):
        r, e, _ = executar(c, g, status="rascunho")
        assert r.status_code == 302 and e is not None and e.status == "sucesso"


@pytest.mark.modulo("m3")
def test_base_executa_ativo_e_nao_rascunho(cliente_base, usuario_base, liberado, executar, modelos, cadeia, cfg_http):
    """PRM-03/FLX-05: Base executa fluxo ativo; rascunho → 404 e nada criado."""
    g = cadeia(cfg_http(f"{liberado.base}/ok"))
    r, e, _ = executar(cliente_base, g, status="ativo")
    assert r.status_code == 302 and e.executado_por_id == usuario_base.pk
    n = modelos.Execucao.objects.count()
    r, e2, _ = executar(cliente_base, g, status="rascunho")
    assert r.status_code == 404 and e2 is None and modelos.Execucao.objects.count() == n


@pytest.mark.modulo("m3")
def test_executar_anonimo_get_csrf_e_pk_inexistente(cliente_anonimo, cliente_adm, usuario_adm, liberado, fabrica_fluxo, modelos, cadeia, cfg_http):
    """PRM-01/PRM-08/EXE-01: anônimo → login; GET → 405; sem CSRF → 403; pk inexistente → 404; nada criado."""
    from django.test import Client

    f = fabrica_fluxo(grafo=cadeia(cfg_http(f"{liberado.base}/ok")), status="ativo")
    url = reverse("fluxos:executar", kwargs={"pk": f.pk})
    r = cliente_anonimo.post(url)
    assert r.status_code == 302 and r.url.startswith(reverse("login"))
    assert cliente_adm.get(url).status_code == 405
    c = Client(enforce_csrf_checks=True)
    c.force_login(usuario_adm)
    assert c.post(url).status_code == 403
    assert cliente_adm.post(reverse("fluxos:executar", kwargs={"pk": 999999})).status_code == 404
    assert modelos.Execucao.objects.count() == 0


@pytest.mark.modulo("m3")
def test_resposta_grande_e_truncada_em_1mb_sem_erro(cliente_coordenador, liberado, executar, no, cadeia, cfg_http):
    """SEG-07: resposta > 1 MB é cortada em 1 MB, gravada com truncado=true e NÃO é erro."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/grande")))
    s = no(e, "h1").saida
    assert e.status == "sucesso" and s["truncado"] is True
    assert len(s["corpo"]) <= 1024 * 1024


@pytest.mark.modulo("m3")
def test_limite_conta_corpo_descompactado(cliente_coordenador, liberado, executar, no, cadeia, cfg_http):
    """SEG-07: gzip de 6 MB descompactado (poucos KB no fio) é cortado em 1 MB e marcado truncado."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/gzip")))
    s = no(e, "h1").saida
    assert s["truncado"] is True and len(s["corpo"]) <= 1024 * 1024
    assert e.status == "sucesso"


@pytest.mark.modulo("m3")
def test_corpo_truncado_usado_em_placeholder_falha_o_no_seguinte(cliente_coordenador, liberado, executar, no, cadeia, cfg_http):
    """SEG-07: placeholder que precisa do corpo truncado → nó seguinte falha com resposta_grande."""
    g = cadeia(cfg_http(f"{liberado.base}/grande"), cfg_http(f"{liberado.base}/eco", "POST", corpo='{"a": "{{ anterior.corpo }}"}'))
    _, e, _ = executar(cliente_coordenador, g)
    assert no(e, "h1").status == "sucesso"
    assert no(e, "h2").status == "erro" and no(e, "h2").erro_categoria == "resposta_grande"
    assert no(e, "s").status == "nao_executado"


@pytest.mark.modulo("m3")
def test_timeout_de_leitura_por_setting(cliente_coordenador, liberado, settings, executar, cadeia, cfg_http, no):
    """SEG-07/SEG-16.7: MOTOR_TIMEOUT_LEITURA (padrão 10 s; aqui 1 s) estourado → categoria timeout, execução erro."""
    settings.MOTOR_TIMEOUT_LEITURA = 1
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/lento?s=4")))
    h1 = no(e, "h1")
    assert h1.status == "erro" and h1.erro_categoria == "timeout"
    assert e.status == "erro" and no(e, "s").status == "nao_executado"


@pytest.mark.modulo("m3")
def test_timeout_total_do_no_por_setting(cliente_coordenador, liberado, settings, executar, cadeia, cfg_http, no):
    """SEG-07/SEG-16.7: MOTOR_TIMEOUT_NO (padrão 15 s; aqui 1 s) vale mesmo com leitura folgada."""
    settings.MOTOR_TIMEOUT_LEITURA = 30
    settings.MOTOR_TIMEOUT_NO = 1
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/lento?s=4")))
    assert no(e, "h1").erro_categoria == "timeout"


@pytest.mark.modulo("m3")
def test_timeout_total_da_execucao_por_setting(cliente_coordenador, liberado, settings, executar, cadeia, cfg_http, no):
    """EXE-13/SEG-16.7: MOTOR_TIMEOUT_EXECUCAO (padrão 60 s; aqui 2 s) estourou → nó atual timeout e execução erro."""
    settings.MOTOR_TIMEOUT_EXECUCAO = 2
    g = cadeia(cfg_http(f"{liberado.base}/lento?s=1.3"), cfg_http(f"{liberado.base}/lento?s=1.3"), cfg_http(f"{liberado.base}/ok"))
    _, e, _ = executar(cliente_coordenador, g)
    assert e.status == "erro"
    assert no(e, "h1").status == "sucesso"
    assert no(e, "h2").status == "erro" and no(e, "h2").erro_categoria == "timeout"
    assert no(e, "h3").status == "nao_executado"
    assert liberado.contagem("/ok") == 0


@pytest.mark.modulo("m3")
def test_limite_de_resposta_por_setting(cliente_coordenador, liberado, settings, executar, cadeia, cfg_http, no):
    """SEG-07/SEG-16.7: MOTOR_LIMITE_RESPOSTA (padrão 1 MiB; aqui 2048) corta e marca truncado sem erro."""
    settings.MOTOR_LIMITE_RESPOSTA = 2048
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/grande")))
    s = no(e, "h1").saida
    assert e.status == "sucesso" and s["truncado"] is True and len(s["corpo"]) <= 2048


@pytest.mark.modulo("m3")
def test_max_redirects_por_setting(cliente_coordenador, liberado, settings, executar, cadeia, cfg_http, no):
    """SEG-05/SEG-16.7: MOTOR_MAX_REDIRECTS (padrão 5; aqui 2): 2 redirects ok, o 3º → redirect_excessivo."""
    settings.MOTOR_MAX_REDIRECTS = 2
    _, ok, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/redir/2")))
    assert ok.status == "sucesso"
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/redir/3")))
    assert no(e, "h1").erro_categoria == "redirect_excessivo"


@pytest.mark.modulo("m3")
def test_redirects_ate_5_seguidos(cliente_coordenador, liberado, executar, no, cadeia, cfg_http):
    """SEG-05: 5 redirects seguidos até a resposta final funcionam."""
    _, e5, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/redir/5")))
    assert e5.status == "sucesso" and no(e5, "h1").saida["status"] == 200


@pytest.mark.modulo("m3")
def test_sexto_redirect_e_redirect_excessivo(cliente_coordenador, liberado, executar, no, cadeia, cfg_http):
    """SEG-05: o 6º redirect → erro redirect_excessivo."""
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/redir/6")))
    h1 = no(e, "h1")
    assert h1.status == "erro" and h1.erro_categoria == "redirect_excessivo"
    assert e.status == "erro"


@pytest.mark.modulo("m3")
def test_nao_usa_proxy_do_ambiente(cliente_coordenador, liberado, executar, monkeypatch, cadeia, cfg_http):
    """SEG-07: trust_env=False — HTTP_PROXY do ambiente é ignorado (a conexão vai direto ao servidor local)."""
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    _, e, _ = executar(cliente_coordenador, cadeia(cfg_http(f"{liberado.base}/ok")))
    assert e.status == "sucesso" and liberado.contagem("/ok") == 1
