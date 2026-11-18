from datetime import date

from django.core.management.base import BaseCommand

from veille.services.collecte import collecter_source


class Command(BaseCommand):
    help = "Collecte les nouveaux avis (BOAMP, TED) et applique le pré-filtre."

    def add_arguments(self, parser):
        parser.add_argument("--source", choices=["BOAMP", "TED", "TOUT"], default="TOUT")
        parser.add_argument("--depuis", type=date.fromisoformat, help="AAAA-MM-JJ (défaut : reprise auto)")

    def handle(self, *args, source, depuis, **opts):
        sources = ["BOAMP", "TED"] if source == "TOUT" else [source]
        for s in sources:
            j = collecter_source(s, depuis)
            msg = f"{s} depuis {j.depuis} : {j.nb_lus} lus, {j.nb_nouveaux} nouveaux, {j.nb_retenus} retenus"
            if j.erreur:
                self.stderr.write(self.style.ERROR(f"{msg} – ERREUR : {j.erreur}"))
            else:
                self.stdout.write(self.style.SUCCESS(msg))
