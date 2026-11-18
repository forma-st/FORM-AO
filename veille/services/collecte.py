"""Orchestration : collecte des sources, enregistrement, dédoublonnage, pré-filtre."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from ..models import AvisMarche, Collecte, ProfilVeille
from . import boamp, prefiltre, ted

log = logging.getLogger("veille.collecte")

# CPV interrogés sur TED (TED ne fait que des correspondances exactes de codes)
CPV_TED_DEFAUT = [
    "80000000", "80300000", "80330000", "80400000", "80500000", "80510000", "80511000",
    "80512000", "80513000", "80520000", "80521000", "80522000", "80530000", "80531000",
    "80531100", "80531200", "80532000", "80533000", "80540000", "80550000", "80560000",
    "80561000", "80562000", "80570000", "80590000", "71317000", "71317100", "71317200",
    "71317210", "79417000", "85147000", "75251110",
]


def date_depart(source: str, jours_defaut: int = 7) -> date:
    """Reprend à la date de la dernière collecte réussie (avec un jour de recouvrement)."""
    derniere = Collecte.objects.filter(source=source, fin__isnull=False, erreur="").first()
    if derniere:
        return (derniere.debut - timedelta(days=1)).date()
    return timezone.localdate() - timedelta(days=jours_defaut)


def enregistrer(donnees: dict, profils: list[ProfilVeille]) -> tuple[AvisMarche | None, bool]:
    """Crée ou met à jour un avis. Renvoie (avis, est_nouveau)."""
    source, source_id = donnees["source"], donnees["source_id"]

    # Dédoublonnage TED / BOAMP : même procédure, même nature déjà connue via une autre source
    proc = donnees.get("procedure_id")
    if proc and source == "TED":
        if (
            AvisMarche.objects.filter(procedure_id=proc, nature=donnees["nature"])
            .exclude(source="TED")
            .exists()
        ):
            return None, False

    avis = AvisMarche.objects.filter(source=source, source_id=source_id).first()
    nouveau = avis is None
    if nouveau:
        avis = AvisMarche(**donnees)
    else:
        for champ, valeur in donnees.items():
            setattr(avis, champ, valeur)
    prefiltre.appliquer(avis, profils)
    alleger(avis, profils)
    avis.save()
    return avis, nouveau


def alleger(avis: AvisMarche, profils: list[ProfilVeille]) -> None:
    """Ne conserve le contenu brut que pour les avis utiles : retenus par la veille, ou
    attributions de notre secteur (analyse de la concurrence). Évite que la base gonfle
    de plusieurs Go par an."""
    if avis.prefiltre_ok:
        return
    if avis.nature == "ATTRIBUTION" and any(prefiltre.evaluer_profil(avis, p).ok for p in profils):
        return
    avis.brut = None
    avis.texte = avis.texte[:1000]


def collecter_source(source: str, depuis: date | None = None) -> Collecte:
    profils = list(ProfilVeille.objects.filter(actif=True))
    depuis = depuis or date_depart(source)
    journal = Collecte.objects.create(source=source, depuis=depuis)
    try:
        if source == "BOAMP":
            flux = boamp.collecter(depuis)
        elif source == "TED":
            cpv = set(CPV_TED_DEFAUT)
            for p in profils:
                cpv.update(c.ljust(8, "0")[:8] for c in p.liste_cpv)
            flux = ted.collecter(depuis, sorted(cpv))
        else:
            raise ValueError(f"Source inconnue : {source}")

        for donnees in flux:
            journal.nb_lus += 1
            with transaction.atomic():
                avis, nouveau = enregistrer(donnees, profils)
            if nouveau:
                journal.nb_nouveaux += 1
                if avis.prefiltre_ok:
                    journal.nb_retenus += 1
    except Exception as e:  # on journalise et on laisse les autres sources tourner
        log.exception("Erreur de collecte %s", source)
        journal.erreur = str(e)[:2000]
    journal.fin = timezone.now()
    journal.save()
    return journal
