# Démo interactive de FORM'AO (artifact claude.ai)

Maquette fonctionnelle de l'outil, sans serveur : elle s'ouvre dans le navigateur sur claude.ai et reprend l'interface de l'application (même feuille de style, mêmes polices, mêmes écrans).

- `source.html` : le code de la démo (accueil à widgets personnalisable, tri Go / No-Go avec annulation et raccourcis clavier, fiche d'avis, parcours de réponse en 4 étapes, mémoire modifiable, réponses en colonnes, coffre-fort, profil, consultation privée). Les modifications restent dans le navigateur du visiteur ; un lien remet la démo à zéro.
- `construire.py` : assemble `index.html` à partir de `source.html` et de `veille/static/veille/app.css` (polices intégrées).
- `index.html` : la page publiée (générée, ne pas modifier à la main).
- `exporter_donnees.py` : régénère `data.json` depuis la base de l'application.
- `data.json` : les données affichées (avis retenus, analyse et mémoire existants, profil, catalogue, consignes IA, documents Word DC1/DC2/DUME… pré-générés pour les avis Go et À étudier). **Contient des données internes : ne pas rendre ce dépôt public.**

## Mettre à jour la démo

Données de la phase de test :

```bash
.venv/bin/python manage.py loaddata data/reprise.json
```

Ou une nouvelle collecte :

```bash
.venv/bin/python manage.py veille_quotidienne
```

Puis :

```bash
.venv/bin/python demo/exporter_donnees.py
```

```bash
python demo/construire.py
```

Enfin, republier `index.html` avec `data.json` à côté (avec Claude Code : « republie la démo »), en déclarant les capacités `sample` (IA) et `downloads` (téléchargements).

## IA dans la démo

Le score d'une consultation, l'analyse du dossier et le brouillon de mémoire passent par Claude **sur le compte du visiteur** (il l'autorise au premier usage), pas par la clé API de l'application. Sans IA, le score se fait par règles (70 au maximum) et l'analyse et le mémoire sont désactivés ; l'analyse et le mémoire déjà produits par l'application (consultation Picard) restent consultables.
