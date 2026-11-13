from django.db import migrations


PERMISSIONS_PAR_ROLE = {
    "Administrateur de l'établissement": (
        "actualites.consulter", "actualites.gerer", "examens.consulter", "examens.gerer",
    ),
    "Directeur": (
        "actualites.consulter", "actualites.gerer", "examens.consulter", "examens.gerer",
    ),
    "Secrétaire": ("actualites.consulter", "examens.consulter"),
    "Responsable pédagogique": (
        "actualites.consulter", "actualites.gerer", "examens.consulter", "examens.gerer",
    ),
    "Enseignant": ("actualites.consulter", "examens.consulter"),
    "Comptable": ("actualites.consulter", "examens.consulter"),
    "Apprenant": ("actualites.consulter", "examens.consulter"),
    "Parent": ("actualites.consulter", "examens.consulter"),
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
        ("actualites", "0001_initial"),
        ("evaluations", "0005_examen_examen_examen_visibilite_idx_and_more"),
        ("noyau", "0011_utilisateur_photo"),
    ]

    operations = [
        migrations.RunPython(ajouter_permissions, migrations.RunPython.noop),
    ]
