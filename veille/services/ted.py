"""Collecte des avis TED (Journal officiel de l'UE) pour les acheteurs français.

API officielle de recherche : https://api.ted.europa.eu/v3/notices/search
(anonyme, sans clé). Une grande partie des avis français TED figure aussi au
BOAMP : on dédoublonne par identifiant de procédure lors de l'enregistrement.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterator

from .http import post_json

log = logging.getLogger("veille.ted")

URL = "https://api.ted.europa.eu/v3/notices/search"
PAGE = 100

CHAMPS = [
    "publication-number",
    "publication-date",
    "notice-type",
    "notice-title",
    "title-proc",
    "title-lot",
    "description-proc",
    "description-lot",
    "buyer-name",
    "classification-cpv",
    "deadline-receipt-tender-date-lot",
    "deadline-time-lot",
    "procedure-identifier",
    "procedure-type",
    "estimated-value-proc",
    "estimated-value-lot",
    "framework-estimated-value-glo",
    "place-of-performance-post-code-proc",
    "place-of-performance-post-code-part",
    "place-of-performance-city-proc",
    "award-criterion-name-lot",
    "award-criterion-number-weight-lot",
    "contract-duration-period-lot",
    "duration-period-unit-lot",
    "received-submissions-type-val",
    "winner-name",
]


def _nature(type_avis: str) -> str:
    if type_avis.startswith("cn"):
        return "AVIS"
    if type_avis.startswith("can"):
        return "ATTRIBUTION"
    if type_avis.startswith("corr"):
        return "RECTIFICATIF"
    return "AUTRE"  # pin-* (préinformation), etc.


def _fr(valeur) -> str | list:
    """Extrait la version française d'un champ multilingue ({"fra": [...]})."""
    if isinstance(valeur, dict):
        for langue in ("fra", "FRA", "eng", "ENG"):
            if langue in valeur:
                return valeur[langue]
        return next(iter(valeur.values()), "")
    return valeur or ""


def _liste(valeur) -> list:
    valeur = _fr(valeur)
    if valeur in ("", None):
        return []
    return valeur if isinstance(valeur, list) else [valeur]


def _premier(valeur) -> str:
    l = _liste(valeur)
    return str(l[0]) if l else ""


def _departements(codes_postaux: list[str]) -> list[str]:
    deps = []
    for cp in codes_postaux:
        cp = str(cp).strip()
        if not re.fullmatch(r"\d{5}", cp):
            continue
        dep = cp[:3] if cp.startswith("97") else cp[:2]
        if dep == "20":
            dep = "2A" if int(cp) < 20200 else "2B"
        if dep not in deps:
            deps.append(dep)
    return deps


def _montant(*valeurs) -> Decimal | None:
    montants = []
    for v in valeurs:
        for x in _liste(v):
            try:
                m = Decimal(str(x))
                if m > 0:
                    montants.append(m)
            except InvalidOperation:
                pass
    return max(montants) if montants else None


def _date_limite(n: dict) -> datetime | None:
    d = _premier(n.get("deadline-receipt-tender-date-lot"))
    if not d:
        return None
    jour = d[:10]
    heure = _premier(n.get("deadline-time-lot"))[:5] or "12:00"
    try:
        return datetime.fromisoformat(f"{jour}T{heure}:00+01:00")
    except ValueError:
        return None


def normaliser_avis(n: dict) -> dict:
    numero = n["publication-number"]
    titre = _premier(n.get("title-proc")) or _premier(n.get("notice-title"))
    # "France – Services de formation – Objet réel" : on garde l'objet réel
    if titre.count(" – ") >= 2 and not n.get("title-proc"):
        titre = titre.split(" – ", 2)[2]

    lignes = []
    for cle in ("description-proc", "title-lot", "description-lot"):
        for v in _liste(n.get(cle)):
            v = html.unescape(str(v)).strip()
            if v and v not in lignes and v != titre:
                lignes.append(v)
    criteres = _liste(n.get("award-criterion-name-lot"))
    poids = _liste(n.get("award-criterion-number-weight-lot"))
    if criteres:
        lignes.append(
            "Critères : "
            + " ; ".join(f"{c} ({p})" if i < len(poids) and (p := poids[i]) else str(c) for i, c in enumerate(criteres[:10]))
        )
    duree = _premier(n.get("contract-duration-period-lot"))
    if duree:
        lignes.append(f"Durée : {duree} {_premier(n.get('duration-period-unit-lot'))}".strip())
    offres = _liste(n.get("received-submissions-type-val"))
    if offres:
        lignes.append(f"Offres reçues : {', '.join(map(str, offres[:10]))}")
    titulaires = _liste(n.get("winner-name"))
    if titulaires:
        lignes.append(f"Titulaire(s) : {', '.join(map(str, titulaires[:10]))}")

    cpv = []
    for c in _liste(n.get("classification-cpv")):
        if c not in cpv:
            cpv.append(c)

    codes_postaux = _liste(n.get("place-of-performance-post-code-proc")) + _liste(
        n.get("place-of-performance-post-code-part")
    )
    pub = _premier(n.get("publication-date"))[:10]

    return {
        "source": "TED",
        "source_id": numero,
        "procedure_id": _premier(n.get("procedure-identifier")),
        "url": f"https://ted.europa.eu/fr/notice/-/detail/{numero}",
        "nature": _nature(n.get("notice-type", "")),
        "objet": html.unescape(titre) or "(sans objet)",
        "acheteur": html.unescape(_premier(n.get("buyer-name"))),
        "acheteur_type": "public",
        "departements": ",".join(_departements(codes_postaux)),
        "lieu_execution": _premier(n.get("place-of-performance-city-proc")),
        "date_publication": date.fromisoformat(pub) if pub else None,
        "date_limite": _date_limite(n),
        "type_marche": "SERVICES",
        "procedure": _premier(n.get("procedure-type")),
        "cpv": ",".join(cpv),
        "montant_estime": _montant(
            n.get("estimated-value-proc"), n.get("framework-estimated-value-glo"), n.get("estimated-value-lot")
        ),
        "texte": "\n".join(lignes)[:8000],
        "brut": n,
    }


def collecter(depuis: date, cpv: list[str]) -> Iterator[dict]:
    """Avis d'acheteurs français publiés depuis ``depuis`` avec l'un des codes CPV donnés."""
    if not cpv:
        return
    codes = " ".join(sorted(set(c.ljust(8, "0")[:8] for c in cpv)))
    requete = (
        f"buyer-country=FRA AND classification-cpv IN ({codes}) "
        f"AND publication-date>={depuis.strftime('%Y%m%d')}"
    )
    page = 1
    lus = 0
    while True:
        data = post_json(
            URL,
            json={
                "query": requete,
                "fields": CHAMPS,
                "limit": PAGE,
                "page": page,
                "scope": "ALL",
                "paginationMode": "PAGE_NUMBER",
            },
        )
        avis = data.get("notices", [])
        if page == 1:
            log.info("TED : %s avis depuis le %s", data.get("totalNoticeCount"), depuis)
        for n in avis:
            yield normaliser_avis(n)
        lus += len(avis)
        if not avis or lus >= (data.get("totalNoticeCount") or 0):
            break
        page += 1
