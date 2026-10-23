from django.db import migrations

CARTEIRAS = [
    ("Ativos", "ATIVOS S.A. SECURITIZADORA DE CRÉDITOS FINANCEIROS"),
    ("Ailos", "COOPERATIVA DE CRÉDITO (SISTEMA AILOS)"),
    ("Volvo", "Volvo"),
    ("Toyota", "Toyota"),
    ("BTB", "BTB"),
    ("John Deere", "John Deere"),
]


def semear(apps, schema_editor):
    Carteira = apps.get_model("juridico", "Carteira")
    for nome, empresa in CARTEIRAS:
        if not Carteira.objects.filter(nome__iexact=nome).exists():
            Carteira.objects.create(nome=nome, empresa=empresa)


class Migration(migrations.Migration):
    dependencies = [("juridico", "0001_cadastro_inicial")]
    operations = [migrations.RunPython(semear, migrations.RunPython.noop)]
