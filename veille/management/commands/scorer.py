from django.core.management.base import BaseCommand

from veille.models import AvisMarche, Parametres
from veille.services import scoring


class Command(BaseCommand):
    help = "Score par l'IA les avis retenus par le pré-filtre et pas encore notés."

    def add_arguments(self, parser):
        parser.add_argument("--limite", type=int, default=None,
                            help="Nombre maximum d'avis notés par l'IA (défaut : réglage des Paramètres)")
        parser.add_argument("--rescorer", action="store_true", help="Recalcule aussi les avis déjà notés")
        parser.add_argument("--refaire-regles", action="store_true",
                            help="Ne re-note que les avis ouverts notés par règles (sans IA)")
        parser.add_argument("--regles", action="store_true", help="Score par règles uniquement (sans IA)")
        parser.add_argument("--id", type=int, nargs="*", help="Ne scorer que ces avis")

    def handle(self, *args, limite, rescorer, refaire_regles, regles, id, **opts):
        qs = AvisMarche.objects.filter(prefiltre_ok=True)
        if id:
            qs = AvisMarche.objects.filter(pk__in=id)
        elif refaire_regles:
            qs = scoring.notes_par_regles()
        elif not rescorer:
            qs = qs.filter(score__isnull=True)
        qs = list(qs.order_by("date_limite"))
        if limite is None:
            limite = Parametres.get().max_avis_par_collecte

        client = profil = None
        if not regles:
            try:
                scoring.verifier_budget()
                client = scoring._client()
                profil = scoring.profil_entreprise()
            except scoring.ScoringIndisponible as e:
                self.stderr.write(self.style.WARNING(f"{e} Bascule sur le score par règles."))
                regles = True

        n = n_ia = 0
        for avis in qs:
            try:
                if not regles and n_ia >= limite:
                    self.stderr.write(self.style.WARNING(
                        f"Limite de {limite} avis notés par l'IA atteinte : les suivants sont notés par règles."))
                    regles = True
                if regles:
                    if refaire_regles:
                        continue  # déjà notés par règles : rien à refaire
                    scoring.enregistrer(avis, scoring.score_regles(avis), modele="règles")
                else:
                    try:
                        scoring.scorer(avis, client=client, profil=profil)
                        n_ia += 1
                    except scoring.BudgetAtteint as e:
                        self.stderr.write(self.style.WARNING(f"{e} Bascule sur le score par règles."))
                        regles = True
                        if refaire_regles:
                            continue
                        scoring.enregistrer(avis, scoring.score_regles(avis), modele="règles")
                n += 1
                self.stdout.write(f"{avis.score:>3} {avis.recommandation:<9} {avis.objet[:90]}")
            except Exception as e:  # un avis en erreur ne bloque pas les autres
                self.stderr.write(self.style.ERROR(f"Avis {avis.pk} : {e}"))
        self.stdout.write(self.style.SUCCESS(f"{n} avis scorés, dont {n_ia} par l'IA."))
