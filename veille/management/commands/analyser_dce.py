from django.core.management.base import BaseCommand, CommandError

from veille.models import AvisMarche
from veille.services import dce


class Command(BaseCommand):
    help = "Analyse par l'IA le DCE déposé pour un avis."

    def add_arguments(self, parser):
        parser.add_argument("avis_id", type=int)

    def handle(self, *args, avis_id, **opts):
        a = AvisMarche.objects.filter(pk=avis_id).first()
        if not a:
            raise CommandError("Avis introuvable.")
        r = dce.analyser(a)
        if r.statut == "OK":
            self.stdout.write(self.style.SUCCESS(f"Analyse terminée : {r.resultat['score']}/100, {r.resultat['recommandation']}"))
        else:
            raise CommandError(r.erreur)
