from django.db import migrations

from apps.fluxos.migracao import migrar_v1_para_v2


def migrar_grafos(apps, schema_editor):
    """MV2-03: converte os grafos v1 existentes para v2 (execuções antigas não mudam)."""
    Fluxo = apps.get_model("fluxos", "Fluxo")
    for fluxo in Fluxo.objects.all().iterator():
        grafo = fluxo.grafo
        if isinstance(grafo, dict) and grafo.get("versao") == 1:
            fluxo.grafo = migrar_v1_para_v2(grafo)
            fluxo.save(update_fields=["grafo"])


class Migration(migrations.Migration):
    dependencies = [("fluxos", "0002_fluxo_setor")]

    operations = [migrations.RunPython(migrar_grafos, migrations.RunPython.noop)]
