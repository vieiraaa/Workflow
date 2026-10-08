from django.db import migrations


def criar_geral(apps, schema_editor):
    """SET-01: cria o setor "Geral" e vincula a ele tudo o que já existe."""
    Setor = apps.get_model("contas", "Setor")
    geral, _ = Setor.objects.get_or_create(nome="Geral")
    apps.get_model("contas", "Usuario").objects.filter(setor__isnull=True).update(setor=geral)
    apps.get_model("fluxos", "Fluxo").objects.filter(setor__isnull=True).update(setor=geral)
    apps.get_model("execucoes", "Execucao").objects.filter(setor__isnull=True).update(setor=geral)


class Migration(migrations.Migration):
    dependencies = [
        ("contas", "0003_setor_usuario_setor"),
        ("fluxos", "0002_fluxo_setor"),
        ("execucoes", "0002_execucao_setor_execucao_exec_setor_inicio_idx_and_more"),
    ]

    operations = [migrations.RunPython(criar_geral, migrations.RunPython.noop)]
