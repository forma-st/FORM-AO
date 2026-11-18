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
    return {"GO": "Go", "A_ETUDIER": "À étudier", "NO_GO": "No-Go"}.get(reco, "—")
