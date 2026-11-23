/* FORM'AO : petites améliorations d'usage. Tout fonctionne aussi sans JavaScript. */
(function () {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const enSaisie = (el) => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));

  /* Messages : fermeture, disparition automatique (sauf ceux qui proposent « Annuler »). */
  function messages() {
    $$(".messages li").forEach((li) => {
      const fermer = () => { li.classList.add("sort"); setTimeout(() => li.remove(), 250); };
      const b = $(".fermer", li);
      if (b) b.addEventListener("click", fermer);
      if (li.hasAttribute("data-disparait")) setTimeout(fermer, 6000);
    });
  }

  /* No-Go : la petite fenêtre du motif se ferme avec Échap ou un clic à côté, et prend le focus. */
  function nogo() {
    $$("details.nogo-motif").forEach((d) => {
      d.addEventListener("toggle", () => {
        if (d.open) {
          $$("details.nogo-motif[open]").forEach((x) => { if (x !== d) x.open = false; });
          const champ = $("input[name=motif]", d);
          if (champ) setTimeout(() => champ.focus(), 0);
        }
      });
    });
    document.addEventListener("click", (e) => {
      $$("details.nogo-motif[open]").forEach((d) => { if (!d.contains(e.target)) d.open = false; });
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") $$("details.nogo-motif[open]").forEach((d) => { d.open = false; $("summary", d).focus(); });
    });
  }

  /* Raccourcis : « / » recherche ; sur la liste de tri, j/k pour se déplacer, g = Go, n = No-Go, Entrée = ouvrir. */
  function raccourcis() {
    const lignes = $$(".liste .ligne");
    let i = -1;
    const choisir = (n) => {
      if (!lignes.length) return;
      i = Math.max(0, Math.min(lignes.length - 1, n));
      lignes.forEach((l) => l.classList.remove("choisie"));
      lignes[i].classList.add("choisie");
      lignes[i].scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
    };
    document.addEventListener("keydown", (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey || enSaisie(document.activeElement)) return;
      if (e.key === "/") { const r = $("#recherche"); if (r) { e.preventDefault(); r.focus(); r.select(); } return; }
      if (!lignes.length) return;
      if (e.key === "j" || e.key === "ArrowDown" && e.shiftKey) { e.preventDefault(); choisir(i + 1); }
      else if (e.key === "k" || e.key === "ArrowUp" && e.shiftKey) { e.preventDefault(); choisir(i - 1); }
      else if (i >= 0 && e.key === "g") { const b = $(".decision button.btn:not(.secondaire)", lignes[i]); if (b) b.click(); }
      else if (i >= 0 && e.key === "n") { const d = $("details.nogo-motif", lignes[i]); if (d) { e.preventDefault(); d.open = true; } }
      else if (i >= 0 && e.key === "Enter") { const a = $(".ligne-titre", lignes[i]); if (a) a.click(); }
    });
  }

  /* Personnalisation de l'accueil : glisser-déposer et flèches, ordre envoyé à l'enregistrement. */
  function personnaliser() {
    const liste = $("#liste-widgets");
    const form = $("#form-perso");
    if (!liste || !form) return;
    let tire = null;
    liste.addEventListener("dragstart", (e) => {
      tire = e.target.closest(".choix-widget");
      if (!tire) return;
      tire.classList.add("tire");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", tire.dataset.cle);
    });
    liste.addEventListener("dragend", () => { if (tire) tire.classList.remove("tire"); tire = null; });
    liste.addEventListener("dragover", (e) => {
      if (!tire) return;
      e.preventDefault();
      const cible = e.target.closest(".choix-widget");
      if (!cible || cible === tire) return;
      const r = cible.getBoundingClientRect();
      liste.insertBefore(tire, e.clientY > r.top + r.height / 2 ? cible.nextSibling : cible);
    });
    liste.addEventListener("click", (e) => {
      const li = e.target.closest(".choix-widget");
      if (!li) return;
      if (e.target.closest(".monter") && li.previousElementSibling) { liste.insertBefore(li, li.previousElementSibling); $(".monter", li).focus(); }
      if (e.target.closest(".descendre") && li.nextElementSibling) { liste.insertBefore(li.nextElementSibling, li); $(".descendre", li).focus(); }
    });
    form.addEventListener("submit", () => {
      $("#ordre").value = $$(".choix-widget", liste).map((li) => li.dataset.cle).join(",");
    });
    const section = $("#personnaliser");
    if (section) section.scrollIntoView({ block: "start" });
  }

  document.addEventListener("DOMContentLoaded", () => { messages(); nogo(); raccourcis(); personnaliser(); });
})();
