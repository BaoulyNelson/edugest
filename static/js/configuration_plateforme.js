(() => {
  const texte = (id, cible, valeurParDefaut = "") => {
    const champ = document.getElementById(`id_${id}`);
    const sortie = document.querySelector(`[data-apercu-${cible}]`);
    if (!champ || !sortie) return;
    const mettreAJour = () => {
      sortie.textContent = champ.value.trim() || valeurParDefaut;
    };
    champ.addEventListener("input", mettreAJour);
    champ.addEventListener("change", mettreAJour);
  };

  texte("nom", "nom", "EduGest");
  texte("nom", "pied-nom", "EduGest");
  texte("slogan", "slogan", "Votre slogan apparaîtra ici.");
  texte("pied_de_page", "pied-texte", "Votre signature institutionnelle apparaîtra ici.");

  const nom = document.getElementById("id_nom");
  const nomCourt = document.getElementById("id_nom_court");
  const apercuNomCourt = document.querySelector("[data-apercu-nom-court]");
  const actualiserNomCourt = () => {
    if (nomCourt && apercuNomCourt) {
      apercuNomCourt.textContent = nomCourt.value.trim() || nom?.value.trim() || "EduGest";
    }
  };
  nom?.addEventListener("input", actualiserNomCourt);
  nomCourt?.addEventListener("input", actualiserNomCourt);

  const email = document.getElementById("id_email");
  const telephone = document.getElementById("id_telephone");
  const siteWeb = document.getElementById("id_site_web");
  const adresse = document.getElementById("id_adresse");
  const coordonnees = document.querySelector("[data-apercu-coordonnees]");
  const actualiserCoordonnees = () => {
    if (!coordonnees) return;
    coordonnees.textContent = [
      email?.value.trim(), telephone?.value.trim(), siteWeb?.value.trim(), adresse?.value.trim(),
    ].filter(Boolean).join(" · ");
  };
  email?.addEventListener("input", actualiserCoordonnees);
  telephone?.addEventListener("input", actualiserCoordonnees);
  siteWeb?.addEventListener("input", actualiserCoordonnees);
  adresse?.addEventListener("input", actualiserCoordonnees);

  const champLogo = document.getElementById("id_logo");
  if (champLogo) {
    champLogo.addEventListener("change", () => {
      const fichier = champLogo.files?.[0];
      if (!fichier) return;
      const apercu = document.querySelector("[data-apercu-logo]");
      if (apercu) {
        apercu.src = URL.createObjectURL(fichier);
        return;
      }
      const icone = document.querySelector("[data-apercu-icone]");
      if (icone) {
        const image = document.createElement("img");
        image.className = "configuration-plateforme__logo";
        image.dataset.apercuLogo = "";
        image.alt = "";
        image.src = URL.createObjectURL(fichier);
        icone.replaceWith(image);
      }
    });
  }
})();
