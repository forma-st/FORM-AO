"""Score Go/No-Go d'un avis par l'IA (Claude), en sortie structurée.

Le profil de l'entreprise (catalogue, formateurs, références, règles de
scoring) forme un préfixe stable mis en cache : seuls les détails de l'avis
changent d'un appel à l'autre.
"""

from __future__ import annotations

import logging
import os
from typing import Literal

import anthropic
from django.conf import settings
from django.utils import timezone
from pydantic import BaseModel, Field

from ..models import AvisMarche, Entreprise, Formateur, Prestation, Reference

log = logging.getLogger("veille.scoring")


class ScoringIndisponible(Exception):
    pass


# --------------------------------------------------------------------------
# Schéma de sortie
# --------------------------------------------------------------------------


class Critere(BaseModel):
    critere: str = Field(description="Nom du critère évalué")
    evaluation: Literal["favorable", "neutre", "defavorable", "eliminatoire"]
    commentaire: str = Field(description="Une phrase factuelle, appuyée sur l'avis")


class ScoreAvis(BaseModel):
    score: int = Field(description="Score global de 0 à 100")
    recommandation: Literal["GO", "A_ETUDIER", "NO_GO"]
    resume: str = Field(description="Ce que l'acheteur veut, en 2 ou 3 phrases simples")
    pourquoi: str = Field(description="Pourquoi ce score, en 1 ou 2 phrases")
    criteres: list[Critere]
    prestations_concernees: list[str] = Field(
        description="Intitulés de NOTRE catalogue qui répondent au besoin (vide si aucun)"
    )
    part_du_besoin_couverte: Literal["totale", "majoritaire", "partielle", "marginale", "aucune"]
    lots_a_viser: list[str] = Field(description="Lots pertinents pour nous, si l'avis est alloti")
    exigences_bloquantes: list[str] = Field(
        description="Exigences de l'avis que nous ne remplissons pas ou pas de façon certaine"
    )
    concurrence_estimee: Literal["faible", "moyenne", "forte", "inconnue"]
    points_de_vigilance: list[str]
    questions_a_verifier: list[str] = Field(description="Ce qu'il faut vérifier dans le DCE")


# --------------------------------------------------------------------------
# Construction du prompt
# --------------------------------------------------------------------------

REGLES = """\
# Ta mission
Tu aides l'organisme de formation décrit ci-dessus à décider s'il doit répondre à un appel d'offres.
L'objectif de l'entreprise : se positionner là où elle a de VRAIES chances de gagner, en priorité des
marchés de taille moyenne, peu concurrentiels, au cœur de son métier. Mieux vaut un No-Go juste
qu'un Go optimiste : chaque réponse coûte des jours de travail.

# Comment noter (score de 0 à 100)
Évalue chacun de ces critères, puis donne un score global cohérent :
1. Adéquation métier : le besoin correspond-il au catalogue (secourisme SST/MAC SST/PSC, incendie,
   évacuation, gestes et postures/TMS, QVT/RPS/stress, prévention des risques) ? Un marché où notre
   métier n'est qu'un petit lot parmi d'autres hors métier vaut moins. Hors métier = éliminatoire.
2. Exigences bloquantes : habilitations, certifications, agréments, CA minimum, effectif,
   moyens que l'entreprise n'a pas (ex. SSIAP, CACES, habilitation électrique, travaux, fournitures,
   gardiennage). Une exigence clairement non remplie = éliminatoire.
3. Taille et capacité : volume, nombre de sites, durée, montant par rapport à une petite structure
   d'intervenants. Un très gros accord-cadre national mono-attributaire est risqué ; un lot régional
   ou un marché de quelques dizaines de milliers d'euros est idéal.
4. Intensité concurrentielle probable : procédure adaptée (MAPA), petit acheteur, besoin spécifique,
   lots fins = concurrence faible. Gros acheteur national, publicité européenne, besoin standard
   très large = concurrence forte. Les offres reçues et titulaires sortants, s'ils sont connus, priment.
5. Place de la valeur technique : un poids technique élevé favorise un petit organisme avec une
   pédagogie forte ; un marché jugé surtout sur le prix (≥ 60 %) est défavorable.
6. Délai : moins de 10 jours avant la date limite est défavorable.
7. Géographie : intervention nationale possible, mais un marché très étendu multi-sites demande
   une logistique à vérifier.

Barème indicatif : 80-100 = Go net (cœur de métier, aucune exigence bloquante, taille adaptée) ;
60-79 = Go probable ou À étudier ; 40-59 = À étudier avec réserves ; < 40 = No-Go.
Tout critère éliminatoire plafonne le score à 30 et impose NO_GO.

# Règles
- Appuie-toi uniquement sur le texte de l'avis et le profil. N'invente ni montant, ni critère, ni
  exigence : si l'information manque, dis-le (et ajoute-la aux questions à vérifier dans le DCE).
- Écris en français simple et direct, phrases courtes.
"""


def _fmt_prix(v):
    return f"{v:.0f} € HT" if v is not None else "—"


def profil_entreprise() -> str:
    e = Entreprise.get()
    lignes = ["# Profil de l'entreprise"]
    if e:
        lignes.append(f"Nom : {e} ({e.raison_sociale})")
        lignes.append(f"Zone d'intervention : {e.zone_intervention}")
        certifs = []
        if e.qualiopi:
            certifs.append("Qualiopi")
        if e.habilitation_inrs_sst:
            certifs.append("Habilitation INRS pour la formation SST")
        if e.autres_certifications:
            certifs.append(e.autres_certifications)
        lignes.append(f"Certifications et habilitations : {', '.join(certifs) or 'aucune renseignée'}")
        if e.effectif or e.tranche_effectif:
            lignes.append(f"Effectif : {e.effectif or e.tranche_effectif}")
        if e.ca_n1:
            lignes.append(f"CA dernier exercice : {e.ca_n1:.0f} € HT")
        if e.presentation:
            lignes.append(f"Présentation : {e.presentation}")
        if e.points_forts:
            lignes.append(f"Points forts : {e.points_forts}")
    else:
        lignes.append("(profil non renseigné)")

    lignes.append("\n## Catalogue (prix de référence)")
    for p in Prestation.objects.filter(actif=True):
        groupe = f", groupe {p.groupe_min}-{p.groupe_max}" if p.groupe_min and p.groupe_max else ""
        lignes.append(
            f"- [{p.get_categorie_display()}] {p.intitule} — durée {p.duree or '?'}{groupe} — "
            f"intra {_fmt_prix(p.prix_intra_ht)}/session, inter {_fmt_prix(p.prix_inter_ht)}/participant"
        )

    lignes.append("\n## Formateurs")
    for f in Formateur.objects.filter(actif=True):
        quali = "; ".join(l.strip() for l in f.qualifications.splitlines() if l.strip())
        lignes.append(f"- {f} — {f.fonction}. {quali}")

    lignes.append("\n## Références")
    for r in Reference.objects.all()[:20]:
        vol = f" ({r.volume})" if r.volume else ""
        lignes.append(f"- {r.client}{vol} : {r.objet}")
    return "\n".join(lignes)


def description_avis(a: AvisMarche) -> str:
    deps = a.departements or "non précisé"
    lignes = [
        f"Source : {a.get_source_display()} {a.source_id}",
        f"Objet : {a.objet}",
        f"Acheteur : {a.acheteur or 'non précisé'}",
        f"Départements : {deps}",
        f"Lieu d'exécution : {a.lieu_execution or 'non précisé'}",
        f"Procédure : {a.procedure or 'non précisée'}",
        f"Type de marché : {a.type_marche or 'non précisé'}",
        f"Codes CPV : {a.cpv or 'non précisés'}",
        f"Montant estimé : {f'{a.montant_estime:.0f} € HT' if a.montant_estime else 'non précisé'}",
        f"Date de publication : {a.date_publication or 'non précisée'}",
        f"Date limite de réponse : {a.date_limite:%d/%m/%Y %H:%M}" if a.date_limite else "Date limite : non précisée",
    ]
    if a.jours_restants is not None:
        lignes.append(f"Jours restants avant la date limite : {a.jours_restants}")
    if a.mots_cles_trouves:
        lignes.append(f"Mots-clés de veille détectés : {a.mots_cles_trouves}")
    if a.texte:
        lignes.append(f"\nTexte de l'avis :\n{a.texte}")
    lignes.append(f"\n(Nous sommes le {timezone.localdate():%d/%m/%Y}.)")
    return "\n".join(lignes)


# --------------------------------------------------------------------------
# Appel IA
# --------------------------------------------------------------------------


def _client() -> anthropic.Anthropic:
    # ANTHROPIC_API_KEY prime ; VEILLE_ANTHROPIC_API_KEY sert de repli
    # (clé dédiée à l'application, sans collision avec d'autres outils).
    cle = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("VEILLE_ANTHROPIC_API_KEY")
    if cle:
        return anthropic.Anthropic(api_key=cle)
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return anthropic.Anthropic()
    raise ScoringIndisponible(
        "Aucune clé API Anthropic : renseignez ANTHROPIC_API_KEY "
        "(ou VEILLE_ANTHROPIC_API_KEY) dans le fichier .env."
    )


def scorer(avis: AvisMarche, client: anthropic.Anthropic | None = None, profil: str | None = None) -> ScoreAvis:
    """Score un avis et enregistre le résultat. Lève ScoringIndisponible si l'IA ne répond pas."""
    client = client or _client()
    profil = profil if profil is not None else profil_entreprise()

    reponse = client.beta.messages.parse(
        model=settings.CLAUDE_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": settings.CLAUDE_EFFORT},
        system=[
            {
                "type": "text",
                "text": f"{profil}\n\n{REGLES}",
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Évalue cet avis de marché :\n\n{description_avis(avis)}",
            }
        ],
        output_format=ScoreAvis,
    )

    if reponse.stop_reason == "refusal":
        raise ScoringIndisponible("L'IA a refusé de traiter cet avis.")
    if reponse.stop_reason == "max_tokens" or reponse.parsed_output is None:
        raise ScoringIndisponible(f"Réponse IA incomplète (stop_reason={reponse.stop_reason}).")

    resultat: ScoreAvis = reponse.parsed_output
    enregistrer(avis, resultat, modele=reponse.model)
    return resultat


def enregistrer(avis: AvisMarche, r: ScoreAvis, modele: str = "") -> None:
    score = max(0, min(100, r.score))
    if any(c.evaluation == "eliminatoire" for c in r.criteres):
        score = min(score, 30)
    avis.score = score
    avis.recommandation = r.recommandation if score > 30 else "NO_GO"
    avis.resume = r.resume
    avis.score_details = r.model_dump()
    avis.score_modele = modele
    avis.score_le = timezone.now()
    if avis.statut in ("DETECTE",):
        avis.statut = "A_QUALIFIER"
    avis.save()


# --------------------------------------------------------------------------
# Score de secours, par règles (sans IA)
# --------------------------------------------------------------------------

def score_regles(avis: AvisMarche) -> ScoreAvis:
    """Score indicatif quand l'IA n'est pas disponible : à confirmer par une lecture humaine."""
    from .texte import mots_cles_trouves, normaliser

    profil = avis.profil
    forts = mots_cles_trouves(f"{avis.objet}\n{avis.texte}", profil.liste_forts) if profil else []
    forts_objet = mots_cles_trouves(avis.objet, profil.liste_forts + profil.liste_mots_cles) if profil else []
    generiques = mots_cles_trouves(f"{avis.objet}\n{avis.texte}", profil.liste_mots_cles) if profil else []
    score = 20 + 14 * min(len(forts), 3) + 5 * min(len(generiques), 3) + 8 * min(len(forts_objet), 2)
    criteres = [
        Critere(
            critere="Adéquation métier",
            evaluation="favorable" if forts else ("neutre" if generiques else "defavorable"),
            commentaire=f"Mots-clés forts : {', '.join(forts) or 'aucun'} ; génériques : {', '.join(generiques) or 'aucun'}",
        )
    ]
    proc = normaliser(avis.procedure)
    if "adapt" in proc:
        score += 6
        criteres.append(Critere(critere="Concurrence", evaluation="favorable", commentaire="Procédure adaptée."))
    if avis.jours_restants is not None and avis.jours_restants < 10:
        score -= 15
        criteres.append(
            Critere(critere="Délai", evaluation="defavorable", commentaire=f"{avis.jours_restants} jours restants.")
        )
    score = max(0, min(70, score))  # sans IA, jamais de « Go » franc
    return ScoreAvis(
        score=score,
        recommandation="A_ETUDIER" if score >= 40 else "NO_GO",
        resume="",
        pourquoi="Score calculé par règles (IA non disponible) : à confirmer à la lecture.",
        criteres=criteres,
        prestations_concernees=[],
        part_du_besoin_couverte="partielle" if forts else "aucune",
        lots_a_viser=[],
        exigences_bloquantes=[],
        concurrence_estimee="inconnue",
        points_de_vigilance=[],
        questions_a_verifier=[],
    )
