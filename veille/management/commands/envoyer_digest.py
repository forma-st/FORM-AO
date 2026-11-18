from django.core.management.base import BaseCommand

from veille.models import ProfilVeille
from veille.services import digest


class Command(BaseCommand):
    help = "Envoie les alertes immédiates et le digest quotidien de chaque profil de veille."

    def add_arguments(self, parser):
        parser.add_argument("--forcer", action="store_true", help="Renvoie aussi les avis déjà envoyés")

    def handle(self, *args, forcer, **opts):
        for p in ProfilVeille.objects.filter(actif=True):
            na = digest.envoyer_alertes(p)
            nd = digest.envoyer_digest(p, forcer=forcer)
            self.stdout.write(self.style.SUCCESS(f"{p} : {na} alerte(s), digest de {nd} avis"))
