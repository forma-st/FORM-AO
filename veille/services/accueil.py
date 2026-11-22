"""Page d'accueil : catalogue des widgets, préférences par utilisateur, données de chaque widget."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from ..models import AvisMarche, Collecte, Entreprise, PieceAdministrative, PreferencesAccueil
from . import annuaire, documents
from .scoring import ia_disponible


@dataclass(frozen=True)
class Widget:
    cle: str
    titre: str
    description: str
    large: bool = False  # taille par défaut


CATALOGUE = [
    Widget("a_trier", "À trier", "Les meilleurs appels d'offres en attente de décision, avec Go / No-Go.", True),
    Widget("echeances", "Prochaines échéances", "Dates limites des dossiers en Go, en rédaction ou déposés."),
    Widget("reponses", "Réponses en cours", "Où en est chaque dossier, de Go à Déposé."),
    Widget("activite", "Activité de la veille", "Avis retenus et Go recommandés sur les 14 derniers jours.", True),
    Widget("resultats", "Résultats", "Marchés gagnés, perdus et taux de réussite."),
    Widget("coffre", "Coffre-fort", "Pièces administratives valides et prochaines expirations."),
    Widget("profil", "Profil FORMA'ST", "Ce qu'il manque pour que les documents soient complets."),
    Widget("veille", "État de la veille", "Dernière collecte, IA, lancement manuel."),
]
PAR_CLE = {w.cle: w for w in CATALOGUE}


def preferences(utilisateur) -> list[dict]:
    """Liste ordonnée [{cle, titre, description, visible, large}] ; les nouveaux widgets s'ajoutent à la fin."""
    enregistrees = []
    if utilisateur and utilisateur.is_authenticated:
        p = PreferencesAccueil.objects.filter(utilisateur=utilisateur).first()
        enregistrees = (p.widgets if p else []) or []
    vus, sortie = set(), []
    for item in enregistrees:
        w = PAR_CLE.get(item.get("cle"))
        if w and w.cle not in vus:
            vus.add(w.cle)
            sortie.append({**w.__dict__, "visible": bool(item.get("visible", True)), "large": bool(item.get("large", w.large))})
    for w in CATALOGUE:
        if w.cle not in vus:
            sortie.append({**w.__dict__, "visible": True})
    return sortie


def enregistrer(utilisateur, ordre: list[str], visibles: set[str], larges: set[str]) -> None:
    ordre = [c for c in ordre if c in PAR_CLE] + [w.cle for w in CATALOGUE if w.cle not in ordre]
    widgets = [{"cle": c, "visible": c in visibles, "large": c in larges} for c in ordre]
    PreferencesAccueil.objects.update_or_create(utilisateur=utilisateur, defaults={"widgets": widgets})


def reinitialiser(utilisateur) -> None:
    PreferencesAccueil.objects.filter(utilisateur=utilisateur).delete()


# ---------------------------------------------------------------------------
# Données des widgets
# ---------------------------------------------------------------------------


def _ouverts(qs):
    return qs.filter(Q(date_limite__isnull=True) | Q(date_limite__gte=timezone.now()))


def w_a_trier():
    qs = _ouverts(AvisMarche.objects.filter(prefiltre_ok=True, statut__in=["DETECTE", "A_QUALIFIER"]))
    return {
        "avis": list(qs.exclude(recommandation="NO_GO").order_by("-score", "date_limite")[:5]),
        "total": qs.count(),
        "go_recommandes": qs.filter(recommandation="GO").count(),
        "no_go_recommandes": qs.filter(recommandation="NO_GO").exclude(score_modele="règles").count(),
    }


def w_echeances():
    qs = AvisMarche.objects.filter(statut__in=["GO", "REDACTION", "DEPOSE"], date_limite__gte=timezone.now())
    return {"avis": list(qs.order_by("date_limite")[:6])}


ETAPES = [("GO", "Go"), ("REDACTION", "En rédaction"), ("DEPOSE", "Déposé")]


def w_reponses():
    comptes = dict(
        AvisMarche.objects.filter(statut__in=[e for e, _ in ETAPES]).values_list("statut").annotate(n=Count("id"))
    )
    total = sum(comptes.values())
    etapes = [{"code": c, "libelle": l, "n": comptes.get(c, 0), "part": (100 * comptes.get(c, 0) / total) if total else 0}
              for c, l in ETAPES]
    avis = AvisMarche.objects.filter(statut__in=[e for e, _ in ETAPES]).order_by("date_limite")[:4]
    return {"etapes": etapes, "total": total, "avis": list(avis)}


def w_activite(jours: int = 14):
    debut = timezone.localdate() - timedelta(days=jours - 1)
    lignes = (
        AvisMarche.objects.filter(date_publication__gte=debut)
        .values("date_publication")
        .annotate(
            lus=Count("id"),
            retenus=Count("id", filter=Q(prefiltre_ok=True)),
            go=Count("id", filter=Q(prefiltre_ok=True, recommandation="GO")),
        )
    )
    par_jour = {l["date_publication"]: l for l in lignes}
    serie = []
    for i in range(jours):
        d = debut + timedelta(days=i)
        l = par_jour.get(d, {})
        serie.append({"jour": d, "lus": l.get("lus", 0), "retenus": l.get("retenus", 0), "go": l.get("go", 0)})
    maxi = max([s["retenus"] for s in serie] + [1])
    # Graphique en barres (SVG) : largeur 280, hauteur 96, une barre par jour
    largeur, hauteur, marge = 560, 130, 18
    pas = largeur / jours
    for i, s in enumerate(serie):
        h = (hauteur - marge) * s["retenus"] / maxi
        hg = (hauteur - marge) * s["go"] / maxi
        s.update(x=round(i * pas + 2, 1), l=round(pas - 4, 1), y=round(hauteur - marge - h, 1), h=round(h, 1),
                 yg=round(hauteur - marge - hg, 1), hg=round(hg, 1), weekend=s["jour"].weekday() >= 5)
    return {
        "serie": serie,
        "maxi": maxi,
        "lus": sum(s["lus"] for s in serie),
        "retenus": sum(s["retenus"] for s in serie),
        "go": sum(s["go"] for s in serie),
        "largeur": largeur,
        "hauteur": hauteur,
        "base": hauteur - marge,
        "premier": serie[0]["jour"],
        "dernier": serie[-1]["jour"],
    }


def w_resultats():
    gagnes = AvisMarche.objects.filter(statut="GAGNE").count()
    perdus = AvisMarche.objects.filter(statut="PERDU").count()
    deposes = AvisMarche.objects.filter(statut="DEPOSE").count()
    decides = gagnes + perdus
    return {
        "gagnes": gagnes,
        "perdus": perdus,
        "deposes": deposes,
        "taux": round(100 * gagnes / decides) if decides else None,
        "derniers": list(AvisMarche.objects.filter(statut__in=["GAGNE", "PERDU"]).order_by("-modifie_le")[:3]),
    }


def w_coffre():
    jour = timezone.localdate()
    attendues = documents.PIECES_ATTENDUES
    valides = {
        p.type
        for p in PieceAdministrative.objects.exclude(fichier="")
        if p.date_expiration is None or p.date_expiration >= jour
    }
    ok = sum(1 for t, _ in attendues if t in valides)
    prochaine = (
        PieceAdministrative.objects.exclude(fichier="").filter(date_expiration__gte=jour).order_by("date_expiration").first()
    )
    return {
        "ok": ok,
        "total": len(attendues),
        "part": round(100 * ok / len(attendues)),
        "manquantes": [lib for t, lib in attendues if t not in valides][:4],
        "nb_manquantes": len(attendues) - ok,
        "prochaine": prochaine,
    }


def w_profil():
    c = annuaire.completude(Entreprise.get())
    obligatoires = [x for x in c if x["obligatoire"]]
    remplis = sum(1 for x in obligatoires if x["rempli"])
    return {
        "part": round(100 * remplis / len(obligatoires)) if obligatoires else 100,
        "manquants": [x["libelle"] for x in obligatoires if not x["rempli"]],
    }


def w_veille():
    derniere = Collecte.objects.filter(fin__isnull=False).first()
    depuis = timezone.now() - timedelta(days=1)
    return {
        "derniere": derniere,
        "en_cours": Collecte.objects.filter(fin__isnull=True, debut__gte=timezone.now() - timedelta(minutes=30)).exists(),
        "erreur": Collecte.objects.filter(fin__isnull=False).exclude(erreur="").filter(debut__gte=depuis).first(),
        "nouveaux": AvisMarche.objects.filter(prefiltre_ok=True, cree_le__gte=depuis).count(),
        "ia": ia_disponible(),
        "total": AvisMarche.objects.count(),
    }


DONNEES = {
    "a_trier": w_a_trier,
    "echeances": w_echeances,
    "reponses": w_reponses,
    "activite": w_activite,
    "resultats": w_resultats,
    "coffre": w_coffre,
    "profil": w_profil,
    "veille": w_veille,
}


def construire(utilisateur) -> list[dict]:
    """Widgets visibles, dans l'ordre choisi, avec leurs données."""
    return [{**w, "d": DONNEES[w["cle"]]()} for w in preferences(utilisateur) if w["visible"]]
