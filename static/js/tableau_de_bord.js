document.addEventListener("DOMContentLoaded", () => {
  const dataElement = document.getElementById("donnees-graphiques-tableau");
  if (!dataElement) return;

  const donnees = JSON.parse(dataElement.textContent);
  const couleurs = ["#146c72", "#e05b55", "#e4a63b", "#9aa9ad"];
  const animation = window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ? false
    : { duration: 750, easing: "easeOutQuart" };
  const optionsCommunes = {
    responsive: true,
    maintainAspectRatio: false,
    animation,
    interaction: { intersect: false, mode: "index" },
    plugins: {
      tooltip: {
        backgroundColor: "#123d42",
        titleFont: { weight: "600" },
        bodyFont: { weight: "500" },
        padding: 12,
        cornerRadius: 8,
        displayColors: true,
      },
    },
  };

  function afficher(id, videId, valeurs, configuration, contientDesDonnees = valeurs.some(
    (valeur) => valeur !== null && valeur > 0,
  )) {
    const canvas = document.getElementById(id);
    const vide = document.getElementById(videId);
    if (!contientDesDonnees) {
      canvas.hidden = true;
      vide.hidden = false;
      return;
    }
    new Chart(canvas, configuration);
  }

  if (donnees.effectifs) {
    afficher(
      "graphique-effectifs",
      "vide-graphique-effectifs",
      donnees.effectifs.values,
      {
        type: "bar",
        data: {
          labels: donnees.effectifs.labels,
          datasets: [{
            label: donnees.effectifs.series_label,
            data: donnees.effectifs.values,
            backgroundColor: "#267f83",
            hoverBackgroundColor: "#145b62",
            borderRadius: 6,
            maxBarThickness: 42,
          }],
        },
        options: {
          ...optionsCommunes,
          plugins: { ...optionsCommunes.plugins, legend: { display: false } },
          scales: {
            x: { grid: { display: false }, ticks: { color: "#627477" } },
            y: {
              beginAtZero: true,
              ticks: { precision: 0, color: "#627477" },
              grid: { color: "rgba(98,116,119,.12)" },
            },
          },
        },
      },
    );
  }

  if (donnees.paiements) {
    afficher(
      "graphique-paiements",
      "vide-graphique-paiements",
      donnees.paiements.values,
      {
        type: "doughnut",
        data: {
          labels: donnees.paiements.labels,
          datasets: [{
            data: donnees.paiements.values,
            backgroundColor: couleurs,
            hoverOffset: 7,
            borderColor: "#fff",
            borderWidth: 3,
          }],
        },
        options: {
          ...optionsCommunes,
          cutout: "68%",
          plugins: {
            ...optionsCommunes.plugins,
            legend: {
              position: "bottom",
              labels: { usePointStyle: true, pointStyle: "circle", padding: 18, color: "#42575a" },
            },
          },
        },
      },
    );
  }

  if (donnees.moyennes) {
    afficher(
      "graphique-moyennes",
      "vide-graphique-moyennes",
      donnees.moyennes.values,
      {
        type: "line",
        data: {
          labels: donnees.moyennes.labels,
          datasets: [{
            label: donnees.moyennes.series_label,
            data: donnees.moyennes.values,
            borderColor: "#146c72",
            backgroundColor: "rgba(38,127,131,.13)",
            pointBackgroundColor: "#fff",
            pointBorderColor: "#146c72",
            pointBorderWidth: 2,
            pointRadius: 4,
            pointHoverRadius: 6,
            borderWidth: 3,
            fill: true,
            tension: .35,
            spanGaps: false,
          }],
        },
        options: {
          ...optionsCommunes,
          plugins: { ...optionsCommunes.plugins, legend: { display: false } },
          scales: {
            x: { grid: { display: false }, ticks: { color: "#627477" } },
            y: {
              beginAtZero: true,
              suggestedMax: donnees.moyennes.echelle,
              ticks: { color: "#627477" },
              grid: { color: "rgba(98,116,119,.12)" },
            },
          },
        },
      },
      donnees.moyennes.values.some((valeur) => valeur !== null),
    );
  }
});
