# Démo interactive (artifact claude.ai)

Maquette fonctionnelle de l'outil, sans serveur : elle s'ouvre dans le navigateur sur claude.ai.

- `index.html` : l'application de démo (tableau, fiches, pipeline, consultation privée, coffre-fort, profil, préparation de la réponse). Les modifications restent dans le navigateur du visiteur ; un bouton remet la démo à zéro.
- `data.json` : les données affichées (avis notés, profil, catalogue, formateurs, bibliothèque, textes des consignes IA et documents Word DC1/DC2/DUME… pré-générés). **Contient des données internes : ne pas rendre ce dépôt public.**
- `exporter_donnees.py` : régénère `data.json` depuis la base de l'application.

## Mettre à jour les données

```bash
.venv/bin/python manage.py collecter --depuis 2026-11-16
```

```bash
.venv/bin/python manage.py scorer
```

```bash
.venv/bin/python demo/exporter_donnees.py
```

Puis republier la page (avec Claude Code : « republie la démo »), en joignant `data.json` à côté de `index.html` et en déclarant les capacités `sample` (IA) et `downloads` (téléchargements).

## IA dans la démo

La notation d'une consultation privée, l'analyse du DCE et le brouillon de mémoire passent par Claude **sur le compte du visiteur** (il doit l'autoriser au premier usage), pas par la clé API de l'application. Sans IA, la notation se fait par règles (plafonnée à 70) et les deux autres fonctions sont désactivées.
