"""Petits utilitaires python-docx : styles, tableaux, champs à compléter, Markdown simple."""

from __future__ import annotations

import io
import re

from docx import Document
from docx.enum.text import WD_COLOR_INDEX, WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

A_COMPLETER = "[À COMPLÉTER]"
ROUGE = RGBColor(0xB3, 0x26, 0x1E)
_MARQUE = re.compile(r"(\[À COMPLÉTER[^\]]*\])")


def nouveau_document() -> Document:
    doc = Document()
    for section in doc.sections:
        section.left_margin = section.right_margin = Cm(2)
        section.top_margin = section.bottom_margin = Cm(1.8)
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10.5)
    return doc


def ajouter_texte(paragraphe, texte: str, gras: bool = False):
    """Ajoute du texte en surlignant en jaune les marques [À COMPLÉTER …] et en
    interprétant le **gras** Markdown."""
    for morceau in _MARQUE.split(texte):
        if not morceau:
            continue
        if _MARQUE.fullmatch(morceau):
            run = paragraphe.add_run(morceau)
            run.bold = True
            run.font.highlight_color = WD_COLOR_INDEX.YELLOW
            continue
        for i, sous in enumerate(re.split(r"\*\*", morceau)):
            if sous:
                run = paragraphe.add_run(sous)
                run.bold = gras or (i % 2 == 1)
    return paragraphe


def titre(doc, texte: str, niveau: int = 1):
    h = doc.add_heading(level=niveau)
    run = h.add_run(texte)
    run.font.color.rgb = ROUGE if niveau <= 1 else RGBColor(0x1F, 0x23, 0x28)
    return h


def para(doc, texte: str = "", gras: bool = False, italique: bool = False, taille: int | None = None):
    p = doc.add_paragraph()
    ajouter_texte(p, texte, gras=gras)
    if italique or taille:
        for r in p.runs:
            r.italic = italique or r.italic
            if taille:
                r.font.size = Pt(taille)
    return p


def case(coche: bool) -> str:
    return "☒" if coche else "☐"


def _ombrer(cellule, couleur="F2F0EC"):
    tc_pr = cellule._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), couleur)
    tc_pr.append(shd)


def tableau_cles(doc, lignes: list[tuple[str, str]]):
    """Tableau à deux colonnes libellé / valeur. Une valeur vide devient [À COMPLÉTER]."""
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    for libelle, valeur in lignes:
        c1, c2 = t.add_row().cells
        c1.width, c2.width = Cm(6), Cm(11)
        ajouter_texte(c1.paragraphs[0], libelle, gras=True)
        _ombrer(c1)
        ajouter_texte(c2.paragraphs[0], valeur if str(valeur).strip() else A_COMPLETER)
    doc.add_paragraph()
    return t


def tableau(doc, entetes: list[str], lignes: list[list[str]]):
    t = doc.add_table(rows=1, cols=len(entetes))
    t.style = "Table Grid"
    for c, e in zip(t.rows[0].cells, entetes):
        ajouter_texte(c.paragraphs[0], e, gras=True)
        _ombrer(c)
    for ligne in lignes:
        cells = t.add_row().cells
        for c, v in zip(cells, ligne):
            ajouter_texte(c.paragraphs[0], str(v) if v not in (None, "") else "—")
    doc.add_paragraph()
    return t


def pied(doc, texte: str):
    for section in doc.sections:
        p = section.footer.paragraphs[0]
        p.text = texte
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for r in p.runs:
            r.font.size = Pt(8)
            r.font.color.rgb = RGBColor(0x62, 0x6A, 0x73)


def en_octets(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def markdown_vers_docx(doc, markdown: str):
    """Convertit un Markdown simple (titres, listes, tableaux, gras) en paragraphes Word."""
    lignes = markdown.splitlines()
    i = 0
    while i < len(lignes):
        ligne = lignes[i].rstrip()
        if not ligne.strip():
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", ligne)
        if m:
            titre(doc, m.group(2).strip(), niveau=len(m.group(1)))
            i += 1
            continue
        if ligne.lstrip().startswith("|"):
            bloc = []
            while i < len(lignes) and lignes[i].lstrip().startswith("|"):
                bloc.append(lignes[i])
                i += 1
            rangees = [
                [c.strip() for c in r.strip().strip("|").split("|")]
                for r in bloc
                if not re.fullmatch(r"\|?\s*:?-{2,}.*", r.strip())
            ]
            if rangees:
                n = max(len(r) for r in rangees)
                rangees = [r + [""] * (n - len(r)) for r in rangees]
                tableau(doc, rangees[0], rangees[1:])
            continue
        m = re.match(r"^(\s*)[-*•]\s+(.*)", ligne)
        if m:
            style = "List Bullet 2" if len(m.group(1)) >= 2 else "List Bullet"
            ajouter_texte(doc.add_paragraph(style=style), m.group(2))
            i += 1
            continue
        m = re.match(r"^\s*\d+[.)]\s+(.*)", ligne)
        if m:
            ajouter_texte(doc.add_paragraph(style="List Number"), m.group(1))
            i += 1
            continue
        para(doc, ligne.strip())
        i += 1
