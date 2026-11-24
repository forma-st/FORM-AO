"""Repère « nouveau depuis votre dernière visite ».

Au début de chaque visite (après 30 minutes sans activité), on garde en session l'heure de la
visite précédente : les avis arrivés depuis portent le badge « Nouveau » jusqu'à la visite suivante.
"""

from datetime import timedelta

from django.utils import timezone

from .models import PreferencesUtilisateur

PAUSE_VISITE = timedelta(minutes=30)
ECRITURE_MAX = timedelta(minutes=5)  # on n'écrit pas en base à chaque requête


class DerniereVisiteMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not request.path.startswith(("/static/", "/media/", "/admin/")):
            try:
                self._noter(request, user)
            except Exception:  # un souci de suivi ne doit jamais bloquer une page
                pass
        return self.get_response(request)

    @staticmethod
    def _noter(request, user):
        maintenant = timezone.now()
        prefs, _ = PreferencesUtilisateur.objects.get_or_create(utilisateur=user)
        request.preferences = prefs
        precedente = prefs.derniere_activite
        if "visite_precedente" not in request.session or (precedente and maintenant - precedente > PAUSE_VISITE):
            request.session["visite_precedente"] = (precedente or maintenant).isoformat()
        if not precedente or maintenant - precedente > ECRITURE_MAX:
            PreferencesUtilisateur.objects.filter(pk=prefs.pk).update(derniere_activite=maintenant)
