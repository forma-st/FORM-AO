"""Exporte les avis notés, le profil et les documents générés vers demo/data.json (données de la démo)."""
import os, sys, json, base64, io, html, datetime, decimal
RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django; django.setup()
from django.forms.models import model_to_dict
from docx import Document
from veille.models import *
from veille.services import scoring, documents, dce, memoire
def clean(d):
    out = {}
    for k, v in d.items():
        if isinstance(v, (datetime.date, datetime.datetime)): v = v.isoformat()
        elif isinstance(v, decimal.Decimal): v = float(v)
        elif hasattr(v, "name") and hasattr(v, "url"): v = v.name or ""
        out[k] = v
    return out
def docx_html(data):
    doc = Document(io.BytesIO(data)); parts = []
    body = doc.element.body
    from docx.table import Table; from docx.text.paragraph import Paragraph
    for child in body.iterchildren():
        tag = child.tag.split("}")[1]
        if tag == "p":
            p = Paragraph(child, doc); t = html.escape(p.text)
            if not t.strip(): continue
            t = t.replace("[À COMPLÉTER", "<mark>[À COMPLÉTER").replace("]", "]</mark>") if "[À COMPLÉTER" in t else t
            st = (p.style.name or "").lower()
            if "title" in st or "heading 1" in st: parts.append(f"<h3>{t}</h3>")
            elif "heading" in st: parts.append(f"<h4>{t}</h4>")
            else: parts.append(f"<p>{t}</p>")
        elif tag == "tbl":
            tb = Table(child, doc); rows = []
            for r in tb.rows:
                cells = []; prev = None
                for c in r.cells:
                    if c._tc is prev: continue
                    prev = c._tc; cells.append("<td>" + html.escape(c.text).replace("\n", "<br>") + "</td>")
                rows.append("<tr>" + "".join(cells) + "</tr>")
            parts.append("<table>" + "".join(rows) + "</table>")
    return "\n".join(parts)
e = Entreprise.get()
avis = []
for a in AvisMarche.objects.filter(score__isnull=False).order_by("-score"):
    d = clean(model_to_dict(a, exclude=["brut", "profil"]))
    d["id"] = a.pk
    docs = {}
    for cle in documents.generateurs_pour(a):
        nom, fn = documents.GENERATEURS[cle]
        try:
            data = fn(a)
            docs[cle] = {"nom": nom, "html": docx_html(data), "b64": base64.b64encode(data).decode()}
        except Exception as ex:
            docs[cle] = {"nom": nom, "erreur": str(ex)}
    d["documents"] = docs
    avis.append(d)
data = {
    "entreprise": clean(model_to_dict(e)),
    "prestations": [clean(model_to_dict(p)) for p in Prestation.objects.all()],
    "formateurs": [clean(model_to_dict(p, exclude=["cv"])) for p in Formateur.objects.all()],
    "references": [clean(model_to_dict(p, exclude=["document"])) for p in Reference.objects.all()],
    "blocs": [clean(model_to_dict(p)) for p in BlocContenu.objects.all()],
    "veille": [clean(model_to_dict(p)) for p in ProfilVeille.objects.all()],
    "pieces_types": PieceAdministrative._meta.get_field("type").choices,
    "avis": avis,
    "prompts": {"profil": scoring.profil_entreprise(), "regles": scoring.REGLES, "analyse": dce.CONSIGNES_ANALYSE,
                "memoire": memoire.CONSIGNES_MEMOIRE, "biblio": memoire.bibliotheque(), "plan_defaut": memoire.PLAN_PAR_DEFAUT},
    "stats": {"publies": AvisMarche.objects.count(), "retenus": AvisMarche.objects.filter(prefiltre_ok=True).count()},
}
sortie = sys.argv[1] if len(sys.argv) > 1 else os.path.join(RACINE, "demo", "data.json")
json.dump(data, open(sortie, "w"), ensure_ascii=False)
print(f"{len(avis)} avis exportés vers {sortie}")
