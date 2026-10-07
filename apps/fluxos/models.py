from django.conf import settings
from django.db import models


def grafo_inicial():
    """Grafo de um fluxo novo: só o gatilho (FLX-02)."""
    return {
        "versao": 1,
        "nos": [
            {
                "id": "n1",
                "tipo": "gatilho",
                "titulo": "Início",
                "posicao": {"x": 80, "y": 120},
                "config": {},
            }
        ],
        "arestas": [],
    }


class Fluxo(models.Model):
    """Workflow: Gatilho manual → Requisição HTTP → Saída. O grafo segue docs/spec/grafo.yaml."""

    RASCUNHO = "rascunho"
    ATIVO = "ativo"
    STATUS = [(RASCUNHO, "Rascunho"), (ATIVO, "Ativo")]

    nome = models.CharField("nome", max_length=120)
    descricao = models.TextField("descrição", max_length=1000, blank=True)
    dono = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="fluxos",
        verbose_name="dono",
        editable=False,
    )
    status = models.CharField("status", max_length=10, choices=STATUS, default=RASCUNHO)
    grafo = models.JSONField("grafo", default=grafo_inicial)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        verbose_name = "fluxo"
        verbose_name_plural = "fluxos"
        ordering = ["-atualizado_em", "-pk"]

    def __str__(self):
        return self.nome
