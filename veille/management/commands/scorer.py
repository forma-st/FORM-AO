from django.core.management.base import BaseCommand

from veille.models import AvisMarche
from veille.services import scoring


class Command(BaseCommand):
    help = "Score par l'IA les avis retenus par le pré-filtre et pas encore notés."

    def add_arguments(self, parser):
        parser.add_argument("--limite", type=int, default=200, help="Nombre maximum d'avis à scorer")
        parser.add_argument("--rescorer", action="store_true", help="Recalcule aussi les avis déjà notés")
        parser.add_argument("--regles", action="store_true", help="Score par règles uniquement (sans IA)")
        parser.add_argument("--id", type=int, nargs="*", help="Ne scorer que ces avis")

    def handle(self, *args, limite, rescorer, regles, id, **opts):
        qs = AvisMarche.objects.filter(prefiltre_ok=True)
        if id:
            qs = AvisMarche.objects.filter(pk__in=id)
        elif not rescorer:
            qs = qs.filter(score__isnull=True)
        qs = qs.order_by("date_limite")[:limite]

        client = profil = None
        if not regles:
            try:
                client = scoring._client()
                profil = scoring.profil_entreprise()
            except scoring.ScoringIndisponible as e:
                self.stderr.write(self.style.WARNING(f"{e} Bascule sur le score par règles."))
                regles = True

        n = 0
        for avis in qs:
            try:
                if regles:
                    r = scoring.score_regles(avis)
                    scoring.enregistrer(avis, r, modele="règles")
                else:
                    r = scoring.scorer(avis, client=client, profil=profil)
                n += 1
                self.stdout.write(f"{avis.score:>3} {avis.recommandation:<9} {avis.objet[:90]}")
            except Exception as e:  # un avis en erreur ne bloque pas les autres
                self.stderr.write(self.style.ERROR(f"Avis {avis.pk} : {e}"))
        self.stdout.write(self.style.SUCCESS(f"{n} avis scorés."))
