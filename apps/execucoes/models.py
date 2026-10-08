from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

LIMITE_EXECUTANDO = timedelta(minutes=5)
RESUMO_INTERROMPIDA = "Execução interrompida"


class Execucao(models.Model):
    """Uma execução de fluxo. Guarda o snapshot do grafo e o nome: o histórico não depende
    do fluxo (EXE-03, FLX-03). Formato dos nós em docs/spec/estados.yaml (EXE-12)."""

    EXECUTANDO, SUCESSO, ERRO = "executando", "sucesso", "erro"
    STATUS = [(EXECUTANDO, "Executando"), (SUCESSO, "Sucesso"), (ERRO, "Erro")]

    fluxo = models.ForeignKey(
        "fluxos.Fluxo",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="execucoes",
        verbose_name="fluxo",
    )
    fluxo_nome = models.CharField("nome do fluxo", max_length=120)
    grafo_snapshot = models.JSONField("grafo (snapshot)", default=dict)
    executado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="execucoes",
        verbose_name="executado por",
    )
    status = models.CharField("status", max_length=12, choices=STATUS, default=EXECUTANDO)
    iniciada_em = models.DateTimeField("iniciada em", default=timezone.now, db_index=True)
    finalizada_em = models.DateTimeField("finalizada em", null=True, blank=True)
    erro_resumo = models.TextField("resumo do erro", blank=True)

    class Meta:
        verbose_name = "execução"
        verbose_name_plural = "execuções"
        ordering = ["-iniciada_em", "-pk"]

    def __str__(self):
        return f"{self.fluxo_nome} · {self.iniciada_em:%d/%m/%Y %H:%M}"

    @property
    def interrompida(self):
        """EXE-10: 'executando' há mais de 5 minutos (processo morto) é tratada como erro."""
        return (
            self.status == self.EXECUTANDO and timezone.now() - self.iniciada_em > LIMITE_EXECUTANDO
        )

    @property
    def status_efetivo(self):
        return self.ERRO if self.interrompida else self.status

    @property
    def status_rotulo(self):
        return dict(self.STATUS)[self.status_efetivo]

    @property
    def erro_resumo_efetivo(self):
        return RESUMO_INTERROMPIDA if self.interrompida else self.erro_resumo

    @property
    def duracao_ms(self):
        """Duração em ms; None enquanto não terminou (e não foi dada como interrompida)."""
        if self.finalizada_em is None:
            return None
        return int((self.finalizada_em - self.iniciada_em).total_seconds() * 1000)


class ExecucaoNo(models.Model):
    """Resultado de um nó numa execução (entrada/saída já com segredos mascarados, SEG-09)."""

    SUCESSO, ERRO, NAO_EXECUTADO = "sucesso", "erro", "nao_executado"
    STATUS = [(SUCESSO, "Sucesso"), (ERRO, "Erro"), (NAO_EXECUTADO, "Não executado")]

    execucao = models.ForeignKey(Execucao, on_delete=models.CASCADE, related_name="nos")
    no_id = models.CharField("id do nó", max_length=40)
    no_tipo = models.CharField("tipo do nó", max_length=20)
    no_titulo = models.CharField("título do nó", max_length=80, blank=True)
    ordem = models.PositiveIntegerField("ordem")
    status = models.CharField("status", max_length=14, choices=STATUS)
    entrada = models.JSONField("entrada", default=dict)
    saida = models.JSONField("saída", default=dict)
    erro_categoria = models.CharField(  # noqa: DJ001 - a spec define a categoria como texto nulo
        "categoria do erro", max_length=30, null=True, blank=True
    )
    erro_mensagem = models.TextField("mensagem do erro", blank=True)
    duracao_ms = models.PositiveIntegerField("duração (ms)", default=0)

    class Meta:
        verbose_name = "execução de nó"
        verbose_name_plural = "execuções de nós"
        ordering = ["execucao", "ordem"]
        constraints = [
            models.UniqueConstraint(fields=["execucao", "ordem"], name="execucaono_ordem_unica"),
        ]

    def __str__(self):
        return f"{self.ordem}. {self.no_titulo or self.no_id}"
