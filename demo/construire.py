"""Assemble demo/index.html : demo/source.html + la feuille de style de l'application.

Les polices (Barlow, Atkinson Hyperlegible) sont intégrées en data: URI, car une page
artifact ne peut charger des polices que depuis Google Fonts ou en ligne.

    python demo/construire.py
"""
import base64
import os
import re

DEMO = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(os.path.dirname(DEMO), "veille", "static", "veille")


def css_application() -> str:
    with open(os.path.join(STATIC, "app.css"), encoding="utf-8") as f:
        css = f.read()

    def police(m):
        with open(os.path.join(STATIC, m.group(1)), "rb") as f:
            return 'url("data:font/woff2;base64,' + base64.b64encode(f.read()).decode() + '")'

    return re.sub(r'url\("(fonts/[^"]+\.woff2)"\)', police, css)


def main():
    with open(os.path.join(DEMO, "source.html"), encoding="utf-8") as f:
        page = f.read()
    page = page.replace("/*APP_CSS*/", css_application(), 1)
    with open(os.path.join(DEMO, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    print(f"demo/index.html : {len(page) // 1024} Ko")


if __name__ == "__main__":
    main()
