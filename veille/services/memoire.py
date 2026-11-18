"""Phase 3 : brouillon de mémoire technique, export Word et grille de conformité."""

from __future__ import annotations

import io
import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from ..models import AvisMarche, BlocContenu, Entreprise, Memoire
from . import dce, scoring
from . import docx_utils as dx

log = logging.getLogger("veille.memoire")

PLAN_PAR_DEFAUT = [
    "Présentation de l'organisme et compréhension du besoin",
    "Programme et contenus proposés (objectifs, déroulé, durée)",
    "Méthodes et moyens pédagogiques",
    "Intervenants et encadrement",
    "Organisation, planification et logistique",
    "Évaluation des acquis, satisfaction et suivi",
    "Démarche qualité, accessibilité et engagements",
]

CONSIGNES_MEMOIRE = """\
# Ta mission
Rédige le BROUILLON du mémoire technique (offre technique) de l'organisme décrit ci-dessus, en
réponse au dossier joint. Un humain le relira, le complétera et le signera.

# Règles impératives
1. Suis EXACTEMENT le plan fourni, dans l'ordre, avec ces titres de sections (titres Markdown « ## »).
   Chaque section doit répondre aux attendus listés et au critère de jugement associé.
2. N'utilise que des faits présents dans le profil, la bibliothèque de contenus ou le dossier. Ne
   jamais inventer : nombre de stagiaires formés, années d'expérience, chiffres, références,
   certifications, noms, tarifs. Quand une information manque, écris
   « [À COMPLÉTER : ce qu'il faut préciser] » à l'endroit voulu.
3. Personnalise pour CET acheteur : reprends ses mots, son contexte, ses publics, ses contraintes
   (lieux, horaires, volumes, risques). Un mémoire générique perd des points.
4. Sois concret : déroulés de séquences, durées, méthodes actives, livrables, délais, indicateurs.
   Des tableaux Markdown sont bienvenus (programme, planning, évaluation).
5. Ne mets aucun prix dans le mémoire, sauf si le plan le demande explicitement.
6. Style : français professionnel, clair, phrases courtes, pas de superlatifs creux.
7. Commence directement par la première section (pas de page de titre ni de sommaire : ils sont
   ajoutés automatiquement). Termine par une courte section « Points à compléter avant envoi »
   qui récapitule les [À COMPLÉTER].
"""


def bibliotheque() -> str:
    lignes = ["# Bibliothèque de contenus (réutilisables, déjà validés)"]
    for b in BlocContenu.objects.filter(actif=True):
        lignes.append(f"\n## [{b.get_categorie_display()}] {b.titre}\n{b.texte}")
    return "\n".join(lignes)


def plan_texte(avis: AvisMarche) -> str:
    analyse = getattr(avis, "analyse", None)
    sections = (analyse.resultat or {}).get("plan_memoire") if analyse and analyse.statut == "OK" else None
    if not sections:
        return "Plan (par défaut, aucun cadre de réponse imposé connu) :\n" + "\n".join(
            f"{i}. {t}" for i, t in enumerate(PLAN_PAR_DEFAUT, 1)
        )
    lignes = ["Plan imposé (issu de l'analyse du DCE) :"]
    for i, s in enumerate(sections, 1):
        lignes.append(f"{i}. {s['titre']} — critère : {s.get('critere_lie', '')} — longueur : {s.get('longueur_conseillee', '')}")
        for att in s.get("attendus", []):
            lignes.append(f"   - attendu : {att}")
    return "\n".join(lignes)


def rediger(avis: AvisMarche, consignes: str = "", client=None, memoire: Memoire | None = None) -> Memoire:
    memoire = memoire or Memoire.objects.create(avis=avis, consignes=consignes, statut="EN_COURS")
    try:
        blocs = dce.blocs_documents(avis)
        if not blocs and avis.texte.strip():
            blocs = [
                {
                    "type": "document",
                    "title": "Texte de la consultation",
                    "source": {"type": "text", "media_type": "text/plain", "data": avis.texte},
                }
            ]
        demande = f"{plan_texte(avis)}\n\n{scoring.description_avis(avis)}"
        if consignes.strip():
            demande += f"\n\nConsignes particulières de l'équipe :\n{consignes.strip()}"
        client = client or scoring._client()
        with client.beta.messages.stream(
            model=settings.CLAUDE_MODEL,
            max_tokens=64000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "high"},
            system=[
                {
                    "type": "text",
                    "text": f"{scoring.profil_entreprise()}\n\n{bibliotheque()}\n\n{CONSIGNES_MEMOIRE}",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": blocs + [{"type": "text", "text": demande}]}],
        ) as flux:
            message = flux.get_final_message()
        if message.stop_reason == "refusal":
            raise scoring.ScoringIndisponible("L'IA a refusé de rédiger ce mémoire.")
        texte = "".join(b.text for b in message.content if b.type == "text").strip()
        if not texte:
            raise scoring.ScoringIndisponible("Réponse vide.")
        if message.stop_reason == "max_tokens":
            texte += "\n\n[À COMPLÉTER : la rédaction a été coupée (longueur maximale atteinte).]"
        memoire.contenu = texte
        memoire.modele = message.model
        memoire.fichier.save(f"memoire_{avis.pk}_{timezone.now():%Y%m%d%H%M}.docx", ContentFile(vers_docx(memoire)), save=False)
        memoire.statut = "OK"
        memoire.save()
        if avis.statut in ("DETECTE", "A_QUALIFIER", "GO"):
            avis.statut = "REDACTION"
            avis.save(update_fields=["statut"])
    except Exception as e:
        log.exception("Rédaction du mémoire impossible")
        memoire.statut = "ERREUR"
        memoire.erreur = str(e)[:2000]
        memoire.save()
    return memoire


def vers_docx(memoire: Memoire) -> bytes:
    a = memoire.avis
    e = Entreprise.get()
    doc = dx.nouveau_document()
    for _ in range(6):
        doc.add_paragraph()
    dx.para(doc, "MÉMOIRE TECHNIQUE", gras=True, taille=22)
    dx.para(doc, a.objet, gras=True, taille=14)
    dx.para(doc, f"Acheteur : {a.acheteur}", taille=12)
    if a.lots_vises:
        dx.para(doc, f"Lot(s) : {a.lots_vises}", taille=12)
    dx.para(doc, "")
    if e:
        dx.para(doc, f"Proposé par {e} – {e.adresse} {e.code_postal} {e.ville}", taille=11)
        dx.para(doc, f"SIRET {e.siret} – Déclaration d'activité n° {e.numero_declaration_activite}", taille=9)
    dx.para(doc, f"Version de travail du {memoire.cree_le or timezone.now():%d/%m/%Y}", italique=True, taille=9)
    doc.add_page_break()
    dx.markdown_vers_docx(doc, memoire.contenu)
    if e:
        dx.pied(doc, f"{e} – Mémoire technique – {a.objet[:90]}")
    return dx.en_octets(doc)


def grille_conformite(avis: AvisMarche) -> bytes:
    """Classeur Excel : critères (avec la section du mémoire qui y répond) et exigences."""
    analyse = getattr(avis, "analyse", None)
    r = (analyse.resultat or {}) if analyse else {}
    wb = Workbook()
    entete = Font(bold=True, color="FFFFFF")
    fond = PatternFill("solid", fgColor="B3261E")
    couleurs = {"remplie": "D9EAD3", "non_remplie": "F4CCCC", "a_verifier": "FFF2CC"}

    ws = wb.active
    ws.title = "Critères et mémoire"
    ws.append(["Critère", "Pondération", "Sous-critères", "Source", "Section(s) du mémoire", "Vérifié"])
    plan = r.get("plan_memoire", [])
    for c in r.get("criteres_jugement", []):
        sections = [s["titre"] for s in plan if c["nom"].lower()[:25] in s.get("critere_lie", "").lower()]
        ws.append([c["nom"], c.get("ponderation", ""), "\n".join(c.get("sous_criteres", [])), c.get("source", ""),
                   "\n".join(sections), ""])

    ws2 = wb.create_sheet("Exigences")
    ws2.append(["Exigence", "Source", "Statut", "Commentaire", "Où traité dans l'offre", "Vérifié"])
    for x in r.get("exigences", []):
        ws2.append([x["exigence"], x.get("source", ""), x.get("statut", ""), x.get("commentaire", ""), "", ""])
        couleur = couleurs.get(x.get("statut"))
        if couleur:
            ws2.cell(ws2.max_row, 3).fill = PatternFill("solid", fgColor=couleur)

    ws3 = wb.create_sheet("Pièces")
    ws3.append(["Pièce", "Étape", "Source", "État", "Détail", "Vérifié"])
    for p in dce.rapprocher_pieces(analyse) if analyse else []:
        ws3.append([p["piece"], p.get("etape", ""), p.get("source", ""), p["etat"], p["detail"], ""])

    for feuille, largeurs in [(ws, [40, 12, 50, 18, 40, 10]), (ws2, [60, 18, 14, 50, 30, 10]), (ws3, [50, 14, 18, 12, 40, 10])]:
        for i, l in enumerate(largeurs):
            feuille.column_dimensions[chr(65 + i)].width = l
        for cell in feuille[1]:
            cell.font, cell.fill = entete, fond
        for row in feuille.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        feuille.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
