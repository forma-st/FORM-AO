"""Collecte des avis du BOAMP via l'API open data de la DILA (Opendatasoft).

Licence Ouverte 2.0, sans authentification.
Doc : https://boamp-datadila.opendatasoft.com/explore/dataset/boamp/api/

Remarque : les filtres d'égalité sur la date sont lents côté serveur. On
interroge donc par plage (``dateparution >= X``) triée par date décroissante,
ce qui répond en une à deux secondes.
"""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterator

from .http import get_json

log = logging.getLogger("veille.boamp")

URL = "https://boamp-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/boamp/records"
CHAMPS = [
    "idweb",
    "contractfolderid",
    "objet",
    "nomacheteur",
    "code_departement",
    "dateparution",
    "datelimitereponse",
    "nature",
    "famille",
    "procedure_libelle",
    "type_marche",
    "descripteur_libelle",
    "url_avis",
    "donnees",
]
PAGE = 100
OFFSET_MAX = 9900  # limite Opendatasoft : offset + limit <= 10 000

NATURES = {"APPEL_OFFRE": "AVIS", "ATTRIBUTION": "ATTRIBUTION", "RECTIFICATIF": "RECTIFICATIF"}

# Dernier segment de chemin dont on garde la valeur pour constituer le texte de l'avis
_CLES_TEXTE = {
    "objet",
    "objetcomplet",
    "description",
    "cbc:description",
    "cbc:name",
    "lieuexecution",
    "lieuexecutionlivraison",
    "ville",
    "nbmois",
    "dureemois",
    "cbc:durationmeasure",
    "renseignementscomplementaires",
    "criteres",
    "critere",
    "cbc:awardingcriteriondescription",
}
_CHEMINS_IGNORES = ("appealterms", "organization", "contact", "efac:organizations", "presentationperiod")


def _parcourir(obj, chemin=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _parcourir(v, f"{chemin}/{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from _parcourir(v, chemin)
    elif obj not in (None, ""):
        yield chemin, obj


def _dernier_segment(chemin: str) -> str:
    segs = [s for s in chemin.lower().split("/") if s and not s.startswith("@")]
    if segs and segs[-1] == "#text":
        segs = segs[:-1]
    return segs[-1] if segs else ""


def extraire_donnees(donnees: dict | None) -> dict:
    """Extrait CPV, montant estimé, date limite, critères et texte utile d'un avis
    (formats eForms, FNSimple, MAPA)."""
    cpv: list[str] = []
    montants: list[Decimal] = []
    lignes: list[str] = []
    fin_date = fin_heure = None
    poids_en_attente = None
    if not donnees:
        return {"cpv": cpv, "montant": None, "texte": "", "date_limite": None}

    for chemin, valeur in _parcourir(donnees):
        bas = chemin.lower()
        dernier = bas.rsplit("/", 1)[-1]
        if dernier.startswith("@"):  # attributs (langue, unité, liste de codes)
            continue
        if any(ign in bas for ign in _CHEMINS_IGNORES):
            continue
        texte = html.unescape(html.unescape(str(valeur))).strip()
        if ("classprincipale" in bas or "itemclassificationcode" in bas) and re.fullmatch(r"\d{8}", texte):
            if texte not in cpv:
                cpv.append(texte)
            continue
        if "estimatedoverallcontractamount" in bas or bas.endswith("/valeurestimee") or "valeur_totale" in bas:
            try:
                m = Decimal(texte)
                if m > 0:
                    montants.append(m)
            except InvalidOperation:
                pass
            continue
        if "tendersubmissiondeadlineperiod" in bas:
            if bas.endswith("cbc:enddate") and not fin_date:
                fin_date = texte
            elif bas.endswith("cbc:endtime") and not fin_heure:
                fin_heure = texte
            continue
        if "awardcriterionparameter" in bas and bas.endswith("efbc:parameternumeric"):
            poids_en_attente = texte
            continue
        if "subordinateawardingcriterion" in bas and _dernier_segment(chemin) == "cbc:description":
            ligne = f"Critère : {texte}" + (f" ({poids_en_attente})" if poids_en_attente else "")
            poids_en_attente = None
            if ligne not in lignes:
                lignes.append(ligne)
            continue
        if _dernier_segment(chemin) in _CLES_TEXTE and len(texte) > 1 and texte not in lignes:
            lignes.append(texte)

    date_limite = None
    if fin_date:
        try:
            jour, tz = fin_date[:10], fin_date[10:] or "+01:00"
            heure = (fin_heure or "12:00:00")[:8]
            date_limite = datetime.fromisoformat(f"{jour}T{heure}{tz}")
        except ValueError:
            pass
    texte = "\n".join(lignes)
    return {
        "cpv": cpv,
        "montant": max(montants) if montants else None,
        "texte": texte[:8000],
        "date_limite": date_limite,
    }


def _date_limite(valeur: str | None) -> datetime | None:
    if not valeur:
        return None
    try:
        return datetime.fromisoformat(valeur)
    except ValueError:
        return None


def normaliser_enregistrement(r: dict) -> dict:
    """Transforme un enregistrement BOAMP en champs du modèle AvisMarche."""
    donnees_brutes = r.get("donnees")
    try:
        donnees = json.loads(donnees_brutes) if isinstance(donnees_brutes, str) else donnees_brutes
    except json.JSONDecodeError:
        donnees = None
    ext = extraire_donnees(donnees)
    return {
        "source": "BOAMP",
        "source_id": r["idweb"],
        "procedure_id": r.get("contractfolderid") or "",
        "url": r.get("url_avis") or f"https://www.boamp.fr/pages/avis/?q=idweb:{r['idweb']}",
        "nature": NATURES.get(r.get("nature") or "", "AUTRE"),
        "objet": _html(r.get("objet") or "").strip() or "(sans objet)",
        "acheteur": _html(r.get("nomacheteur") or ""),
        "acheteur_type": "public",
        "departements": ",".join(r.get("code_departement") or []),
        "date_publication": date.fromisoformat(r["dateparution"]) if r.get("dateparution") else None,
        "date_limite": _date_limite(r.get("datelimitereponse")) or ext["date_limite"],
        "type_marche": ",".join(r.get("type_marche") or []),
        "procedure": r.get("procedure_libelle") or "",
        "cpv": ",".join(ext["cpv"]),
        "montant_estime": ext["montant"],
        "texte": ext["texte"],
        "brut": {
            "famille": r.get("famille"),
            "descripteurs": r.get("descripteur_libelle"),
            "donnees": donnees,
        },
    }


def _html(s: str) -> str:
    return html.unescape(s)


def collecter(depuis: date) -> Iterator[dict]:
    """Itère sur les avis publiés depuis ``depuis`` (inclus), du plus récent au plus ancien."""
    offset = 0
    total = None
    while True:
        params = {
            "limit": PAGE,
            "offset": offset,
            "where": f'dateparution >= "{depuis.isoformat()}"',
            "order_by": "dateparution desc, idweb desc",
            "select": ",".join(CHAMPS),
        }
        data = get_json(URL, params=params)
        if total is None:
            total = data.get("total_count", 0)
            log.info("BOAMP : %s avis publiés depuis le %s", total, depuis)
        resultats = data.get("results", [])
        for r in resultats:
            yield normaliser_enregistrement(r)
        offset += len(resultats)
        if not resultats or offset >= total:
            break
        if offset + PAGE > OFFSET_MAX + PAGE:
            log.warning(
                "BOAMP : plus de %s avis sur la période, collecte tronquée. Réduire l'intervalle.", OFFSET_MAX
            )
            break
