from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Enchaîne collecte, scoring et envoi des e-mails (à lancer par cron chaque matin)."

    def handle(self, *args, **opts):
        call_command("collecter")
        call_command("scorer")
        call_command("envoyer_digest")
