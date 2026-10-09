from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from . import cofre


class Credencial(models.Model):
    """Segredo reutilizável dos nós (CRD-01). O valor só existe cifrado em `dados_cifrados`."""

    BEARER, HEADER, BASIC, SMTP = "bearer", "header", "basic", "smtp"
    TIPOS = [
        (BEARER, "Bearer token"),
        (HEADER, "Header"),
        (BASIC, "Basic (usuário e senha)"),
        (SMTP, "SMTP (e-mail)"),
    ]

    nome = models.CharField("nome", max_length=80)
    tipo = models.CharField("tipo", max_length=10, choices=TIPOS)
    setor = models.ForeignKey(
        "contas.Setor",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="credenciais",
        verbose_name="setor",
    )
    criado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="credenciais_criadas",
        verbose_name="criado por",
    )
    atualizado_em = models.DateTimeField("atualizado em", auto_now=True)
    dados_cifrados = models.TextField("dados cifrados", editable=False)

    class Meta:
        verbose_name = "credencial"
        verbose_name_plural = "credenciais"
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(Lower("nome"), name="credencial_nome_unico_ci"),
        ]

    def __str__(self):
        return self.nome

    @property
    def tipo_rotulo(self):
        return dict(self.TIPOS)[self.tipo]

    def definir_dados(self, dados):
        self.dados_cifrados = cofre.cifrar(dados)

    def dados(self):
        """Dados decifrados (valor, usuario, header_nome, host, porta, tls); ErroCofre se falhar."""
        return cofre.decifrar(self.dados_cifrados)
