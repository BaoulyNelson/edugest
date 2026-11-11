"""Vues publiques de compte : authentification, inscription et invitations."""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as vues_auth
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from applications.noyau import saas
from applications.noyau.exceptions import ErreurMetier
from applications.noyau.models import Utilisateur

from . import services
from .authentification import BackendEmail
from .forms import FormulaireCompteInvite, FormulaireConnexion, FormulaireInscriptionEspace

BACKEND = f"{BackendEmail.__module__}.{BackendEmail.__name__}"


class VueConnexion(vues_auth.LoginView):
    template_name = "comptes/connexion.html"
    authentication_form = FormulaireConnexion
    redirect_authenticated_user = True


def inscription_espace(request):
    """Crée le compte administrateur et son premier établissement."""
    if request.user.is_authenticated:
        return redirect("etablissements")
    plan_demande = request.GET.get("plan", "ESSAI").upper()
    if plan_demande not in saas.PLANS_PAR_DEFAUT:
        plan_demande = "ESSAI"
    donnees_formulaire = request.POST.copy() if request.method == "POST" else None
    if donnees_formulaire is not None and not donnees_formulaire.get("plan"):
        donnees_formulaire["plan"] = plan_demande
    formulaire = FormulaireInscriptionEspace(
        donnees_formulaire,
        initial={"plan": plan_demande},
    )
    if request.method == "POST" and formulaire.is_valid():
        donnees = formulaire.cleaned_data
        try:
            utilisateur = services.inscrire_utilisateur(
                donnees["prenom"], donnees["nom"], donnees["email"], donnees["mot_de_passe"],
                url_base=request.build_absolute_uri("/").rstrip("/"),
                username=donnees["username"],
            )
            etablissement = saas.creer_espace(
                utilisateur, donnees["nom_etablissement"], donnees["type_etablissement"],
                code_plan=donnees["plan"],
            )
        except ErreurMetier as erreur:
            formulaire.add_error("email", str(erreur))
        else:
            login(request, utilisateur, backend=BACKEND)
            request.session["etablissement_id"] = etablissement.pk
            messages.success(
                request,
                f"Bienvenue ! Votre espace « {etablissement.nom} » est prêt. "
                f"Essai gratuit de {saas.DUREE_ESSAI_JOURS} jours.",
            )
            return redirect("demarrage")
    return render(request, "comptes/inscription.html", {"formulaire": formulaire})


def verification_courriel(request, jeton):
    try:
        services.verifier_courriel(jeton)
    except ErreurMetier as erreur:
        messages.error(request, str(erreur))
    else:
        messages.success(request, "Votre adresse e-mail est confirmée. Merci !")
    return redirect("tableau_de_bord" if request.user.is_authenticated else "connexion")


@login_required
@require_POST
def renvoyer_verification(request):
    if not request.user.email_verifie:
        try:
            services.envoyer_verification(request.user, request.build_absolute_uri("/").rstrip("/"))
        except ErreurMetier as erreur:
            messages.error(request, str(erreur))
        else:
            if saas.courriel_en_mode_console():
                messages.warning(
                    request,
                    "Le message de confirmation a été affiché dans le terminal du serveur, "
                    "mais n'a pas été livré. Configurez SMTP pour l'envoyer.",
                )
            else:
                messages.success(request, f"Un e-mail de confirmation a été envoyé à {request.user.email}.")
    return redirect(request.POST.get("suite") or "tableau_de_bord")


def invitation(request, jeton):
    """Accepte une invitation et crée au besoin le compte de l'invité."""
    try:
        invitation_obj = services.invitation_par_jeton(jeton)
    except ErreurMetier as erreur:
        return render(request, "comptes/invitation.html", {"erreur": str(erreur)}, status=410)
    contexte = {
        "invitation": invitation_obj,
        "compte_existant": Utilisateur.objects.filter(email__iexact=invitation_obj.email).exists(),
    }
    if request.user.is_authenticated:
        contexte["bon_compte"] = request.user.email.lower() == invitation_obj.email.lower()
        if request.method == "POST" and contexte["bon_compte"]:
            try:
                appartenance = services.accepter_invitation(invitation_obj, request.user)
            except ErreurMetier as erreur:
                messages.error(request, str(erreur))
            else:
                request.session["etablissement_id"] = appartenance.etablissement_id
                messages.success(request, f"Vous avez rejoint « {appartenance.etablissement.nom} ».")
                return redirect("tableau_de_bord")
        return render(request, "comptes/invitation.html", contexte)

    formulaire = FormulaireCompteInvite(request.POST or None)
    if request.method == "POST" and formulaire.is_valid() and not contexte["compte_existant"]:
        donnees = formulaire.cleaned_data
        try:
            utilisateur = services.creer_compte_par_invitation(
                invitation_obj, donnees["prenom"], donnees["nom"], donnees["mot_de_passe"],
                username=donnees["username"],
            )
        except ErreurMetier as erreur:
            messages.error(request, str(erreur))
        else:
            login(request, utilisateur, backend=BACKEND)
            request.session["etablissement_id"] = invitation_obj.etablissement_id
            messages.success(request, f"Compte créé. Bienvenue dans « {invitation_obj.etablissement.nom} ».")
            return redirect("tableau_de_bord")
    contexte["formulaire"] = formulaire
    return render(request, "comptes/invitation.html", contexte)


@login_required
def profil(request):
    return render(request, "comptes/profil.html")