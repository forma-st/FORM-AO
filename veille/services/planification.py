"""Veille automatique : le Mac lance la commande toutes les 15 minutes, elle ne tourne qu'une fois
par jour, à partir de l'heure choisie dans les Paramètres (rattrapée au réveil si le Mac dormait)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from django.utils import timezone

from ..models import Collecte, Parametres

AGENT_VEILLE = Path.home() / "Library/LaunchAgents/com.formast.formao.veille.plist"


def prevue_maintenant(p: Parametres, maintenant=None) -> bool:
    maintenant = timezone.localtime(maintenant)
    if not p.collecte_auto or p.derniere_veille_auto == maintenant.date():
        return False
    return maintenant.time() >= p.heure_collecte


def prochaine_execution(p: Parametres, maintenant=None) -> datetime | None:
    """Prochaine veille automatique (None si désactivée). Si l'heure est passée sans que la veille
    ait tourné aujourd'hui, elle est due tout de suite : on renvoie l'heure d'aujourd'hui."""
    if not p.collecte_auto:
        return None
    maintenant = timezone.localtime(maintenant)
    jour = maintenant.date()
    if p.derniere_veille_auto == jour:
        jour += timedelta(days=1)
    return timezone.make_aware(datetime.combine(jour, p.heure_collecte))


def automatisation_installee() -> bool:
    """Le lanceur macOS de la veille est-il en place (deploy/mac/installer.sh) ?"""
    return AGENT_VEILLE.exists()


def derniere_collecte() -> dict | None:
    """Bilan de la dernière collecte, toutes sources confondues (BOAMP, TED…)."""
    derniere = Collecte.objects.filter(fin__isnull=False).first()
    if not derniere:
        return None
    lot = list(Collecte.objects.filter(debut__gte=derniere.debut - timedelta(minutes=30), debut__lte=derniere.fin))
    return {
        "fin": max(c.fin for c in lot if c.fin),
        "lus": sum(c.nb_lus for c in lot),
        "nouveaux": sum(c.nb_nouveaux for c in lot),
        "retenus": sum(c.nb_retenus for c in lot),
        "sources": sorted({c.source for c in lot}),
        "erreurs": [c for c in lot if c.erreur],
    }
