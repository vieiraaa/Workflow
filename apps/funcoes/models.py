from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

ICONES = [
    "zap",
    "list-checks",
    "mail",
    "file-text",
    "bar-chart-3",
    "users",
    "calendar",
    "search",
    "refresh-cw",
    "send",
]
PAPEIS_LIBERAVEIS = [("coordenador", "Coordenador"), ("base", "Usuário base")]


class Funcao(models.Model):
    """Fluxo publicado com cara de botão (FUN-01..13); `grafo_publicado` é cópia congelada."""

    TODOS, SETORES, PAPEIS = "todos", "setores", "papeis"
    LIBERAR_PARA = [(TODOS, "Todos"), (SETORES, "Setores"), (PAPEIS, "Papéis")]

    nome = models.CharField("nome", max_length=80)
    descricao = models.CharField("descrição", max_length=300, blank=True)
    icone = models.CharField(
        "ícone", max_length=20, choices=[(i, i) for i in ICONES], default="zap"
    )
    fluxo = models.ForeignKey(
        "fluxos.Fluxo", on_delete=models.PROTECT, related_name="funcoes", verbose_name="fluxo"
    )
    versao = models.PositiveIntegerField("versão", default=0)
    grafo_publicado = models.JSONField("grafo publicado", default=dict, blank=True)
    publicada_em = models.DateTimeField("publicada em", null=True, blank=True)
    publicada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="funcoes_publicadas",
        verbose_name="publicada por",
    )
    entradas = models.JSONField("entradas", default=list, blank=True)
    liberar_para = models.CharField(
        "liberar para", max_length=10, choices=LIBERAR_PARA, default=TODOS
    )
    setores = models.ManyToManyField(
        "contas.Setor", blank=True, related_name="funcoes", verbose_name="setores"
    )
    papeis = models.JSONField("papéis", default=list, blank=True)
    ativa = models.BooleanField("ativa", default=True)
    criada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="funcoes_criadas",
        verbose_name="criada por",
        editable=False,
    )
    criada_em = models.DateTimeField("criada em", auto_now_add=True)
    atualizada_em = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        verbose_name = "função"
        verbose_name_plural = "funções"
        ordering = ["nome", "pk"]
        constraints = [models.UniqueConstraint(Lower("nome"), name="funcao_nome_unico_ci")]

    def __str__(self):
        return self.nome

    @property
    def publicada(self):
        return self.versao >= 1
