import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from veille.models import AvisMarche, BlocContenu, Entreprise, Formateur, Prestation, ProfilVeille, Reference
from veille.services import prefiltre


class Command(BaseCommand):
    help = "Charge (ou met à jour) le profil entreprise, le catalogue et la veille depuis un fichier JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "fichier", nargs="?", default=str(Path(settings.BASE_DIR) / "data" / "seed_formast.json")
        )

    @transaction.atomic
    def handle(self, *args, fichier, **opts):
        data = json.loads(Path(fichier).read_text(encoding="utf-8"))

        e = Entreprise.get() or Entreprise()
        for k, v in data["entreprise"].items():
            setattr(e, k, v)
        e.save()

        for p in data.get("prestations", []):
            Prestation.objects.update_or_create(intitule=p["intitule"], defaults=p)

        for f in data.get("formateurs", []):
            Formateur.objects.update_or_create(nom=f["nom"], prenom=f["prenom"], defaults=f)

        for r in data.get("references", []):
            Reference.objects.update_or_create(client=r["client"], objet=r["objet"], defaults=r)

        for b in data.get("blocs", []):
            BlocContenu.objects.update_or_create(titre=b["titre"], defaults=b)

        pv = data.get("profil_veille")
        profil = None
        if pv:
            profil, _ = ProfilVeille.objects.update_or_create(nom=pv["nom"], defaults=pv)

        profils = list(ProfilVeille.objects.filter(actif=True))
        for c in data.get("consultations_privees", []):
            avis, _ = AvisMarche.objects.update_or_create(
                source="PRIVE", source_id=c["source_id"], defaults={**c, "type_marche": "SERVICES"}
            )
            avis.refresh_from_db()
            prefiltre.appliquer(avis, profils)
            avis.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Profil chargé : {e} – {Prestation.objects.count()} prestations, "
                f"{Formateur.objects.count()} formateurs, {Reference.objects.count()} références, "
                f"{BlocContenu.objects.count()} blocs de contenu, "
                f"profil de veille « {profil} »."
            )
        )
