import importlib
import secrets

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.contas.models import Setor, Usuario

USUARIOS_DEMO = [
    ("adm@exemplo.test", "Ana Admin", "Adm"),
    ("coord@exemplo.test", "Caio Coordenador", "Coordenador"),
    ("base@exemplo.test", "Bia Base", "Base"),
]
SEM_PAPEL = ("sem@exemplo.test", "Sônia Sem Papel", None)
GRUPOS_EXTRAS = ["Adm", "Coordenador", "Base", "Base", "Base"]


class Command(BaseCommand):
    help = "Cria usuários fictícios e, se existirem, fluxos de exemplo. Idempotente."

    def add_arguments(self, parser):
        parser.add_argument("--senha", help="Senha dos usuários (padrão: aleatória e impressa).")
        parser.add_argument("--extras", type=int, default=0, help="Usuários fictícios adicionais.")
        parser.add_argument(
            "--com-sem-papel", action="store_true", help="Cria também um usuário sem papel."
        )

    def _garantir(self, email, nome, grupo, senha, **extra):
        geral, _ = Setor.objects.get_or_create(nome="Geral")
        usuario, novo = Usuario.objects.get_or_create(
            email=email, defaults={"nome": nome, "setor": geral, **extra}
        )
        if novo:
            usuario.set_password(senha)
            usuario.save()
        usuario.groups.set([Group.objects.get(name=grupo)] if grupo else [])
        return novo

    def handle(self, *args, **opcoes):
        senha = opcoes["senha"]
        gerada = senha is None
        if gerada:
            senha = secrets.token_urlsafe(14)
        pessoas = list(USUARIOS_DEMO)
        if opcoes["com_sem_papel"]:
            pessoas.append(SEM_PAPEL)
        criados = sum(self._garantir(e, n, g, senha) for e, n, g in pessoas)
        for i in range(opcoes["extras"]):
            criados += self._garantir(
                f"pessoa{i:02d}@exemplo.test",
                f"Pessoa Fictícia {i:02d}",
                GRUPOS_EXTRAS[i % len(GRUPOS_EXTRAS)],
                senha,
                is_active=i % 7 != 0,
            )
        self.stdout.write(f"Usuários de demo: {criados} criado(s).")
        try:  # gancho: fluxos de exemplo, quando o model Fluxo existir (M2)
            demo = importlib.import_module("apps.fluxos.demo")
        except ImportError:
            demo = None
        if demo is not None:
            for nome in ("Financeiro", "Atendimento"):
                setor = Setor.objects.get_or_create(nome=nome)[0]
                demo.pessoas_do_setor(setor, senha)
            demo.semear()
        if gerada and criados:
            self.stdout.write(f"Senha gerada (só para dev): {senha}")
