"""Reprise des avis notés, analyses et mémoires d'une autre base (fichier JSON de loaddata),
fusionnée avec la base actuelle sans créer de doublons.

- Avis absent : ajouté tel quel.
- Avis déjà collecté ici : on reprend le score de l'IA s'il est meilleur que celui de la base
  (base sans score ou notée par règles) ; le statut, le responsable et les notes saisis ici sont gardés.
- Analyses et mémoires : rattachés au bon avis, ajoutés s'ils n'existent pas.
"""

import json

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.dateparse import parse_date, parse_datetime

from veille.models import AnalyseDCE, AvisMarche, Memoire, ProfilVeille

CHAMPS_SCORE = ["score", "recommandation", "resume", "score_details", "score_le", "score_modele"]
STATUTS_INITIAUX = ("DETECTE", "A_QUALIFIER")


def _valeurs(modele, champs: dict) -> dict:
    """Convertit les valeurs JSON (dates en texte, clés étrangères) pour le modèle."""
    sortie = {}
    for nom, v in champs.items():
        try:
            f = modele._meta.get_field(nom)
        except Exception:
            continue
        if f.is_relation:
            continue
        if v is not None and f.get_internal_type() == "DateTimeField":
            v = parse_datetime(v)
        elif v is not None and f.get_internal_type() == "DateField":
            v = parse_date(v)
        sortie[nom] = v
    return sortie


class Command(BaseCommand):
    help = "Fusionne un export (data/reprise.json) avec la base actuelle, sans doublons."

    def add_arguments(self, parser):
        parser.add_argument("fichier", nargs="?", default="data/reprise.json")

    @transaction.atomic
    def handle(self, *args, fichier, **opts):
        with open(fichier, encoding="utf-8") as f:
            objets = json.load(f)
        profils = {p.pk: p for p in ProfilVeille.objects.all()}
        profil_defaut = ProfilVeille.objects.filter(actif=True).first()
        correspondance = {}  # pk dans le fichier -> avis de la base
        ajoutes = completes = gardes = 0

        for o in objets:
            if o["model"] != "veille.avismarche":
                continue
            champs = o["fields"]
            valeurs = _valeurs(AvisMarche, champs)
            existant = AvisMarche.objects.filter(source=champs["source"], source_id=champs["source_id"]).first()
            if existant is None:
                avis = AvisMarche(**valeurs)
                avis.profil = profils.get(champs.get("profil")) or profil_defaut
                avis.save()
                ajoutes += 1
            else:
                avis = existant
                ia_fichier = champs.get("score_modele") not in (None, "", "règles")
                ia_base = avis.score_modele not in ("", "règles") and avis.score is not None
                if ia_fichier and not ia_base:
                    for nom in CHAMPS_SCORE:
                        if nom in valeurs and valeurs[nom] is not None:
                            setattr(avis, nom, valeurs[nom])
                    if avis.statut in STATUTS_INITIAUX and champs.get("statut") not in STATUTS_INITIAUX:
                        # décision prise pendant la phase de test, rien de décidé ici
                        for nom in ("statut", "decision_motif", "responsable", "notes", "lots_vises"):
                            setattr(avis, nom, valeurs.get(nom) or getattr(avis, nom))
                    avis.prefiltre_ok = avis.prefiltre_ok or champs.get("prefiltre_ok", False)
                    avis.save()
                    completes += 1
                else:
                    gardes += 1
            correspondance[o["pk"]] = avis

        n_analyses = n_memoires = 0
        for o in objets:
            avis = correspondance.get(o["fields"].get("avis"))
            if avis is None:
                continue
            if o["model"] == "veille.analysedce" and not AnalyseDCE.objects.filter(avis=avis).exists():
                AnalyseDCE.objects.create(avis=avis, **_valeurs(AnalyseDCE, o["fields"]))
                n_analyses += 1
            elif o["model"] == "veille.memoire":
                v = _valeurs(Memoire, o["fields"])
                if not Memoire.objects.filter(avis=avis, cree_le=v.get("cree_le")).exists():
                    m = Memoire.objects.create(avis=avis, **{k: x for k, x in v.items() if k != "cree_le"})
                    Memoire.objects.filter(pk=m.pk).update(cree_le=v.get("cree_le"))  # auto_now_add
                    n_memoires += 1

        self.stdout.write(self.style.SUCCESS(
            f"Reprise : {ajoutes} avis ajoutés, {completes} complétés par le score de l'IA, "
            f"{gardes} déjà à jour ; {n_analyses} analyse(s) et {n_memoires} mémoire(s) repris."
        ))
