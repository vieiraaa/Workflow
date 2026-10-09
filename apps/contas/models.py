from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.db.models.functions import Lower


class UsuarioManager(UserManager):
    use_in_migrations = True

    def get_by_natural_key(self, email):
        return self.get(email__iexact=(email or "").strip())

    def _create_user_object(self, email, password, **extra_fields):
        email = self.normalize_email((email or "").strip()).lower()
        usuario = self.model(email=email, **extra_fields)
        usuario.password = None
        if password:
            usuario.set_password(password)
        else:
            usuario.set_unusable_password()
        return usuario

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        usuario = self._create_user_object(email, password, **extra_fields)
        usuario.save(using=self._db)
        return usuario

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class Setor(models.Model):
    """Setor da organização (SET-01..06). Nunca é excluído: preserva o histórico; só se desativa."""

    nome = models.CharField("nome", max_length=80)
    ativo = models.BooleanField("ativo", default=True)
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        verbose_name = "setor"
        verbose_name_plural = "setores"
        ordering = ["nome"]
        constraints = [
            models.UniqueConstraint(Lower("nome"), name="setor_nome_unico_ci"),
        ]

    def __str__(self):
        return self.nome


class Usuario(AbstractUser):
    """Usuário do produto: login por e-mail único. O papel vem de um Group (ver permissoes.py)."""

    username = None
    email = models.EmailField("e-mail", unique=True)
    nome = models.CharField("nome", max_length=120)
    setor = models.ForeignKey(
        Setor,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="usuarios",
        verbose_name="setor",
    )
    criado_em = models.DateTimeField("criado em", auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nome"]

    objects = UsuarioManager()

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nome or self.email
