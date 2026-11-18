"""Pré-filtre par règles : élimine gratuitement tout ce qui est hors cible
avant de dépenser un appel IA. Calcule aussi un pré-score indicatif."""

from __future__ import annotations

from dataclasses import dataclass, field

from django.utils import timezone

from ..models import AvisMarche, ProfilVeille
from .texte import mots_cles_trouves


@dataclass
class Resultat:
    ok: bool
    motif: str = ""
    profil: ProfilVeille | None = None
    mots: list[str] = field(default_factory=list)
    cpv: list[str] = field(default_factory=list)


def _texte_recherche(avis: AvisMarche) -> str:
    descripteurs = ""
    if isinstance(avis.brut, dict):
        descripteurs = " ".join(avis.brut.get("descripteurs") or [])
    return f"{avis.objet}\n{descripteurs}\n{avis.texte}"


def evaluer_profil(avis: AvisMarche, profil: ProfilVeille) -> Resultat:
    exclus = mots_cles_trouves(avis.objet, profil.liste_exclus)
    if exclus:
        return Resultat(False, f"mot exclu dans l'objet : {', '.join(exclus)}", profil)

    if profil.liste_departements and avis.departements:
        deps = set(avis.departements.split(","))
        if not deps & set(profil.liste_departements):
            return Resultat(False, "hors zone géographique", profil)

    if avis.montant_estime is not None:
        if profil.montant_min is not None and avis.montant_estime < profil.montant_min:
            return Resultat(False, "montant estimé sous le minimum", profil)
        if profil.montant_max is not None and avis.montant_estime > profil.montant_max:
            return Resultat(False, "montant estimé au-dessus du maximum", profil)

    texte = _texte_recherche(avis)
    forts = mots_cles_trouves(texte, profil.liste_forts)
    generiques = mots_cles_trouves(texte, profil.liste_mots_cles)
    contexte = mots_cles_trouves(avis.objet, profil.liste_contexte) or mots_cles_trouves(
        texte, profil.liste_contexte_texte
    )
    if not (profil.liste_contexte or profil.liste_contexte_texte):
        contexte = ["(pas de contexte exigé)"]
    mots = forts + (generiques if contexte else [])
    cpv = [c for c in avis.liste_cpv if any(c.startswith(p) for p in profil.liste_cpv)]
    if not mots and not cpv:
        if generiques:
            return Resultat(False, f"mots génériques sans contexte formation : {', '.join(generiques[:3])}", profil)
        return Resultat(False, "aucun mot-clé ni CPV suivi", profil)
    return Resultat(True, "", profil, mots, cpv)


def evaluer(avis: AvisMarche, profils: list[ProfilVeille]) -> Resultat:
    if avis.nature == "ATTRIBUTION":
        return Resultat(False, "avis d'attribution (conservé pour l'analyse concurrentielle)")
    if avis.nature == "RECTIFICATIF":
        return Resultat(False, "rectificatif")
    types = set(filter(None, avis.type_marche.upper().split(",")))
    if types and "SERVICES" not in types:
        return Resultat(False, f"marché de {', '.join(sorted(types)).lower()}")
    if avis.date_limite and avis.date_limite < timezone.now():
        return Resultat(False, "date limite dépassée")

    if not profils:
        return Resultat(False, "aucun profil de veille actif")
    meilleur = None
    refus = None
    for profil in profils:
        r = evaluer_profil(avis, profil)
        if not r.ok:
            refus = refus or r
        elif meilleur is None or len(r.mots) + len(r.cpv) > len(meilleur.mots) + len(meilleur.cpv):
            meilleur = r
    return meilleur or refus


def appliquer(avis: AvisMarche, profils: list[ProfilVeille]) -> bool:
    """Met à jour les champs de pré-filtre de l'avis (sans sauvegarder)."""
    r = evaluer(avis, profils)
    avis.prefiltre_ok = r.ok
    avis.prefiltre_motif = r.motif[:300]
    avis.profil = r.profil if r.ok else None
    avis.mots_cles_trouves = ", ".join(r.mots + [f"CPV {c}" for c in r.cpv])[:500]
    if not r.ok and avis.statut == "DETECTE":
        avis.statut = "ECARTE"
    elif r.ok and avis.statut == "ECARTE":
        avis.statut = "DETECTE"
    return r.ok
