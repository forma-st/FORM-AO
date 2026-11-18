"""Lancement des traitements IA longs (analyse, mémoire) en arrière-plan.

Usage interne, peu d'utilisateurs : un simple thread suffit. Le statut est suivi
dans la base (EN_COURS / OK / ERREUR) et la page se rafraîchit toute seule.
"""

import threading

from django.db import close_old_connections


def lancer(fonction, *args, **kwargs) -> threading.Thread:
    def cible():
        close_old_connections()
        try:
            fonction(*args, **kwargs)
        finally:
            close_old_connections()

    t = threading.Thread(target=cible, daemon=True)
    t.start()
    return t
