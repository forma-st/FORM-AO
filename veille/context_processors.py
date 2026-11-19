from django.db.models import Q
from django.utils import timezone

from .models import AvisMarche
from .services.scoring import ia_disponible


def navigation(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    a_trier = AvisMarche.objects.filter(prefiltre_ok=True, statut__in=["DETECTE", "A_QUALIFIER"]).filter(
        Q(date_limite__isnull=True) | Q(date_limite__gte=timezone.now())
    )
    return {
        "nav_a_trier": a_trier.count(),
        "nav_en_cours": AvisMarche.objects.filter(statut__in=["GO", "REDACTION", "DEPOSE"]).count(),
        "ia_active": ia_disponible(),
    }
