from django.db import migrations

GRUPOS = ["Adm", "Coordenador", "Base"]


def criar_grupos(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for nome in GRUPOS:
        Group.objects.get_or_create(name=nome)


def remover_grupos(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=GRUPOS).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("contas", "0001_usuario_inicial"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(criar_grupos, remover_grupos)]
