from django.core.management.base import BaseCommand, CommandError

from veille.models import AvisMarche
from veille.services import memoire


class Command(BaseCommand):
    help = "Rédige par l'IA un brouillon de mémoire technique pour un avis (export Word)."

    def add_arguments(self, parser):
        parser.add_argument("avis_id", type=int)
        parser.add_argument("--consignes", default="")

    def handle(self, *args, avis_id, consignes, **opts):
        a = AvisMarche.objects.filter(pk=avis_id).first()
        if not a:
            raise CommandError("Avis introuvable.")
        m = memoire.rediger(a, consignes=consignes)
        if m.statut != "OK":
            raise CommandError(m.erreur)
        self.stdout.write(self.style.SUCCESS(f"Mémoire rédigé : {m.fichier.path} ({m.nb_a_completer} points à compléter)"))
