/* Comportements d'interface : sidebar réductible, confirmations, états de chargement. */
(function () {
  "use strict";
  var racine = document.documentElement;
  var CLE = "edugest.sidebar.reduite";
  try {
    if (window.localStorage.getItem(CLE) === "1") { racine.classList.add("sidebar-reduite"); }
  } catch (e) { /* stockage indisponible : on ignore */ }

  var bascule = document.getElementById("basculerSidebar");
  if (bascule) {
    bascule.addEventListener("click", function () {
      var reduite = racine.classList.toggle("sidebar-reduite");
      try { window.localStorage.setItem(CLE, reduite ? "1" : "0"); } catch (e) { /* ignoré */ }
    });
  }

  document.addEventListener("submit", function (evenement) {
    var formulaire = evenement.target;
    if (formulaire.id === "formulaireAjoutRapide") { return; }
    var message = formulaire.getAttribute("data-confirmer");
    if (message && !window.confirm(message)) { evenement.preventDefault(); return; }
    var bouton = formulaire.querySelector("button[type=submit]:not([data-sans-chargement])");
    if (bouton && !evenement.defaultPrevented) {
      bouton.classList.add("en-chargement");
      bouton.setAttribute("aria-busy", "true");
    }
  });

  function ajouterBasculeMotDePasse(entree) {
    if (!entree || entree.type !== "password" || entree.closest(".champ-mot-de-passe")) { return; }
    var conteneur = document.createElement("div");
    conteneur.className = "champ-mot-de-passe";
    entree.parentNode.insertBefore(conteneur, entree);
    conteneur.appendChild(entree);
    var bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "champ-mot-de-passe__toggle";
    bouton.setAttribute("aria-label", "Afficher le mot de passe");
    bouton.title = "Afficher le mot de passe";
    bouton.innerHTML = '<i class="bi bi-eye" aria-hidden="true"></i>';
    conteneur.appendChild(bouton);
  }

  document.addEventListener("click", function (evenement) {
    var bouton = evenement.target.closest(".champ-mot-de-passe__toggle");
    if (!bouton) { return; }
    evenement.preventDefault();
    var conteneur = bouton.closest(".champ-mot-de-passe");
    var entree = conteneur ? conteneur.querySelector("input") : null;
    if (!entree) { return; }
    var cache = entree.type === "password";
    entree.type = cache ? "text" : "password";
    bouton.setAttribute("aria-label", cache ? "Masquer le mot de passe" : "Afficher le mot de passe");
    bouton.title = cache ? "Masquer le mot de passe" : "Afficher le mot de passe";
    var icone = bouton.querySelector("i");
    if (icone) {
      icone.classList.toggle("bi-eye", !cache);
      icone.classList.toggle("bi-eye-slash", cache);
    }
  });

  document.querySelectorAll('input[type="password"]').forEach(function (entree) {
    ajouterBasculeMotDePasse(entree);
  });

  var minuteriesFiltres = new WeakMap();
  document.addEventListener("change", function (evenement) {
    var controle = evenement.target;
    var formulaire = controle.form;
    if (controle.matches("[data-selection-tout]")) {
      var formulaireSelection = controle.form;
      if (formulaireSelection) {
        formulaireSelection.querySelectorAll("[data-selection-ligne]").forEach(function (ligne) {
          ligne.checked = controle.checked;
        });
      }
      return;
    }
    if (controle.matches("#selecteurLangue, #selecteurLangueMobile") && formulaire) {
      formulaire.requestSubmit();
      return;
    }
    if (formulaire && formulaire.matches("[data-auto-filtre]") &&
        (controle.matches("select") || controle.type === "checkbox" || controle.type === "radio")) {
      formulaire.requestSubmit();
    }
  });
  document.addEventListener("input", function (evenement) {
    var controle = evenement.target;
    var formulaire = controle.form;
    if (!formulaire || !formulaire.matches("[data-auto-filtre]") ||
        !(controle.matches("input[type=search], input[type=text]"))) { return; }
    window.clearTimeout(minuteriesFiltres.get(formulaire));
    minuteriesFiltres.set(formulaire, window.setTimeout(function () {
      formulaire.requestSubmit();
    }, 350));
  });
  document.addEventListener("keydown", function (evenement) {
    var controle = evenement.target;
    if (evenement.key === "Enter" && controle.form &&
        controle.form.matches("[data-auto-filtre]") &&
        controle.matches("input[type=search], input[type=text]")) {
      evenement.preventDefault();
      window.clearTimeout(minuteriesFiltres.get(controle.form));
      controle.form.requestSubmit();
    }
  });

  var modalElement = document.getElementById("modalAjoutRapide");
  var formulaireRapide = document.getElementById("formulaireAjoutRapide");
  var champsRapide = document.getElementById("champsAjoutRapide");
  var erreursRapide = document.getElementById("erreursAjoutRapide");
  var boutonRapide = document.getElementById("confirmerAjoutRapide");
  var selectionCible = null;
  var urlRapide = "";
  var champsRelations = {
    programme: "faculte",
    niveau: "programme",
    classe: "niveau",
    matiere_niveau: "classe"
  };

  function montrerErreur(message) {
    erreursRapide.textContent = message;
    erreursRapide.className = "message message--error mt-3";
  }

  function ajouterChamp(champ) {
    var conteneur = document.createElement("div");
    conteneur.className = "champ";
    var etiquette = document.createElement("label");
    etiquette.textContent = champ.label + (champ.required ? " *" : "");
    etiquette.htmlFor = "ajoutRapide-" + champ.name;
    var entree;
    if (champ.type === "select") {
      entree = document.createElement("select");
      entree.className = "form-select";
      (champ.choices || []).forEach(function (choix) {
        var option = document.createElement("option");
        option.value = choix.value;
        option.textContent = choix.label;
        entree.appendChild(option);
      });
    } else {
      entree = document.createElement("input");
      entree.type = ["date", "email", "number"].indexOf(champ.type) >= 0 ? champ.type : "text";
      entree.className = "form-control";
    }
    entree.id = etiquette.htmlFor;
    entree.name = champ.name;
    entree.required = champ.required;
    if (champ.value !== undefined) { entree.value = champ.value; }
    if (champ.min !== undefined) { entree.min = champ.min; }
    if (champ.step !== undefined) { entree.step = champ.step; }
    conteneur.appendChild(etiquette);
    conteneur.appendChild(entree);
    champsRapide.appendChild(conteneur);
  }

  function valeursContexte(cible) {
    var relation = champsRelations[cible];
    if (!relation || !selectionCible || !selectionCible.form) { return {}; }
    var selecteur = 'select[name="' + relation + '"], select[name$="-' + relation + '"]';
    var champRelation = selectionCible.form.querySelector(selecteur);
    return champRelation && champRelation.value ? { [relation]: champRelation.value } : {};
  }

  function mettreAJourSelecteur(selecteur, id, label) {
    if (!selecteur) { return; }
    var option = Array.prototype.find.call(selecteur.options, function (element) {
      return element.value === String(id);
    });
    if (!option) {
      option = new Option(label, id);
      selecteur.add(option);
    }
    selecteur.value = String(id);
    selecteur.dispatchEvent(new Event("change", { bubbles: true }));
  }

  document.addEventListener("click", function (evenement) {
    var bouton = evenement.target.closest("[data-ajout-rapide-url]");
    if (!bouton || !modalElement || !formulaireRapide) { return; }
    selectionCible = bouton.parentElement.querySelector("select");
    urlRapide = bouton.getAttribute("data-ajout-rapide-url");
    var params = new URLSearchParams(valeursContexte(bouton.dataset.ajoutRapideCible));
    var url = params.toString() ? urlRapide + "?" + params.toString() : urlRapide;
    champsRapide.replaceChildren();
    erreursRapide.textContent = "";
    erreursRapide.className = "mt-3";
    document.getElementById("titreAjoutRapide").textContent = "Ajouter : " + (selectionCible ? selectionCible.labels[0].textContent.replace("*", "").trim() : "une entité");
    boutonRapide.disabled = true;
    fetch(url, { headers: { "Accept": "application/json" }, credentials: "same-origin" })
      .then(function (reponse) {
        return reponse.json().then(function (donnees) {
          if (!reponse.ok) { throw new Error(donnees.error || "Impossible de charger le formulaire d'ajout."); }
          return donnees;
        });
      })
      .then(function (donnees) {
        donnees.fields.forEach(ajouterChamp);
        formulaireRapide.dataset.url = url;
        bootstrap.Modal.getOrCreateInstance(modalElement).show();
        var premierChamp = champsRapide.querySelector("input, select");
        if (premierChamp) { premierChamp.focus(); }
      })
      .catch(function (erreur) { montrerErreur(erreur.message); bootstrap.Modal.getOrCreateInstance(modalElement).show(); })
      .finally(function () { boutonRapide.disabled = false; });
  });

  if (formulaireRapide) {
    formulaireRapide.addEventListener("submit", function (evenement) {
      evenement.preventDefault();
      erreursRapide.textContent = "";
      boutonRapide.disabled = true;
      var csrf = formulaireRapide.querySelector("[name=csrfmiddlewaretoken]");
      fetch(formulaireRapide.dataset.url, {
        method: "POST",
        body: new FormData(formulaireRapide),
        headers: { "Accept": "application/json", "X-CSRFToken": csrf ? csrf.value : "" },
        credentials: "same-origin"
      })
        .then(function (reponse) {
          return reponse.json().then(function (donnees) {
            if (!reponse.ok) {
              if (donnees.errors) {
                var lignes = [];
                Object.keys(donnees.errors).forEach(function (nom) {
                  lignes = lignes.concat(donnees.errors[nom]);
                });
                throw new Error(lignes.join(" "));
              }
              throw new Error(donnees.error || "La création a échoué.");
            }
            return donnees;
          });
        })
        .then(function (donnees) {
          mettreAJourSelecteur(selectionCible, donnees.id, donnees.label);
          Object.keys(donnees.relations || {}).forEach(function (nom) {
            var relation = selectionCible.form.querySelector('select[name="' + nom + '"], select[name$="-' + nom + '"]');
            mettreAJourSelecteur(relation, donnees.relations[nom], relation && relation.options[relation.selectedIndex] ? relation.options[relation.selectedIndex].text : "");
          });
          Object.keys(donnees.champs_parent || {}).forEach(function (nom) {
            var parent = selectionCible.form.querySelector('[name="' + nom + '"], [name$="-' + nom + '"]');
            if (parent) { parent.value = donnees.champs_parent[nom]; }
          });
          bootstrap.Modal.getOrCreateInstance(modalElement).hide();
          if (selectionCible) { selectionCible.focus(); }
        })
        .catch(function (erreur) { montrerErreur(erreur.message); })
        .finally(function () { boutonRapide.disabled = false; });
    });
  }
})();
