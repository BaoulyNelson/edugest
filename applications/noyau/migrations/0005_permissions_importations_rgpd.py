from django.db import migrations


PERMISSIONS_PAR_ROLE = {
    "Administrateur de l'établissement": (
        "importations.apprenants", "importations.personnel", "rgpd.gerer", "rgpd.demander",
        "finances.consulter_propres",
    ),
    "Directeur": ("importations.apprenants", "importations.personnel", "rgpd.gerer"),
    "Secrétaire": ("importations.apprenants",),
    "Responsable pédagogique": ("importations.apprenants", "rgpd.gerer"),
    "Apprenant": ("rgpd.demander", "finances.consulter_propres"),
    "Parent": ("rgpd.demander", "finances.consulter_propres"),
}


def ajouter_permissions(apps, schema_editor):
    Role = apps.get_model("noyau", "Role")
    for nom_role, permissions in PERMISSIONS_PAR_ROLE.items():
        for role in Role.objects.filter(nom=nom_role):
            codes = list(role.codes or [])
            role.codes = list(dict.fromkeys([*codes, *permissions]))
            role.save(update_fields=["codes"])


class Migration(migrations.Migration):

    dependencies = [
        ("noyau", "0004_parametresetablissement_retention_annees_and_more"),
        ("apprenants", "0003_apprenant_anonymise_apprenant_anonymise_le_and_more"),
        ("importations", "0001_initial"),
        ("rgpd", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(ajouter_permissions, migrations.RunPython.noop),
    ]
