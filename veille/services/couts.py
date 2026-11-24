"""Coût de l'IA : enregistrement de chaque appel, budget mensuel, estimations avant lancement.

Les tarifs sont ceux de l'API Anthropic, en dollars par million de jetons. Les jetons de
réflexion du modèle sont comptés (et facturés) comme des jetons de sortie.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Avg, Count, Sum
from django.utils import timezone

from ..models import AvisMarche, ConsommationIA, Parametres

log = logging.getLogger("veille.couts")


@dataclass(frozen=True)
class Tarif:
    entree: float
    sortie: float
    cache_lu: float
    cache_ecrit: float  # cache de 5 minutes : 1,25 × l'entrée


TARIFS = {
    "claude-opus-5-5": Tarif(4.00, 20.00, 0.20, 5.00),
    "claude-opus-5": Tarif(5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-8": Tarif(5.00, 25.00, 0.50, 6.25),
    "claude-sonnet-5-5": Tarif(2.00, 10.00, 0.10, 2.50),
    "claude-sonnet-5": Tarif(2.00, 10.00, 0.20, 2.50),
    "claude-haiku-5-5": Tarif(0.10, 0.50, 0.01, 0.125),
    "claude-fable-5-2": Tarif(8.00, 40.00, 0.20, 10.00),
}
TARIF_PAR_DEFAUT = TARIFS["claude-opus-5-5"]


def tarif(modele: str) -> Tarif:
    modele = modele or ""
    if modele in TARIFS:
        return TARIFS[modele]
    # « claude-opus-5-5-xxx » ou nom inconnu : on prend le plus proche par préfixe
    for nom in sorted(TARIFS, key=len, reverse=True):
        if modele.startswith(nom):
            return TARIFS[nom]
    return TARIF_PAR_DEFAUT


def cout_usd(modele: str, entree: int, sortie: int, cache_lu: int = 0, cache_ecrit: int = 0) -> Decimal:
    t = tarif(modele)
    total = (entree * t.entree + sortie * t.sortie + cache_lu * t.cache_lu + cache_ecrit * t.cache_ecrit) / 1_000_000
    return Decimal(str(round(total, 5)))


def _entier(usage, nom: str) -> int:
    v = getattr(usage, nom, None)
    return v if isinstance(v, int) else 0


def enregistrer(reponse, usage: str, avis: AvisMarche | None = None) -> ConsommationIA | None:
    """Note la consommation d'une réponse de l'API. Ne fait jamais échouer le traitement."""
    try:
        u = getattr(reponse, "usage", None)
        if u is None:
            return None
        modele = getattr(reponse, "model", "") or ""
        e, s = _entier(u, "input_tokens"), _entier(u, "output_tokens")
        cl, ce = _entier(u, "cache_read_input_tokens"), _entier(u, "cache_creation_input_tokens")
        return ConsommationIA.objects.create(
            usage=usage,
            avis=avis if avis is not None and avis.pk else None,
            modele=modele[:50],
            jetons_entree=e,
            jetons_sortie=s,
            jetons_cache_lus=cl,
            jetons_cache_ecrits=ce,
            cout_usd=cout_usd(modele, e, s, cl, ce),
        )
    except Exception:  # le suivi du coût ne doit pas bloquer une analyse
        log.exception("Consommation IA non enregistrée")
        return None


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


def en_euros(usd: Decimal | float, p: Parametres | None = None) -> Decimal:
    p = p or Parametres.get()
    return (Decimal(str(usd)) * p.taux_usd_eur).quantize(Decimal("0.01"))


def debut_du_mois():
    maintenant = timezone.localtime()
    return maintenant.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@dataclass
class EtatBudget:
    depense: Decimal  # € ce mois-ci
    budget: Decimal  # € ; 0 = pas de limite
    seuil: int  # % d'alerte
    nb_appels: int

    @property
    def limite(self) -> bool:
        return self.budget > 0

    @property
    def part(self) -> int:
        if not self.limite:
            return 0
        return int(min(100, 100 * self.depense / self.budget))

    @property
    def atteint(self) -> bool:
        return self.limite and self.depense >= self.budget

    @property
    def alerte(self) -> bool:
        return self.limite and not self.atteint and self.part >= self.seuil

    @property
    def niveau(self) -> str:
        return "ko" if self.atteint else ("attente" if self.alerte else "ok")

    @property
    def restant(self) -> Decimal:
        return max(Decimal("0"), self.budget - self.depense) if self.limite else Decimal("0")


def etat_budget() -> EtatBudget:
    p = Parametres.get()
    agr = ConsommationIA.objects.filter(date__gte=debut_du_mois()).aggregate(total=Sum("cout_usd"), n=Count("id"))
    return EtatBudget(
        depense=en_euros(agr["total"] or 0, p),
        budget=p.budget_mensuel,
        seuil=p.seuil_alerte_budget,
        nb_appels=agr["n"] or 0,
    )


def budget_atteint() -> bool:
    return etat_budget().atteint


def depense_par_usage() -> list[dict]:
    """Détail du mois en cours, par type d'appel."""
    p = Parametres.get()
    libelles = dict(ConsommationIA.USAGES)
    lignes = (
        ConsommationIA.objects.filter(date__gte=debut_du_mois())
        .values("usage")
        .annotate(total=Sum("cout_usd"), n=Count("id"))
        .order_by("-total")
    )
    return [
        {"usage": libelles.get(l["usage"], l["usage"]), "n": l["n"], "total": en_euros(l["total"] or 0, p),
         "moyen": en_euros((l["total"] or 0) / l["n"], p) if l["n"] else Decimal("0")}
        for l in lignes
    ]


def historique_mensuel(mois: int = 6) -> list[dict]:
    """Dépense des derniers mois (le plus récent en dernier)."""
    p = Parametres.get()
    debut = debut_du_mois()
    sortie = []
    for i in range(mois - 1, -1, -1):
        annee, m = debut.year, debut.month - i
        while m <= 0:
            m += 12
            annee -= 1
        d = debut.replace(year=annee, month=m)
        f = d.replace(year=annee + (m == 12), month=1 if m == 12 else m + 1)
        total = ConsommationIA.objects.filter(date__gte=d, date__lt=f).aggregate(t=Sum("cout_usd"))["t"] or 0
        sortie.append({"mois": d, "total": en_euros(total, p)})
    return sortie


# ---------------------------------------------------------------------------
# Estimations avant lancement
# ---------------------------------------------------------------------------

# Sans historique : ordres de grandeur prudents (jetons d'entrée hors documents, jetons de sortie).
BASE = {"SCORE": (6_000, 2_500), "ANALYSE": (12_000, 12_000), "MEMOIRE": (16_000, 30_000)}
JETONS_PAR_PAGE_PDF = 1_800
CARACTERES_PAR_JETON = 3.5


def _moyenne_historique(usage: str) -> Decimal | None:
    agr = ConsommationIA.objects.filter(usage=usage).aggregate(m=Avg("cout_usd"), n=Count("id"))
    return Decimal(str(agr["m"])) if agr["n"] and agr["n"] >= 3 else None


def estimer_usd(usage: str, avis: AvisMarche | None = None, modele: str = "") -> Decimal:
    """Coût probable d'un appel. Pour un dossier, tient compte de la taille des documents."""
    from django.conf import settings

    modele = modele or settings.CLAUDE_MODEL
    entree, sortie = BASE.get(usage, BASE["SCORE"])
    if usage == "SCORE" or avis is None:
        moyenne = _moyenne_historique(usage)
        if moyenne is not None:
            return moyenne
        return cout_usd(modele, entree, sortie)
    documents = 0
    for d in avis.documents.all():
        if d.texte:
            documents += int(len(d.texte) / CARACTERES_PAR_JETON)
        elif d.nb_pages:
            documents += d.nb_pages * JETONS_PAR_PAGE_PDF
        else:
            documents += 10 * JETONS_PAR_PAGE_PDF
    if not documents and avis.texte:
        documents = int(len(avis.texte) / CARACTERES_PAR_JETON)
    return cout_usd(modele, entree + documents, sortie)


def estimer_euros(usage: str, avis: AvisMarche | None = None, nombre: int = 1) -> Decimal:
    return en_euros(estimer_usd(usage, avis) * nombre)
