"""Phase 2 : génération des pièces de candidature à partir du profil entreprise.

Les formulaires DC1 et DC2 sont des modèles facultatifs proposés par la Direction
des affaires juridiques (DAJ) : l'acheteur ne peut pas en imposer la forme, seul
le contenu compte. On reproduit donc leur structure (rubriques A à H pour le DC1,
A à F pour le DC2). Si l'acheteur fournit ses propres modèles, il faut les utiliser :
ces documents servent alors de base de recopie.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass

from django.utils import timezone

from ..models import AvisMarche, Entreprise, Formateur, PieceAdministrative, Prestation, Reference
from . import docx_utils as dx
from .docx_utils import A_COMPLETER, case

# Pièces du coffre-fort attendues dans un dossier de candidature classique
PIECES_ATTENDUES = [
    ("KBIS", "Extrait Kbis de moins de 3 mois"),
    ("URSSAF", "Attestation de vigilance URSSAF (moins de 6 mois)"),
    ("FISCAL", "Attestation de régularité fiscale"),
    ("RCPRO", "Attestation d'assurance RC professionnelle en cours"),
    ("QUALIOPI", "Certificat Qualiopi"),
    ("INRS", "Habilitation INRS (formation SST)"),
    ("NDA", "Déclaration d'activité d'organisme de formation"),
    ("RIB", "RIB"),
]


def _e() -> Entreprise:
    e = Entreprise.get()
    if not e:
        raise ValueError("Le profil entreprise n'est pas renseigné (Paramètres > Entreprise).")
    return e


def _adresse(e: Entreprise) -> str:
    return " ".join(x for x in [e.adresse, e.code_postal, e.ville] if x)


def _effectif(e: Entreprise) -> str:
    return str(e.effectif) if e.effectif else (f"{e.tranche_effectif} (INSEE)" if e.tranche_effectif else "")


def _capital(e: Entreprise) -> str:
    return _montant_brut(e.capital) if e.capital else ""


def _montant_brut(v) -> str:
    return f"{v:,.0f} €".replace(",", " ")


def _etablissements(e: Entreprise) -> str:
    return "\n".join(l.strip() for l in (e.etablissements or "").splitlines() if l.strip())


def _ref_avis(a: AvisMarche) -> str:
    ref = f"{a.get_source_display()} n° {a.source_id}" if a.source in ("BOAMP", "TED") else ""
    return ref or "Consultation directe"


def _lots(a: AvisMarche) -> tuple[bool, str]:
    lots = a.lots_vises.strip()
    return (not lots, lots)


def _entete(doc, code: str, titre: str, sous_titre: str):
    dx.para(doc, "MARCHÉS PUBLICS", gras=True, taille=9)
    dx.titre(doc, f"{code} – {titre}", 1)
    dx.para(doc, sous_titre, italique=True, taille=9)


def _montant(v) -> str:
    return f"{v:,.0f} € HT".replace(",", " ") if v else ""


# ---------------------------------------------------------------------------
# DC1 – Lettre de candidature
# ---------------------------------------------------------------------------


def dc1(a: AvisMarche) -> bytes:
    e = _e()
    doc = dx.nouveau_document()
    _entete(
        doc,
        "DC1",
        "Lettre de candidature",
        "Désignation du mandataire par ses co-traitants. Reproduction du modèle de la DAJ, "
        "pré-remplie par l'outil de veille FORMA'ST : à vérifier avant envoi.",
    )

    dx.titre(doc, "A – Identification de l'acheteur", 2)
    dx.tableau_cles(doc, [("Acheteur", a.acheteur), ("Référence de l'avis", _ref_avis(a))])

    dx.titre(doc, "B – Objet de la consultation", 2)
    dx.para(doc, a.objet)

    dx.titre(doc, "C – Objet de la candidature", 2)
    global_, lots = _lots(a)
    dx.para(doc, f"{case(global_)} au marché public (ou à l'accord-cadre) dans son ensemble")
    dx.para(doc, f"{case(not global_)} au(x) lot(s) n° {lots or '…'}")

    dx.titre(doc, "D – Présentation du candidat", 2)
    dx.para(doc, f"{case(True)} Le candidat se présente seul.")
    dx.para(doc, f"{case(False)} Le candidat est un groupement d'entreprises.")
    dx.tableau_cles(
        doc,
        [
            ("Nom commercial et dénomination sociale", f"{e.nom_commercial or e.raison_sociale} ({e.forme_juridique})"),
            ("Adresse du siège", _adresse(e)),
            ("Adresse électronique", e.email),
            ("Téléphone", e.telephone),
            ("N° SIRET", e.siret),
        ],
    )

    dx.titre(doc, "E – Identification des membres du groupement et répartition des prestations", 2)
    dx.para(doc, "Sans objet : candidature individuelle.")

    dx.titre(doc, "F – Engagements du candidat", 2)
    dx.titre(doc, "F1 – Attestations sur l'honneur", 3)
    dx.para(doc, "Le candidat individuel déclare sur l'honneur :")
    dx.para(
        doc,
        "a) n'entrer dans aucun des cas d'exclusion de la procédure de passation prévus aux articles "
        "L. 2141-1 à L. 2141-5 et L. 2141-7 à L. 2141-11 du code de la commande publique ;",
    )
    dx.para(
        doc,
        "b) être en règle au regard des articles L. 5212-1 à L. 5212-11 du code du travail concernant "
        "l'emploi des travailleurs handicapés.",
    )
    dx.titre(doc, "F2 – Capacités", 3)
    dx.para(doc, f"{case(True)} Le candidat présente ses capacités dans le formulaire DC2 joint.")
    dx.titre(doc, "F3 – Documents de preuve disponibles en ligne", 3)
    dx.para(doc, "Les justificatifs (Kbis, attestations sociales et fiscales, Qualiopi) sont joints au dossier "
                 "ou fournis sur simple demande.")

    dx.titre(doc, "G – Désignation du mandataire (en cas de groupement)", 2)
    dx.para(doc, "Sans objet.")

    dx.titre(doc, "H – Signature", 2)
    dx.tableau_cles(
        doc,
        [
            ("Nom, prénom et qualité du signataire", f"{e.representant_nom}, {e.representant_qualite}"),
            ("Lieu et date", f"{e.ville}, le {A_COMPLETER}"),
            ("Signature", ""),
        ],
    )
    dx.pied(doc, f"{e} – SIRET {e.siret} – DC1 – {a.objet[:80]}")
    return dx.en_octets(doc)


# ---------------------------------------------------------------------------
# DC2 – Déclaration du candidat
# ---------------------------------------------------------------------------


def dc2(a: AvisMarche) -> bytes:
    e = _e()
    doc = dx.nouveau_document()
    _entete(
        doc,
        "DC2",
        "Déclaration du candidat individuel ou du membre du groupement",
        "Reproduction du modèle de la DAJ, pré-remplie par l'outil de veille FORMA'ST : à vérifier avant envoi.",
    )

    dx.titre(doc, "A – Identification de l'acheteur", 2)
    dx.tableau_cles(doc, [("Acheteur", a.acheteur), ("Référence de l'avis", _ref_avis(a))])

    dx.titre(doc, "B – Objet de la consultation", 2)
    global_, lots = _lots(a)
    dx.para(doc, a.objet)
    dx.para(doc, "Marché dans son ensemble" if global_ else f"Lot(s) n° {lots}")

    dx.titre(doc, "C – Identification du candidat", 2)
    dx.tableau_cles(
        doc,
        [
            ("Nom commercial et dénomination sociale", e.nom_commercial or e.raison_sociale),
            ("Forme juridique et capital", " – capital de ".join(x for x in [e.forme_juridique, _capital(e)] if x)),
            ("Adresse du siège social", _adresse(e)),
            ("Autres établissements", _etablissements(e) or "Néant"),
            ("Adresse électronique", e.email),
            ("Téléphone", e.telephone),
            ("N° SIRET", e.siret),
            ("N° TVA intracommunautaire", e.tva_intracommunautaire),
            ("Code NAF", e.code_naf),
            ("N° de déclaration d'activité (organisme de formation)", e.numero_declaration_activite),
            ("Représentant habilité à engager le candidat", f"{e.representant_nom}, {e.representant_qualite}"),
            ("Le candidat est une micro, petite ou moyenne entreprise", "Oui"),
        ],
    )

    dx.titre(doc, "D – Situation juridique", 2)
    dx.para(doc, f"Le candidat est-il en redressement judiciaire ?  {case(False)} Oui   {case(True)} Non")

    dx.titre(doc, "E – Capacités du candidat", 2)
    dx.titre(doc, "E1 – Capacité économique et financière", 3)
    dx.tableau(
        doc,
        ["", "Dernier exercice", "Avant-dernier exercice", "Antépénultième exercice"],
        [
            [
                "Chiffre d'affaires global HT",
                _montant(e.ca_n1) or A_COMPLETER,
                _montant(e.ca_n2) or A_COMPLETER,
                _montant(e.ca_n3) or A_COMPLETER,
            ],
            ["Part du chiffre d'affaires concernant les prestations objet du marché", A_COMPLETER, A_COMPLETER, A_COMPLETER],
        ],
    )
    dx.tableau_cles(doc, [("Assurance responsabilité civile professionnelle", _piece_libelle("RCPRO"))])

    dx.titre(doc, "E2 – Capacités techniques et professionnelles", 3)
    dx.tableau_cles(
        doc,
        [
            ("Effectif", _effectif(e)),
            ("Certifications et habilitations", _certifs(e)),
            ("Zone d'intervention", e.zone_intervention),
        ],
    )
    dx.para(doc, "Principales références (prestations similaires) :", gras=True)
    refs = Reference.objects.filter(citable=True)
    dx.tableau(
        doc,
        ["Client", "Objet", "Période", "Volume / montant"],
        [
            [
                r.client,
                r.objet,
                " – ".join(f"{d:%m/%Y}" for d in [r.date_debut, r.date_fin] if d),
                r.volume or _montant(r.montant_ht),
            ]
            for r in refs
        ]
        or [[A_COMPLETER, "", "", ""]],
    )
    dx.para(doc, "Intervenants :", gras=True)
    dx.tableau(
        doc,
        ["Intervenant", "Fonction", "Qualifications"],
        [[str(f), f.fonction, "; ".join(l.strip() for l in f.qualifications.splitlines() if l.strip())]
         for f in Formateur.objects.filter(actif=True)],
    )
    dx.para(doc, "Moyens matériels :", gras=True)
    dx.para(doc, _points_forts_courts(e) or A_COMPLETER)

    dx.titre(doc, "F – Capacités des autres opérateurs économiques", 2)
    dx.para(doc, "Sans objet : le candidat ne s'appuie pas sur les capacités d'autres opérateurs.")

    dx.pied(doc, f"{e} – SIRET {e.siret} – DC2 – {a.objet[:80]}")
    return dx.en_octets(doc)


def _certifs(e: Entreprise) -> str:
    c = []
    if e.qualiopi:
        fin = f", valable jusqu'au {e.qualiopi_expiration:%d/%m/%Y}" if e.qualiopi_expiration else ""
        c.append(f"Certification Qualiopi (actions de formation){fin}")
    if e.habilitation_inrs_sst:
        fin = f", valable jusqu'au {e.habilitation_inrs_sst_expiration:%d/%m/%Y}" if e.habilitation_inrs_sst_expiration else ""
        c.append(f"Habilitation INRS pour la formation Sauveteur Secouriste du Travail{fin}")
    if e.numero_declaration_activite:
        c.append(f"Organisme de formation déclaré (n° {e.numero_declaration_activite})")
    return " ; ".join(c)


def _points_forts_courts(e: Entreprise) -> str:
    lignes = [l.strip() for l in (e.points_forts or "").splitlines() if l.strip()]
    return " ".join(lignes[:3])


def _piece_libelle(type_: str) -> str:
    p = PieceAdministrative.objects.filter(type=type_).order_by("-date_expiration").first()
    if not p:
        return ""
    fin = f", valable jusqu'au {p.date_expiration:%d/%m/%Y}" if p.date_expiration else ""
    return f"{p}{fin}"


# ---------------------------------------------------------------------------
# Attestation sur l'honneur, présentation, aide DUME
# ---------------------------------------------------------------------------


def attestation_honneur(a: AvisMarche) -> bytes:
    e = _e()
    doc = dx.nouveau_document()
    dx.titre(doc, "Déclaration sur l'honneur", 1)
    dx.para(doc, f"Consultation : {a.objet}")
    dx.para(doc, f"Acheteur : {a.acheteur}")
    dx.para(doc, "")
    dx.para(
        doc,
        f"Je soussigné(e) {e.representant_nom}, agissant en qualité de {e.representant_qualite} de la société "
        f"{e.raison_sociale} ({e.forme_juridique}), SIRET {e.siret}, dont le siège est situé {_adresse(e)}, "
        "déclare sur l'honneur que la société :",
    )
    for texte in [
        "n'entre dans aucun des cas d'exclusion de la procédure de passation des marchés publics prévus aux "
        "articles L. 2141-1 à L. 2141-5 et L. 2141-7 à L. 2141-11 du code de la commande publique ;",
        "est en règle au regard des articles L. 5212-1 à L. 5212-11 du code du travail concernant l'emploi des "
        "travailleurs handicapés ;",
        "que les renseignements fournis dans le dossier de candidature sont exacts.",
    ]:
        dx.ajouter_texte(doc.add_paragraph(style="List Bullet"), texte)
    dx.para(doc, "")
    dx.para(doc, f"Fait à {e.ville}, le {A_COMPLETER}")
    dx.para(doc, f"{e.representant_nom}, {e.representant_qualite}")
    dx.para(doc, "Signature :")
    dx.pied(doc, f"{e} – SIRET {e.siret}")
    return dx.en_octets(doc)


def presentation(a: AvisMarche | None = None) -> bytes:
    """Présentation de la structure : identité, certifications, offre, intervenants, références.
    Les prix ne figurent pas dans ce document."""
    e = _e()
    doc = dx.nouveau_document()
    dx.titre(doc, f"Présentation de {e}", 1)
    if a:
        dx.para(doc, f"Dans le cadre de la consultation : {a.objet} – {a.acheteur}", italique=True)
    dx.tableau_cles(
        doc,
        [
            ("Raison sociale", f"{e.raison_sociale} ({e.forme_juridique})"),
            ("Création", f"{e.date_creation:%Y}" if e.date_creation else ""),
            ("Siège", _adresse(e)),
            ("SIRET", e.siret),
            ("Effectif", _effectif(e)),
            ("Déclaration d'activité", e.numero_declaration_activite),
            ("Certifications", _certifs(e)),
            ("Représentant", f"{e.representant_nom}, {e.representant_qualite}"),
            ("Zone d'intervention", e.zone_intervention),
        ],
    )
    if e.presentation:
        dx.titre(doc, "Qui sommes-nous ?", 2)
        dx.para(doc, e.presentation)
    if e.points_forts:
        dx.titre(doc, "Nos points forts", 2)
        for l in e.points_forts.splitlines():
            if l.strip():
                dx.ajouter_texte(doc.add_paragraph(style="List Bullet"), l.strip())
    dx.titre(doc, "Notre offre", 2)
    for cat, libelle in Prestation.CATEGORIES:
        items = Prestation.objects.filter(actif=True, categorie=cat).exclude(intitule__icontains="frais")
        if items:
            dx.para(doc, libelle, gras=True)
            for p in items:
                duree = f" ({p.duree})" if p.duree else ""
                dx.ajouter_texte(doc.add_paragraph(style="List Bullet"), f"{p.intitule}{duree}")
    dx.titre(doc, "Nos intervenants", 2)
    for f in Formateur.objects.filter(actif=True):
        dx.para(doc, f"{f} – {f.fonction}", gras=True)
        for l in f.qualifications.splitlines():
            if l.strip():
                dx.ajouter_texte(doc.add_paragraph(style="List Bullet"), l.strip())
    refs = Reference.objects.filter(citable=True)
    if refs:
        dx.titre(doc, "Nos références", 2)
        for r in refs:
            vol = f" – {r.volume}" if r.volume else ""
            dx.ajouter_texte(doc.add_paragraph(style="List Bullet"), f"**{r.client}** : {r.objet}{vol}")
    dx.pied(doc, f"{e} – SIRET {e.siret}")
    return dx.en_octets(doc)


def aide_dume(a: AvisMarche) -> bytes:
    """Fiche d'aide à la saisie du DUME (le DUME se remplit sur le service en ligne
    de l'acheteur ou sur le service DUME de l'État)."""
    e = _e()
    doc = dx.nouveau_document()
    dx.titre(doc, "Aide à la saisie du DUME", 1)
    dx.para(doc, "Réponses à recopier dans le DUME en ligne (si l'acheteur le demande à la place des DC1/DC2).",
            italique=True)
    dx.titre(doc, "Partie I – Procédure", 2)
    dx.tableau_cles(doc, [("Acheteur", a.acheteur), ("Objet", a.objet), ("Référence", _ref_avis(a))])
    dx.titre(doc, "Partie II – Opérateur économique", 2)
    dx.tableau_cles(
        doc,
        [
            ("Nom", e.raison_sociale),
            ("SIRET / TVA", " / ".join(x for x in [e.siret, e.tva_intracommunautaire] if x)),
            ("Adresse", _adresse(e)),
            ("Contact", " – ".join(x for x in [e.representant_nom, e.email, e.telephone] if x)),
            ("Micro, petite ou moyenne entreprise", "Oui"),
            ("Candidature en groupement", "Non"),
            ("Recours aux capacités d'autres entités", "Non"),
            ("Sous-traitance envisagée", "Non"),
            ("Représentant", f"{e.representant_nom}, {e.representant_qualite}"),
            ("Lots", a.lots_vises or "Marché dans son ensemble"),
        ],
    )
    dx.titre(doc, "Partie III – Motifs d'exclusion", 2)
    dx.para(doc, "Condamnations pénales, impôts et cotisations, insolvabilité, faute professionnelle, conflits "
                 "d'intérêts : répondre « Non » à chaque motif (cohérent avec la déclaration sur l'honneur).")
    dx.titre(doc, "Partie IV – Critères de sélection", 2)
    dx.tableau_cles(
        doc,
        [
            ("Chiffre d'affaires annuel (3 derniers exercices)",
             " / ".join(_montant(x) or A_COMPLETER for x in [e.ca_n1, e.ca_n2, e.ca_n3])),
            ("Effectif", _effectif(e)),
            ("Certificats de qualité", _certifs(e)),
            ("Références", "; ".join(f"{r.client} ({r.objet})" for r in Reference.objects.filter(citable=True))),
        ],
    )
    dx.titre(doc, "Partie VI – Déclarations finales", 2)
    dx.para(doc, f"Signataire : {e.representant_nom}, {e.representant_qualite}.")
    return dx.en_octets(doc)


# ---------------------------------------------------------------------------
# Dossier complet
# ---------------------------------------------------------------------------


@dataclass
class ControlePiece:
    type: str
    libelle: str
    statut: str  # ok, expiree, manquante
    detail: str
    piece: PieceAdministrative | None = None


def controler_pieces(a: AvisMarche) -> list[ControlePiece]:
    """Vérifie chaque pièce attendue au regard de la date limite de l'avis."""
    jour = a.date_limite.date() if a.date_limite else timezone.localdate()
    e = Entreprise.get()
    resultats = []
    for type_, libelle in PIECES_ATTENDUES:
        if type_ == "INRS" and e and not e.habilitation_inrs_sst:
            continue
        p = PieceAdministrative.objects.filter(type=type_).exclude(fichier="").order_by("-date_expiration").first()
        if not p:
            resultats.append(ControlePiece(type_, libelle, "manquante", "Pas de fichier dans le coffre-fort"))
        elif not p.valide_le(jour):
            resultats.append(
                ControlePiece(type_, libelle, "expiree", f"Expirée ou expirant le {p.date_expiration:%d/%m/%Y}", p)
            )
        else:
            fin = f"valable jusqu'au {p.date_expiration:%d/%m/%Y}" if p.date_expiration else "sans date d'expiration"
            resultats.append(ControlePiece(type_, libelle, "ok", fin, p))
    return resultats


GENERATEURS = {
    "dc1": ("DC1_lettre_de_candidature.docx", dc1),
    "dc2": ("DC2_declaration_du_candidat.docx", dc2),
    "attestation": ("Declaration_sur_l_honneur.docx", attestation_honneur),
    "presentation": ("Presentation_FORMAST.docx", presentation),
    "dume": ("Aide_saisie_DUME.docx", aide_dume),
}


def generateurs_pour(a: AvisMarche) -> list[str]:
    """Les formulaires DC1/DC2/DUME ne concernent que les marchés publics."""
    if a.source == "PRIVE":
        return ["presentation"]
    return ["dc1", "dc2", "attestation", "presentation", "dume"]


def dossier_zip(a: AvisMarche, memoire_docx: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    controles = controler_pieces(a)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i, cle in enumerate([c for c in generateurs_pour(a) if c != "dume"], start=1):
            nom, fn = GENERATEURS[cle]
            z.writestr(f"1_Candidature/{i:02d}_{nom}", fn(a))
        for i, c in enumerate([c for c in controles if c.piece and c.statut == "ok"], start=5):
            ext = c.piece.fichier.name.rsplit(".", 1)[-1] if "." in c.piece.fichier.name else "pdf"
            with c.piece.fichier.open("rb") as f:
                z.writestr(f"1_Candidature/{i:02d}_{c.type}.{ext}", f.read())
        if memoire_docx:
            z.writestr("2_Offre/Memoire_technique_FORMAST.docx", memoire_docx)
        z.writestr("A_LIRE_check-list.txt", check_list_texte(a, controles))
    return buf.getvalue()


def check_list_texte(a: AvisMarche, controles: list[ControlePiece]) -> str:
    lignes = [
        f"Dossier : {a.objet}",
        f"Acheteur : {a.acheteur}",
        f"Date limite : {a.date_limite:%d/%m/%Y %H:%M}" if a.date_limite else "Date limite : non précisée",
        "",
        "À FAIRE AVANT DÉPÔT",
        "- Relire DC1/DC2 : compléter les champs surlignés [À COMPLÉTER], dater et signer.",
        "- Si l'acheteur fournit ses propres formulaires (DC1, DC2, acte d'engagement), les utiliser.",
        "- Vérifier la liste des pièces exigées dans le règlement de consultation.",
        "",
        "PIÈCES ADMINISTRATIVES (au regard de la date limite)",
    ]
    symbole = {"ok": "[OK]", "expiree": "[EXPIRÉE]", "manquante": "[MANQUANTE]"}
    for c in controles:
        lignes.append(f"{symbole[c.statut]:<12} {c.libelle} – {c.detail}")
    return "\n".join(lignes) + "\n"
