import secrets

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.contas.models import Usuario

USUARIOS_DEMO = [
    ("adm@exemplo.test", "Ana Admin", "Adm"),
    ("coord@exemplo.test", "Caio Coordenador", "Coordenador"),
    ("base@exemplo.test", "Bia Base", "Base"),
]


class Command(BaseCommand):
    help = "Cria 3 usuários fictícios (Adm, Coordenador, Base). Idempotente."

    def add_arguments(self, parser):
        parser.add_argument("--senha", help="Senha dos 3 usuários (padrão: aleatória e impressa).")

    def handle(self, *args, **opcoes):
        senha = opcoes["senha"]
        gerada = senha is None
        if gerada:
            senha = secrets.token_urlsafe(14)
        criados = 0
        for email, nome, grupo in USUARIOS_DEMO:
            usuario, novo = Usuario.objects.get_or_create(email=email, defaults={"nome": nome})
            if novo:
                usuario.set_password(senha)
                usuario.save()
                criados += 1
            usuario.groups.set([Group.objects.get(name=grupo)])
        self.stdout.write(
            f"Usuários de demo: {criados} criado(s), {len(USUARIOS_DEMO) - criados} já existiam."
        )
        if gerada and criados:
            self.stdout.write(f"Senha gerada (só para dev): {senha}")
