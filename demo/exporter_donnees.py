"""Exporte les données de la base vers demo/data.json (données de la démo FORM'AO).

Avis retenus, analyses du DCE, mémoires, collectes, profil, catalogue, consignes IA,
et les documents Word générés (DC1, DC2…) pour les avis qui ne sont pas des No-Go recommandés.

    .venv/bin/python demo/exporter_donnees.py [sortie.json]
"""
import base64
import datetime
import decimal
import html
import io
import json
import os
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from django.forms.models import model_to_dict  # noqa: E402
from docx import Document  # noqa: E402
from docx.table import Table  # noqa: E402
from docx.text.paragraph import Paragraph  # noqa: E402

from veille.models import (  # noqa: E402
    AnalyseDCE, AvisMarche, BlocContenu, Collecte, Entreprise, Formateur, Memoire,
    PieceAdministrative, Prestation, ProfilVeille, Reference,
)
from veille.services import accueil, annuaire, dce, documents, memoire, scoring  # noqa: E402


def propre(d):
    out = {}
    for k, v in d.items():
        if isinstance(v, (datetime.date, datetime.datetime)):
            v = v.isoformat()
        elif isinstance(v, decimal.Decimal):
            v = float(v)
        elif hasattr(v, "name") and hasattr(v, "url"):
            v = v.name or ""
        out[k] = v
    return out


def docx_en_html(data: bytes) -> str:
    """Aperçu HTML simple d'un .docx (paragraphes, titres, tableaux)."""
    doc = Document(io.BytesIO(data))
    parts = []
    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[1]
        if tag == "p":
            p = Paragraph(child, doc)
            t = html.escape(p.text)
            if not t.strip():
                continue
            t = t.replace("[À COMPLÉTER", '<mark>[À COMPLÉTER').replace("]", "]</mark>") if "[À COMPLÉTER" in t else t
            style = (p.style.name or "").lower()
            if "title" in style or "heading 1" in style:
                parts.append(f"<h3>{t}</h3>")
            elif "heading" in style:
                parts.append(f"<h4>{t}</h4>")
            else:
                parts.append(f"<p>{t}</p>")
        elif tag == "tbl":
            lignes = []
            for r in Table(child, doc).rows:
                cellules, prec = [], None
                for c in r.cells:
                    if c._tc is prec:
                        continue
                    prec = c._tc
                    cellules.append("<td>" + html.escape(c.text).replace("\n", "<br>") + "</td>")
                lignes.append("<tr>" + "".join(cellules) + "</tr>")
            parts.append("<table>" + "".join(lignes) + "</table>")
    return "\n".join(parts)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def main():
    sortie = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RACINE, "demo", "data.json")
    avis = []
    for a in AvisMarche.objects.filter(prefiltre_ok=True).order_by("-score", "date_limite"):
        d = propre(model_to_dict(a, exclude=["brut", "profil"]))
        d["id"] = a.pk
        d["cree_le"] = a.cree_le.isoformat()
        docs = {}
        if a.recommandation != "NO_GO" or a.statut not in ("DETECTE", "A_QUALIFIER"):
            for cle in documents.generateurs_pour(a):
                nom, fn = documents.GENERATEURS[cle]
                try:
                    data = fn(a)
                    docs[cle] = {"nom": nom, "html": docx_en_html(data), "b64": b64(data)}
                except Exception as ex:  # document impossible : on le signale dans la démo
                    docs[cle] = {"nom": nom, "erreur": str(ex)}
        d["documents"] = docs
        avis.append(d)

    analyses = {}
    for x in AnalyseDCE.objects.filter(statut="OK"):
        analyses[x.avis_id] = {"resultat": x.resultat}
        try:
            analyses[x.avis_id]["grille_b64"] = b64(memoire.grille_conformite(x.avis))
        except Exception:
            pass
    memoires = {}
    for m in Memoire.objects.filter(statut="OK").order_by("cree_le"):
        memoires[m.avis_id] = {"contenu": m.contenu, "cree_le": m.cree_le.isoformat(), "consignes": m.consignes,
                               "docx_b64": b64(memoire.vers_docx(m))}

    e = Entreprise.get()
    data = {
        "exporte_le": datetime.datetime.now().isoformat(),
        "entreprise": propre(model_to_dict(e)),
        "completude": [{"champ": c, "libelle": l, "obligatoire": o} for c, l, o in annuaire.CHAMPS_DOCUMENTS],
        "prestations": [propre(model_to_dict(p)) for p in Prestation.objects.all()],
        "formateurs": [propre(model_to_dict(p, exclude=["cv"])) for p in Formateur.objects.all()],
        "references": [propre(model_to_dict(p, exclude=["document"])) for p in Reference.objects.all()],
        "veille": [propre(model_to_dict(p)) for p in ProfilVeille.objects.all()],
        "pieces_types": PieceAdministrative._meta.get_field("type").choices,
        "pieces_attendues": documents.PIECES_ATTENDUES,
        "widgets": [{"cle": w.cle, "titre": w.titre, "description": w.description, "large": w.large} for w in accueil.CATALOGUE],
        "collectes": [propre(model_to_dict(c)) for c in Collecte.objects.all()],
        "avis": avis,
        "analyses": analyses,
        "memoires": memoires,
        "prompts": {
            "profil": scoring.profil_entreprise(), "regles": scoring.REGLES, "analyse": dce.CONSIGNES_ANALYSE,
            "memoire": memoire.CONSIGNES_MEMOIRE, "biblio": memoire.bibliotheque(), "plan_defaut": memoire.PLAN_PAR_DEFAUT,
        },
        "nb_blocs": BlocContenu.objects.filter(actif=True).count(),
    }
    with open(sortie, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"{len(avis)} avis, {len(analyses)} analyse(s), {len(memoires)} mémoire(s) exportés vers {sortie}")


if __name__ == "__main__":
    main()
