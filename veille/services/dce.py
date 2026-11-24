"""Phase 3 : dépôt du DCE, extraction du texte et analyse par l'IA.

Les PDF sont transmis tels quels à Claude (lecture native, pages comprises),
les fichiers Word / Excel / texte sous forme de texte extrait.
"""

from __future__ import annotations

import base64
import io
import logging
import re
import zipfile
from pathlib import PurePosixPath
from typing import Literal

from django.conf import settings
from django.core.files.base import ContentFile
from pydantic import BaseModel, Field

from ..models import AnalyseDCE, AvisMarche, DocumentDCE, PieceAdministrative
from . import scoring
from .texte import normaliser

log = logging.getLogger("veille.dce")

EXTENSIONS = {"pdf", "docx", "xlsx", "xlsm", "txt", "csv", "md", "odt", "doc", "xls"}
TAILLE_MAX_FICHIER = 40 * 1024 * 1024
TAILLE_MAX_ZIP_DECOMPRESSE = 300 * 1024 * 1024
PDF_MAX_OCTETS_REQUETE = 24 * 1024 * 1024  # marge sous la limite de 32 Mo par requête
PDF_MAX_PAGES_REQUETE = 550


# ---------------------------------------------------------------------------
# Dépôt et extraction
# ---------------------------------------------------------------------------


def deviner_type(nom: str) -> str:
    n = normaliser(nom)
    if re.search(r"\b(rc|reglement)\b|reglement de (la )?consultation", n):
        return "RC"
    if re.search(r"\bcctp\b|cahier des (clauses techniques|charges)|\bcdc\b|\bcctp\b", n):
        return "CCTP"
    if re.search(r"\bccap\b|clauses administratives", n):
        return "CCAP"
    if re.search(r"\b(ae|attri1?)\b|acte d engagement", n):
        return "AE"
    if re.search(r"\b(bpu|dpgf|dqe)\b|bordereau|decomposition du prix|detail quantitatif", n):
        return "BPU"
    return "AUTRE"


def extraire_texte(nom: str, contenu: bytes) -> tuple[str, int | None]:
    """Renvoie (texte, nombre de pages) ; le texte des PDF sert à la recherche et en secours."""
    ext = nom.rsplit(".", 1)[-1].lower() if "." in nom else ""
    try:
        if ext == "pdf":
            from pypdf import PdfReader

            lecteur = PdfReader(io.BytesIO(contenu))
            pages = [p.extract_text() or "" for p in lecteur.pages]
            return "\n".join(pages), len(pages)
        if ext == "docx":
            from docx import Document

            doc = Document(io.BytesIO(contenu))
            lignes = [p.text for p in doc.paragraphs if p.text.strip()]
            for t in doc.tables:
                for r in t.rows:
                    cellules = []
                    for c in r.cells:
                        if c.text.strip() and c.text.strip() not in cellules:
                            cellules.append(c.text.strip())
                    if cellules:
                        lignes.append(" | ".join(cellules))
            return "\n".join(lignes), None
        if ext in ("xlsx", "xlsm"):
            from openpyxl import load_workbook

            wb = load_workbook(io.BytesIO(contenu), read_only=True, data_only=True)
            lignes = []
            for ws in wb.worksheets:
                lignes.append(f"### Feuille « {ws.title} »")
                for row in ws.iter_rows(values_only=True):
                    vals = [str(v).strip() for v in row if v not in (None, "")]
                    if vals:
                        lignes.append(" | ".join(vals))
            return "\n".join(lignes), None
        if ext in ("txt", "csv", "md"):
            return contenu.decode("utf-8", errors="replace"), None
    except Exception as e:  # fichier abîmé ou protégé : on le garde, sans texte
        log.warning("Extraction impossible pour %s : %s", nom, e)
        return "", None
    return "", None  # .doc, .xls, .odt : formats anciens non lus automatiquement


def _enregistrer(avis: AvisMarche, nom: str, contenu: bytes) -> DocumentDCE | None:
    ext = nom.rsplit(".", 1)[-1].lower() if "." in nom else ""
    if ext not in EXTENSIONS or len(contenu) > TAILLE_MAX_FICHIER or not contenu:
        return None
    texte, pages = extraire_texte(nom, contenu)
    doc = DocumentDCE(avis=avis, nom=nom[:255], type=deviner_type(nom), texte=texte, nb_pages=pages)
    doc.fichier.save(PurePosixPath(nom).name, ContentFile(contenu), save=False)
    doc.save()
    return doc


def ajouter_fichiers(avis: AvisMarche, fichiers) -> list[DocumentDCE]:
    """Ajoute des fichiers téléversés (PDF, Word, Excel ou archive ZIP du DCE)."""
    ajoutes = []
    for f in fichiers:
        contenu = f.read()
        if f.name.lower().endswith(".zip"):
            ajoutes += _depuis_zip(avis, contenu)
        else:
            d = _enregistrer(avis, f.name, contenu)
            if d:
                ajoutes.append(d)
    return ajoutes


def _depuis_zip(avis: AvisMarche, contenu: bytes, profondeur: int = 0) -> list[DocumentDCE]:
    ajoutes = []
    with zipfile.ZipFile(io.BytesIO(contenu)) as z:
        total = 0
        for info in z.infolist():
            if info.is_dir():
                continue
            chemin = PurePosixPath(info.filename.replace("\\", "/"))
            if ".." in chemin.parts or chemin.name.startswith(".") or "__MACOSX" in chemin.parts:
                continue
            total += info.file_size
            if total > TAILLE_MAX_ZIP_DECOMPRESSE:
                log.warning("Archive trop volumineuse, extraction arrêtée.")
                break
            data = z.read(info)
            if chemin.suffix.lower() == ".zip" and profondeur < 2:
                ajoutes += _depuis_zip(avis, data, profondeur + 1)
                continue
            d = _enregistrer(avis, chemin.name, data)
            if d:
                ajoutes.append(d)
    return ajoutes


# ---------------------------------------------------------------------------
# Schéma de l'analyse
# ---------------------------------------------------------------------------


class Lot(BaseModel):
    numero: str
    intitule: str
    pertinent_pour_nous: bool
    commentaire: str


class CritereJugement(BaseModel):
    nom: str
    ponderation: str = Field(description="Ex. « 60 % » ou « non précisée »")
    sous_criteres: list[str]
    source: str = Field(description="Document et page, ex. « RC p. 12 »")


class Piece(BaseModel):
    piece: str
    etape: Literal["candidature", "offre"]
    source: str


class Exigence(BaseModel):
    exigence: str
    source: str
    statut: Literal["remplie", "non_remplie", "a_verifier"] = Field(
        description="Au regard du profil de l'entreprise"
    )
    commentaire: str


class SectionPlan(BaseModel):
    titre: str
    critere_lie: str = Field(description="Critère ou sous-critère de jugement traité par cette section")
    attendus: list[str] = Field(description="Ce que l'acheteur attend concrètement dans cette section")
    longueur_conseillee: str


class AnalyseResultat(BaseModel):
    synthese: str = Field(description="Le besoin en une dizaine de lignes, en langage simple")
    objet: str
    lots: list[Lot]
    duree_et_volumes: str
    lieux_et_organisation: str
    forme_du_prix: str
    date_limite_offres: str
    date_limite_questions: str
    visite_ou_soutenance: str
    criteres_jugement: list[CritereJugement]
    pieces_a_fournir: list[Piece]
    exigences: list[Exigence]
    pieges_et_clauses_sensibles: list[str]
    questions_a_poser: list[str]
    plan_memoire: list[SectionPlan]
    prix_a_chiffrer: list[str] = Field(description="Lignes ou postes à chiffrer (BPU, DPGF, devis)")
    score: int = Field(description="0 à 100, même barème que le pré-score")
    recommandation: Literal["GO", "A_ETUDIER", "NO_GO"]
    justification: str


CONSIGNES_ANALYSE = """\
# Ta mission
Tu analyses le dossier de consultation (DCE ou cahier des charges) joint, pour l'organisme de
formation décrit ci-dessus. Tu dois permettre de décider en 5 minutes de répondre ou non, puis
de préparer la réponse sans rien oublier.

# Règles
- Ne t'appuie QUE sur les documents joints et le profil. Indique la source de chaque critère,
  pièce et exigence (nom du document et page, ex. « RC p. 4 », « CCTP §3.2 »).
- Si une information n'est pas dans les documents, écris « non précisé » : n'invente rien.
- Exigences : liste toutes celles qui conditionnent la recevabilité ou la note (habilitations,
  certifications, qualification des formateurs, délais, matériel, documents, assurances, CA…)
  et dis si le profil les remplit (remplie / non_remplie / a_verifier).
- Plan du mémoire : reprends EXACTEMENT la structure attendue par l'acheteur (critères et
  sous-critères, cadre de réponse imposé s'il existe), dans l'ordre. S'il n'y en a pas,
  propose un plan qui suit les attendus du cahier des charges.
- Pièces à fournir : toutes, candidature et offre, avec la source.
- Score et recommandation : même barème que pour le pré-score (critère éliminatoire = 30 max).
- Français simple, phrases courtes.
"""


# ---------------------------------------------------------------------------
# Construction de la requête et appel
# ---------------------------------------------------------------------------


def blocs_documents(avis: AvisMarche) -> list[dict]:
    """Blocs « document » : PDF natifs tant que le volume le permet, texte sinon."""
    blocs = []
    octets = pages = 0
    for d in avis.documents.all():
        titre = f"{d.get_type_display()} – {d.nom}"
        if d.extension == "pdf":
            with d.fichier.open("rb") as f:
                data = f.read()
            if octets + len(data) <= PDF_MAX_OCTETS_REQUETE and pages + (d.nb_pages or 0) <= PDF_MAX_PAGES_REQUETE:
                octets += len(data)
                pages += d.nb_pages or 0
                blocs.append(
                    {
                        "type": "document",
                        "title": titre,
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": base64.standard_b64encode(data).decode(),
                        },
                    }
                )
                continue
        if d.texte.strip():
            blocs.append(
                {
                    "type": "document",
                    "title": titre,
                    "source": {"type": "text", "media_type": "text/plain", "data": d.texte[:400_000]},
                }
            )
    return blocs


def analyser(avis: AvisMarche, client=None, forcer_budget: bool = False) -> AnalyseDCE:
    from . import couts

    analyse, _ = AnalyseDCE.objects.update_or_create(avis=avis, defaults={"statut": "EN_COURS", "erreur": ""})
    try:
        if not forcer_budget:
            scoring.verifier_budget()
        blocs = blocs_documents(avis)
        if not blocs:
            if not avis.texte.strip():
                raise scoring.ScoringIndisponible("Aucun document lisible : déposez le DCE (PDF, Word, Excel ou ZIP).")
            blocs = [
                {
                    "type": "document",
                    "title": "Texte de la consultation",
                    "source": {"type": "text", "media_type": "text/plain", "data": avis.texte},
                }
            ]
        client = client or scoring._client()
        reponse = client.beta.messages.parse(
            model=settings.CLAUDE_MODEL,
            max_tokens=32000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "high"},
            system=[
                {
                    "type": "text",
                    "text": f"{scoring.profil_entreprise()}\n\n{scoring.REGLES}\n\n{CONSIGNES_ANALYSE}",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": blocs
                    + [{"type": "text", "text": f"Analyse ce dossier.\n\n{scoring.description_avis(avis)}"}],
                }
            ],
            output_format=AnalyseResultat,
            timeout=900,
        )
        couts.enregistrer(reponse, "ANALYSE", avis)
        if reponse.stop_reason == "refusal":
            raise scoring.ScoringIndisponible("L'IA a refusé d'analyser ce dossier.")
        if reponse.parsed_output is None:
            raise scoring.ScoringIndisponible(f"Analyse incomplète (stop_reason={reponse.stop_reason}).")
        analyse.resultat = reponse.parsed_output.model_dump()
        analyse.modele = reponse.model
        analyse.statut = "OK"
        analyse.save()
        if avis.statut in ("DETECTE", "A_QUALIFIER"):
            avis.statut = "A_QUALIFIER"
            avis.save(update_fields=["statut"])
    except Exception as e:
        log.exception("Analyse du DCE impossible")
        analyse.statut = "ERREUR"
        analyse.erreur = str(e)[:2000]
        analyse.save()
    return analyse


# ---------------------------------------------------------------------------
# Rapprochement avec le coffre-fort
# ---------------------------------------------------------------------------

_CORRESPONDANCES = [
    ("KBIS", r"\bkbis\b|extrait.*registre|immatriculation"),
    ("URSSAF", r"urssaf|vigilance|attestation.*sociale|cotisations sociales"),
    ("FISCAL", r"fiscal|impots|regularite fiscale"),
    ("RCPRO", r"assurance|responsabilite civile"),
    ("QUALIOPI", r"qualiopi"),
    ("INRS", r"\binrs\b|habilitation.*sst"),
    ("NDA", r"declaration d activite|\bnda\b|numero de declaration"),
    ("RIB", r"\brib\b|releve d identite bancaire"),
    ("GEN:dc1", r"\bdc ?1\b|lettre de candidature"),
    ("GEN:dc2", r"\bdc ?2\b|declaration du candidat"),
    ("GEN:dume", r"\bdume\b"),
    ("GEN:attestation", r"sur l honneur"),
    ("GEN:presentation", r"presentation (de la structure|de l entreprise|de la societe)|references"),
    ("GEN:memoire", r"memoire technique|offre technique|note methodologique|programme"),
]


def rapprocher_pieces(analyse: AnalyseDCE) -> list[dict]:
    """Pour chaque pièce demandée : ce que l'outil fournit déjà (coffre-fort ou document généré)."""
    sortie = []
    jour = analyse.avis.date_limite.date() if analyse.avis.date_limite else None
    for p in (analyse.resultat or {}).get("pieces_a_fournir", []):
        n = normaliser(p.get("piece", ""))
        etat, detail = "a_faire", "À préparer"
        for cle, motif in _CORRESPONDANCES:
            if re.search(motif, n):
                if cle.startswith("GEN:"):
                    etat, detail = "genere", "Généré par l'outil (à relire)"
                else:
                    piece = PieceAdministrative.objects.filter(type=cle).exclude(fichier="").order_by(
                        "-date_expiration"
                    ).first()
                    if piece and (jour is None or piece.valide_le(jour)):
                        etat, detail = "ok", f"Dans le coffre-fort : {piece}"
                    elif piece:
                        etat, detail = "expiree", "Dans le coffre-fort mais expirée à la date limite"
                    else:
                        etat, detail = "manquante", "À déposer dans le coffre-fort"
                break
        sortie.append({**p, "etat": etat, "detail": detail})
    return sortie
