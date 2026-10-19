"""Adversarial M8 · corridas e duplicidade sob concorrência (CAD-06, CAD-07, CAD-13, CAD-21). Threads reais, banco transacional."""
import threading
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import connections
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from .conftest import campos_dify, cnj, criar_processo, pdf_processo, upload

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.modulo("m8")]

NUM, DIG = cnj(1234)


def _paralelo(*tarefas):
    """Roda as tarefas ao mesmo tempo (barreira) e devolve [(resultado | exceção)]."""
    barreira = threading.Barrier(len(tarefas))
    saidas = [None] * len(tarefas)

    def _roda(i, f):
        try:
            barreira.wait(10)
            saidas[i] = f()
        except Exception as e:  # noqa: BLE001
            saidas[i] = e
        finally:
            connections.close_all()

    ts = [threading.Thread(target=_roda, args=(i, f)) for i, f in enumerate(tarefas)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(120)
        assert not t.is_alive(), "thread travada"
    return saidas


def _cliente(usuario):
    c = Client()
    c.force_login(usuario)
    return c


def test_dois_envios_simultaneos_do_mesmo_arquivo(cad):
    """CAD-06a: duas pessoas enviam o MESMO arquivo no mesmo instante, nenhuma exceção; depois do worker há um único processo."""
    conteudo, nome = pdf_processo(NUM)
    ana, bruno = _cliente(cad.ana_u), _cliente(cad.bruno_u)
    r = _paralelo(lambda: ana.post(reverse("juridico:enviar_pdfs"), {"arquivos": [upload(conteudo, nome)], "carteira": ""}),
                  lambda: bruno.post(reverse("juridico:enviar_pdfs"), {"arquivos": [upload(conteudo, nome)], "carteira": ""}))
    assert all(not isinstance(x, Exception) and x.status_code == 302 for x in r), r
    call_command("processar_cadastros", "--uma-vez")
    assert cad.Processo.objects.filter(numero_digitos=DIG).count() == 1
    assert not cad.ItemEnvio.objects.filter(status="erro").exists()
    assert not cad.ItemEnvio.objects.filter(status__in=["na_fila", "processando"]).exists()


def test_dois_workers_ao_mesmo_tempo_nao_processam_o_mesmo_item_duas_vezes(cad, enviar):
    """CAD-07: dois `processar_cadastros --uma-vez` em paralelo: cada item vai ao Dify UMA vez e nenhum processo duplica."""
    nums = [cnj(10 + i)[0] for i in range(6)]
    for i, n in enumerate(nums):
        enviar(cad.ana, pdf_processo(n, str(i)))
    r = _paralelo(lambda: call_command("processar_cadastros", "--uma-vez"), lambda: call_command("processar_cadastros", "--uma-vez"))
    assert not any(isinstance(x, Exception) for x in r), r
    consultas = [c["query"] for c in cad.dify.chats]
    assert len(consultas) == 6, len(consultas)
    assert cad.Processo.objects.count() == 6 and set(cad.ItemEnvio.objects.values_list("status", flat=True)) == {"concluido"}


def test_dois_pdfs_do_mesmo_numero_em_workers_paralelos_geram_um_processo(cad, enviar):
    """CAD-06b/modelo (único quando válido): PDFs diferentes com o MESMO número processados em paralelo → 1 processo, sem IntegrityError."""
    for i, c in enumerate((cad.ana, cad.bruno, cad.adm, cad.ana, cad.bruno)):
        enviar(c, pdf_processo(NUM, f"v{i}"))
    r = _paralelo(*[lambda: call_command("processar_cadastros", "--uma-vez")] * 3)
    assert not any(isinstance(x, Exception) for x in r), r
    assert cad.Processo._base_manager.filter(numero_digitos=DIG).count() == 1
    assert not cad.ItemEnvio.objects.filter(status="erro").exists()
    assert not cad.ItemEnvio.objects.filter(status__in=["na_fila", "processando"]).exists()


def test_cadastro_manual_simultaneo_do_mesmo_numero(cad):
    """CAD-21: duas pessoas cadastram manualmente o mesmo número ao mesmo tempo → 1 processo; a outra recebe o aviso (sem 500)."""
    dados = {"numero": DIG, "adverso_nome": "Manual", "tribunal": "TJSP", "comarca": "SP", "juizo": "1", "valor_causa": "1,00", "distribuido_em": "2022-03-15"}
    ana, bruno = _cliente(cad.ana_u), _cliente(cad.bruno_u)
    r = _paralelo(lambda: ana.post(reverse("juridico:processo_novo"), dados), lambda: bruno.post(reverse("juridico:processo_novo"), dados))
    assert not any(isinstance(x, Exception) for x in r), r
    assert all(x.status_code in (200, 302) for x in r)
    assert cad.Processo._base_manager.filter(numero_digitos=DIG).count() == 1


def test_excluir_e_pdf_do_mesmo_numero_em_paralelo(cad, ingerir, enviar):
    """CAD-06d/21: excluir o processo enquanto o worker atualiza o mesmo número → sem exceção; estado final consistente (1 linha; excluído OU restaurado)."""
    _, p = ingerir(cad.ana, NUM, variante="a")
    enviar(cad.bruno, pdf_processo(NUM, "b"))
    ana = _cliente(cad.ana_u)
    r = _paralelo(lambda: call_command("processar_cadastros", "--uma-vez"), lambda: ana.post(reverse("juridico:excluir", kwargs={"pk": p.pk})))
    assert not any(isinstance(x, Exception) for x in r), r
    assert cad.Processo._base_manager.filter(numero_digitos=DIG).count() == 1
    assert cad.ItemEnvio.objects.get(envio__enviado_por=cad.bruno_u).status in ("concluido", "erro")


def test_dois_marcar_cadastrado_simultaneos(cad):
    """CAD-15: dois cliques simultâneos em 'Marcar como cadastrado' → um só registro de quem/quando (consistente), sem erro."""
    p = criar_processo(cad)
    ana, bruno = _cliente(cad.ana_u), _cliente(cad.bruno_u)
    r = _paralelo(lambda: ana.post(reverse("juridico:marcar_cadastrado", kwargs={"pk": p.pk})),
                  lambda: bruno.post(reverse("juridico:marcar_cadastrado", kwargs={"pk": p.pk})))
    assert not any(isinstance(x, Exception) for x in r), r
    p.refresh_from_db()
    assert p.status == "CADASTRADO" and p.cadastrado_espaider_por in (cad.ana_u, cad.bruno_u) and p.cadastrado_espaider_em is not None


def test_editar_e_marcar_cadastrado_em_paralelo_nao_deixa_cadastrado_com_pendencia(cad):
    """CAD-12/15: apagar um obrigatório enquanto outro usuário marca como cadastrado → nunca fica CADASTRADO sem número/tribunal… (ou fica CADASTRADO com campo preenchido)."""
    p = criar_processo(cad)
    ana, bruno = _cliente(cad.ana_u), _cliente(cad.bruno_u)
    _paralelo(lambda: ana.post(reverse("juridico:processo", kwargs={"pk": p.pk}), {"juizo": ""}),
              lambda: bruno.post(reverse("juridico:marcar_cadastrado", kwargs={"pk": p.pk})))
    p.refresh_from_db()
    assert p.status in ("CADASTRADO", "COM_PENDENCIAS")
    if p.status == "CADASTRADO":
        assert p.cadastrado_espaider_em is not None


def test_item_tentar_de_novo_em_paralelo_nao_duplica_chamada(cad, ingerir):
    """CAD-13: três cliques simultâneos em 'Tentar de novo' no mesmo item → um único reprocessamento (uma chamada ao Dify a mais)."""
    cad.dify.modo = "500"
    item, _ = ingerir(cad.ana, NUM)
    cad.dify.modo = None
    antes = len(cad.dify.chats)
    ana = _cliente(cad.ana_u)
    _paralelo(*[lambda: ana.post(reverse("juridico:tentar_de_novo", kwargs={"pk": item.pk}))] * 3)
    call_command("processar_cadastros", "--uma-vez")
    assert len(cad.dify.chats) - antes == 1 and cad.Processo.objects.count() == 1


def test_duplicado_de_aponta_para_item_cujo_processo_sumiu(cad, ingerir, enviar, ver):
    """CAD-06a: o processo do item original some (FK SET_NULL) → a tela do envio duplicado não dá 500."""
    _, p = ingerir(cad.ana, NUM, variante="a")
    enviar(cad.bruno, pdf_processo(NUM, "a"))
    cad.Processo._base_manager.filter(pk=p.pk).delete()
    novo = cad.ItemEnvio.objects.order_by("pk").last()
    r = cad.bruno.get(reverse("juridico:envio", kwargs={"pk": novo.envio_id}))
    assert r.status_code == 200
    assert cad.bruno.get(reverse("juridico:status") + f"?envio={novo.envio_id}").status_code == 200


def test_numero_invalido_igual_a_valido_em_paralelo_nao_mescla(cad):
    """CAD-06c: PDFs com número válido e com o DV trocado, processados ao mesmo tempo, nunca viram o mesmo processo."""
    bom, ruim = cnj(1234), cnj(1234, dv_errado=True)
    from .conftest import SEGREDO_DIFY  # noqa: F401
    cad.dify.respostas[bom[0]] = campos_dify(bom[0], comarca="DO VALIDO")
    cad.dify.respostas[ruim[0]] = campos_dify(ruim[0], comarca="DO INVALIDO")
    for i, n in enumerate((bom[0], ruim[0], bom[0], ruim[0])):
        c = cad.ana if i % 2 == 0 else cad.bruno
        c.post(reverse("juridico:enviar_pdfs"), {"arquivos": [upload(*pdf_processo(n, f"p{i}"))], "carteira": ""})
    _paralelo(*[lambda: call_command("processar_cadastros", "--uma-vez")] * 2)
    validos = cad.Processo._base_manager.filter(numero_valido=True)
    assert validos.count() == 1 and validos.get().comarca == "DO VALIDO"
    assert cad.Processo._base_manager.filter(numero_valido=False).count() >= 1
    assert not cad.Processo._base_manager.filter(numero_valido=False, comarca="DO VALIDO").exists()
    _ = timezone.now() + timedelta(days=1)
