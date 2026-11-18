"""Digest quotidien et alertes immédiates par e-mail."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from ..models import AvisMarche, PieceAdministrative, ProfilVeille

log = logging.getLogger("veille.digest")


def _ouverts():
    return AvisMarche.objects.filter(prefiltre_ok=True, nature__in=["AVIS", "AUTRE"]).filter(
        Q(date_limite__isnull=True) | Q(date_limite__gte=timezone.now())
    )


def pieces_a_renouveler(jours: int = 30):
    limite = timezone.localdate() + timedelta(days=jours)
    return PieceAdministrative.objects.filter(date_expiration__isnull=False, date_expiration__lte=limite)


def echeances_proches(jours: int = 10):
    return AvisMarche.objects.filter(
        statut__in=["GO", "REDACTION"],
        date_limite__gte=timezone.now(),
        date_limite__lte=timezone.now() + timedelta(days=jours),
    ).order_by("date_limite")


def _envoyer(sujet: str, destinataires: list[str], template: str, contexte: dict) -> None:
    contexte = {"base_url": getattr(settings, "BASE_URL", "http://localhost:8000"), **contexte}
    html = render_to_string(template, contexte)
    texte = render_to_string(template.replace(".html", ".txt"), contexte)
    msg = EmailMultiAlternatives(sujet, texte, settings.DEFAULT_FROM_EMAIL, destinataires)
    msg.attach_alternative(html, "text/html")
    msg.send()


def envoyer_digest(profil: ProfilVeille, forcer: bool = False) -> int:
    """Envoie les nouveaux avis au-dessus du seuil du profil. Renvoie le nombre d'avis envoyés."""
    avis = list(
        _ouverts()
        .filter(profil=profil, score__gte=profil.seuil_digest)
        .filter(Q(digest_envoye=False) if not forcer else Q())
        .order_by("-score", "date_limite")
    )
    pieces = list(pieces_a_renouveler())
    echeances = list(echeances_proches())
    if not profil.liste_destinataires:
        log.warning("Profil %s : aucun destinataire, digest non envoyé.", profil)
        return 0
    if not (avis or pieces or echeances):
        return 0
    sujet = f"[Veille AO] {len(avis)} appel(s) d'offres à regarder – {timezone.localdate():%d/%m}"
    _envoyer(
        sujet,
        profil.liste_destinataires,
        "veille/email/digest.html",
        {"profil": profil, "avis": avis, "pieces": pieces, "echeances": echeances},
    )
    AvisMarche.objects.filter(pk__in=[a.pk for a in avis]).update(digest_envoye=True)
    return len(avis)


def envoyer_alertes(profil: ProfilVeille) -> int:
    avis = list(
        _ouverts().filter(profil=profil, score__gte=profil.seuil_alerte, alerte_envoyee=False).order_by("-score")
    )
    if not avis or not profil.liste_destinataires:
        return 0
    for a in avis:
        _envoyer(
            f"[Veille AO] À regarder vite ({a.score}/100) : {a.objet[:80]}",
            profil.liste_destinataires,
            "veille/email/alerte.html",
            {"a": a},
        )
    AvisMarche.objects.filter(pk__in=[a.pk for a in avis]).update(alerte_envoyee=True)
    return len(avis)
