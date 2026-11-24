"""Notification sur le Mac (centre de notifications) après la collecte du matin."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from ..models import AvisMarche, Collecte

log = logging.getLogger("veille.notifications")

# Les textes passent en arguments : aucun risque d'injection dans le script AppleScript.
SCRIPT = [
    "on run argv",
    "display notification (item 2 of argv) with title (item 1 of argv) subtitle (item 3 of argv) sound name \"Glass\"",
    "end run",
]


def disponible() -> bool:
    return sys.platform == "darwin" and shutil.which("osascript") is not None


def notifier(titre: str, texte: str, sous_titre: str = "") -> bool:
    """Affiche une notification macOS. Renvoie False si ce n'est pas possible (autre système, erreur)."""
    if not disponible():
        log.info("Notification non affichée (pas sur macOS) : %s – %s", titre, texte)
        return False
    commande = ["osascript"]
    for ligne in SCRIPT:
        commande += ["-e", ligne]
    commande += [titre[:120], texte[:240], sous_titre[:120]]
    try:
        subprocess.run(commande, check=True, timeout=15, capture_output=True)
        return True
    except (subprocess.SubprocessError, OSError):
        log.exception("Notification macOS impossible")
        return False


def resume_collecte(depuis=None) -> dict:
    """Ce que la dernière collecte a apporté (avis retenus depuis « depuis », 1 h par défaut)."""
    depuis = depuis or timezone.now() - timedelta(hours=1)
    nouveaux = AvisMarche.objects.filter(prefiltre_ok=True, cree_le__gte=depuis)
    erreurs = Collecte.objects.filter(debut__gte=depuis).exclude(erreur="")
    return {
        "retenus": nouveaux.count(),
        "go": nouveaux.filter(recommandation="GO").count(),
        "forts": nouveaux.filter(score__gte=70).count(),
        "echeances": AvisMarche.objects.filter(
            statut__in=["GO", "REDACTION"],
            date_limite__gte=timezone.now(),
            date_limite__lte=timezone.now() + timedelta(days=3),
        ).count(),
        "erreurs": [c.source for c in erreurs],
        "a_trier": AvisMarche.objects.filter(prefiltre_ok=True, statut__in=["DETECTE", "A_QUALIFIER"])
        .filter(Q(date_limite__isnull=True) | Q(date_limite__gte=timezone.now()))
        .count(),
    }


def message_collecte(r: dict, budget=None) -> tuple[str, str, str]:
    """(titre, texte, sous-titre) de la notification du matin."""
    if r["retenus"]:
        titre = f"{r['retenus']} nouvel appel d'offres" if r["retenus"] == 1 else f"{r['retenus']} nouveaux appels d'offres"
        details = []
        if r["go"]:
            details.append(f"{r['go']} Go recommandé" + ("s" if r["go"] > 1 else ""))
        elif r["forts"]:
            details.append(f"{r['forts']} à fort potentiel")
        details.append(f"{r['a_trier']} à trier au total")
        texte = ", ".join(details) + "."
    else:
        titre = "Pas de nouvel appel d'offres"
        texte = f"{r['a_trier']} avis restent à trier." if r["a_trier"] else "Tout est trié."
    if r["echeances"]:
        texte += f" {r['echeances']} date(s) limite(s) dans les 3 jours."
    if r["erreurs"]:
        texte += f" Collecte {', '.join(r['erreurs'])} en échec."
    sous_titre = "FORM'AO"
    if budget is not None and budget.limite:
        sous_titre = f"FORM'AO · IA : {budget.depense:.2f} € sur {budget.budget:.0f} € ce mois".replace(".", ",")
        if budget.atteint:
            sous_titre += " (budget atteint)"
    return titre, texte, sous_titre
