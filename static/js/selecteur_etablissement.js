/* Changement immédiat d'établissement depuis l'en-tête de la sidebar. */
(function () {
  "use strict";
  var selecteur = document.getElementById("selecteurEtablissement");
  if (!selecteur || !selecteur.form) { return; }
  selecteur.addEventListener("change", function () {
    if (selecteur.value) { selecteur.form.requestSubmit(); }
  });
}());
