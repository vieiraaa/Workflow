from django.conf import settings
from django.core.exceptions import ValidationError
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
    setor = models.ForeignKey(
        "contas.Setor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="fluxos",
        verbose_name="setor",
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

    def save(self, *args, **kwargs):
        if self._state.adding and self.setor_id is None:  # SET-04: nasce no setor do dono
            self.setor_id = self.dono.setor_id
        super().save(*args, **kwargs)

    def clean(self):
        """O grafo gravado por qualquer entrada (admin, semeadura) segue o formato canônico."""
        from .grafo import validar

        erros, _ = validar(self.grafo)
        if erros:
            raise ValidationError(
                {"grafo": [f"{erro['mensagem']}" for erro in erros]},
            )
