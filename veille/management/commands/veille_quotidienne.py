from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from veille.models import Parametres
from veille.services import couts, notifications
from veille.services.planification import prevue_maintenant


class Command(BaseCommand):
    help = "Enchaîne collecte, scoring, e-mail et notification (lancé chaque matin par le Mac)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--si-prevu", action="store_true",
            help="Ne tourne que si l'heure choisie dans les Paramètres est passée et pas encore aujourd'hui",
        )

    def handle(self, *args, si_prevu, **opts):
        p = Parametres.get()
        if si_prevu:
            if not prevue_maintenant(p):
                return
            p.derniere_veille_auto = timezone.localdate()
            p.save(update_fields=["derniere_veille_auto"])
        debut = timezone.now()
        self.stdout.write(f"Veille du {timezone.localtime(debut):%d/%m/%Y %H:%M}")
        call_command("collecter")
        call_command("scorer")
        if p.notif_email:
            call_command("envoyer_digest")
        if p.notif_macos:
            titre, texte, sous_titre = notifications.message_collecte(
                notifications.resume_collecte(debut), couts.etat_budget()
            )
            notifications.notifier(titre, texte, sous_titre)
