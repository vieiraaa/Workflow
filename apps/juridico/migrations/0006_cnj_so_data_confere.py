"""D-062: processo 'divergente' só pela data de distribuição passa a 'confere' (a divergência
fica registrada em cnj_divergencias e aparece como aviso na ficha)."""

from django.db import migrations

SO_AVISO = ("distribuído em ",)  # cópia de mescla.SO_AVISO: migração não importa código vivo


def para_confere(apps, schema_editor):
    Processo = apps.get_model("juridico", "Processo")
    for p in Processo.objects.filter(cnj_validacao="divergente").only("cnj_divergencias"):
        if p.cnj_divergencias and all(d.startswith(SO_AVISO) for d in p.cnj_divergencias):
            Processo.objects.filter(pk=p.pk).update(cnj_validacao="confere")


def para_divergente(apps, schema_editor):
    Processo = apps.get_model("juridico", "Processo")
    for p in Processo.objects.filter(cnj_validacao="confere").only("cnj_divergencias"):
        if p.cnj_divergencias:
            Processo.objects.filter(pk=p.pk).update(cnj_validacao="divergente")


class Migration(migrations.Migration):
    dependencies = [
        ("juridico", "0005_log_chamadas_api"),
    ]

    operations = [migrations.RunPython(para_confere, para_divergente)]
