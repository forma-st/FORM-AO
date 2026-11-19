from django import template

register = template.Library()


@register.filter
def couleur_score(score):
    if score is None:
        return "gris"
    if score >= 70:
        return "vert"
    if score >= 45:
        return "orange"
    return "rouge"


@register.filter
def libelle_reco(reco):
    return {"GO": "Go recommandé", "A_ETUDIER": "À étudier", "NO_GO": "No-Go recommandé"}.get(reco, "Non évalué")


@register.filter
def j_moins(jours):
    if jours is None:
        return ""
    if jours < 0:
        return "Clos"
    if jours == 0:
        return "Auj."
    return f"J-{jours}"


@register.filter
def euros(v):
    if v in (None, ""):
        return ""
    v = float(v)
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f} M€ HT".replace(".", ",")
    if v >= 1000:
        return f"{v / 1000:.0f} k€ HT"
    return f"{v:.0f} € HT"


@register.filter
def departements(codes):
    codes = [c for c in (codes or "").split(",") if c]
    if not codes:
        return ""
    if len(codes) > 4:
        return f"{len(codes)} départements"
    return ("dép. " if len(codes) == 1 else "dép. ") + ", ".join(codes)


@register.filter
def marquer_a_completer(texte):
    """Surligne les [À COMPLÉTER …] dans un texte déjà échappé."""
    import re

    from django.utils.html import escape
    from django.utils.safestring import mark_safe

    return mark_safe(re.sub(r"(\[À COMPLÉTER[^\]]*\])", r'<mark class="marque-completer">\1</mark>', escape(texte or "")))
