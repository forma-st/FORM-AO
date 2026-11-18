# Veille AO – outil interne FORMA'ST

Veille des appels d'offres publics et privés, score Go/No-Go par IA et suivi des réponses.
Le cahier des charges complet est dans [SPEC.md](SPEC.md).

## Ce qui marche aujourd'hui

### Phase 1 – veille

- **Collecte automatique** : BOAMP (tous les avis, environ 300 à 500 par jour) et TED (acheteurs français, codes CPV formation et prévention), avec dédoublonnage entre les deux.
- **Filtre par règles**, gratuit et paramétrable dans l'admin (*Paramètres → Profils de veille*) :
  - **Mots-clés forts** : suffisent seuls (ex. « sauveteur secouriste », « guide file »).
  - **Mots-clés génériques** : comptent seulement avec un **mot de contexte** (ex. « incendie » + « formation »). Cela évite les marchés de maintenance ou de travaux.
  - **Exclusions** dans l'objet de l'avis (maintenance, gardiennage, maîtrise d'œuvre…), codes CPV, départements, montants.
  - Marchés de travaux et de fournitures, avis d'attribution, rectificatifs et dates limites dépassées sont écartés. Les attributions sont conservées pour l'analyse de la concurrence.
- **Score Go/No-Go par IA** (Claude) sur les seuls avis retenus. L'IA connaît le catalogue, les prix, les formateurs, les références et les habilitations. Elle rend un score sur 100, une recommandation, le besoin résumé, les critères (favorable, défavorable, éliminatoire), les prestations concernées, les lots à viser, les exigences bloquantes et les questions à vérifier dans le DCE.
  Sans clé API, un **score par règles** prend le relais (plafonné à 70, toujours « À étudier »).
- **Interface web** : tableau des AO triés par score, fiche détaillée avec suivi (statut, responsable, motif de décision), pipeline Kanban, saisie des consultations privées.
- **E-mails** : alerte immédiate au-dessus de 80/100 et digest quotidien au-dessus de 50/100. Le digest rappelle aussi les dates limites proches et les pièces administratives à renouveler.
- **Profil FORMA'ST pré-chargé (identité légale : annuaire officiel des entreprises)** depuis les documents Picard : catalogue et prix 2026, 2 formateurs, référence Picard, profil de veille, et la consultation Picard « Gestes et postures », à rendre le 11/12.

### Phase 2 – dossier administratif

- **Coffre-fort** (menu *Coffre-fort*) : Kbis, attestation URSSAF, attestation fiscale, RC Pro, Qualiopi, INRS, déclaration d'activité, RIB, avec leur date d'expiration. Une alerte part dans le digest 30 jours avant l'échéance. Ces fichiers ne sont accessibles qu'aux utilisateurs connectés.
- **Pièces générées** depuis le profil, sur la page *Préparer la réponse* de chaque avis :
  - **DC1** (lettre de candidature) et **DC2** (déclaration du candidat), qui reprennent la structure des modèles de la DAJ ;
  - la **déclaration sur l'honneur** ;
  - la **présentation de FORMA'ST** (offre, intervenants, références, sans les prix) ;
  - une **aide à la saisie du DUME**.

  Les informations manquantes sont surlignées en jaune « [À COMPLÉTER] ».
- **Dossier complet en ZIP** : les pièces générées, les pièces du coffre-fort **valides à la date limite**, le dernier mémoire et une check-list (pièce OK, expirée ou manquante).
- Pour une **consultation privée**, pas de DC1, DC2 ni DUME : seulement la présentation, les pièces et le mémoire.

### Phase 3 – analyse du DCE et mémoire technique

- **Dépôt du DCE** : ZIP de la plateforme acheteur, PDF, Word, Excel. Le type de chaque document est reconnu (RC, CCTP, CCAP, AE, BPU). Les PDF sont lus directement par l'IA, avec les numéros de page.
- **Analyse IA** (1 à 3 min, en arrière-plan) :
  - synthèse du besoin, lots pertinents, volumes, forme du prix, dates ;
  - **critères de jugement et pondérations** ;
  - **toutes les pièces à fournir**, rapprochées du coffre-fort et des documents générés ;
  - **exigences** (remplie, non remplie, à vérifier) avec leur source ;
  - pièges, questions à poser à l'acheteur, postes à chiffrer ;
  - **plan du mémoire** calqué sur les critères ;
  - score et recommandation.
- **Grille de conformité** (Excel) : critères et sections du mémoire, exigences, pièces.
- **Brouillon de mémoire technique** (3 à 8 min, en arrière-plan) :
  - il suit le plan de l'analyse et s'appuie sur le profil, la **bibliothèque de contenus** (*Paramètres → Bibliothèque de contenus*, pré-remplie depuis la proposition et la convention Picard) et le DCE ;
  - rien n'est inventé : tout manque est signalé « [À COMPLÉTER : …] » ;
  - export **Word** avec page de garde.
- Commandes équivalentes : `manage.py analyser_dce <id>` et `manage.py rediger_memoire <id> --consignes "…"`.

Pas encore fait : le remplissage automatique des BPU et DPGF Excel de l'acheteur. L'analyse liste les postes à chiffrer, mais les prix sont à saisir à la main.

## Installation (serveur Linux ou poste de travail)

Il faut Python 3.12 ou plus récent.

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Éditez ensuite `.env` : la clé API Anthropic et le serveur SMTP.

```bash
.venv/bin/python manage.py migrate
```

```bash
.venv/bin/python manage.py charger_profil
```

```bash
.venv/bin/python manage.py createsuperuser
```

Le fichier `data/seed_formast.json` contient des données internes (prix, CV, bibliothèque de contenus). Il est versionné parce que le dépôt est **privé** : ne rendez jamais ce dépôt public.

À faire ensuite dans l'application :
1. **Profil** (menu *Profil*) : compléter e-mail, téléphone, chiffre d'affaires, capital et dates d'expiration. Le bouton « Mettre à jour depuis l'annuaire officiel » rafraîchit l'identité légale (adresse, dirigeant, NAF, TVA, déclaration d'activité). Les documents se régénèrent à chaque téléchargement, donc toute information ajoutée apparaît aussitôt.
2. **Profils de veille** : renseigner les **destinataires** des e-mails (sinon aucun digest n'est envoyé).
3. **Coffre-fort** : déposer Kbis, attestation URSSAF, attestation fiscale, RC Pro et Qualiopi, avec leurs dates d'expiration. Ce n'est pas bloquant : sans pièces, le dossier se génère et la check-list les signale manquantes. Chaque pièce manquante a un lien « ajouter » sur la page de réponse.

## Clé API Anthropic

L'application lit la clé dans la variable `ANTHROPIC_API_KEY`. Elle peut venir du fichier `.env` ou de l'environnement du serveur.
- **Serveur de production** : dans `.env`, ajouter la ligne `ANTHROPIC_API_KEY=sk-ant-…`, puis redémarrer l'application.
- **Session cloud Claude Code** (pour les tests) : ajouter une variable d'environnement `VEILLE_ANTHROPIC_API_KEY` dans les réglages de l'environnement (la session ne transmet pas `ANTHROPIC_API_KEY` aux commandes). Elle est lisible par toute personne et toute commande qui utilise cet environnement.

Sans clé, l'outil fonctionne quand même : le score se fait par règles, mais l'analyse du DCE et le mémoire restent indisponibles.

## Utilisation

```bash
.venv/bin/python manage.py runserver
```

Puis ouvrir http://localhost:8000.

Commandes utiles :

| Commande | Rôle |
|---|---|
| `manage.py veille_quotidienne` | Collecte, puis score, puis e-mails (à planifier chaque matin) |
| `manage.py collecter --depuis 2026-11-01` | Collecte manuelle d'une période |
| `manage.py scorer` | Score des avis retenus non encore notés (`--rescorer` pour tout refaire, `--regles` sans IA) |
| `manage.py envoyer_digest` | Envoi des alertes et du digest |
| `manage.py charger_profil` | Recharge le profil, le catalogue et la veille depuis le JSON |
| `manage.py test veille` | Tests automatiques |

Planification (cron) chaque jour à 7 h 10 :

```
10 7 * * * cd /chemin/veille-ao && .venv/bin/python manage.py veille_quotidienne >> veille.log 2>&1
```

## Mise en production

Guide pas à pas pour un serveur loué (VPS) : [deploy/INSTALLATION.md](deploy/INSTALLATION.md). Le script `deploy/install.sh` installe tout (application, HTTPS, veille chaque matin, sauvegardes).


- Servir l'application avec un seul processus multi-thread, par exemple `gunicorn config.wsgi --workers 1 --threads 4 --timeout 120`, derrière nginx et en HTTPS. Les analyses et les mémoires tournent dans des threads de ce processus.
- **Ne pas** faire servir `/media/` directement par nginx : les pièces (Kbis, RIB, CV) passent par l'application, qui vérifie la connexion.
- Sauvegarder chaque jour `db.sqlite3` et le dossier `media/`.

## Coûts

- **IA** : environ 60 à 80 avis par mois passent le filtre. Chaque score coûte quelques centimes (Claude Opus 5.5, profil mis en cache). Comptez **moins de 10 € par mois** pour la veille. L'analyse d'un DCE coûte environ 0,50 à 1 € et un brouillon de mémoire 1 à 3 €.
- **Hébergement** : un petit VPS en France suffit (environ 5 à 20 €/mois). La base SQLite convient pour un usage interne, et le passage à PostgreSQL est prévu si besoin.

## Architecture

```
config/                  réglages Django
veille/models.py         Entreprise, Prestation, Formateur, Reference, PieceAdministrative,
                         ProfilVeille, AvisMarche, Collecte
veille/services/
  boamp.py               API open data DILA (Opendatasoft) : formats eForms, FNSimple, MAPA
  ted.py                 API de recherche TED v3
  collecte.py            orchestration, dédoublonnage, reprise automatique
  prefiltre.py           règles (mots-clés forts, génériques + contexte, exclusions, CPV)
  scoring.py             score IA (sortie structurée) et score par règles
  digest.py              e-mails
  documents.py           DC1, DC2, déclaration sur l'honneur, présentation, aide DUME, dossier ZIP
  dce.py                 dépôt et extraction du DCE, analyse IA, rapprochement des pièces
  memoire.py             brouillon de mémoire (IA), export Word, grille de conformité
  docx_utils.py          mise en forme Word, Markdown vers Word
  taches.py              traitements longs en arrière-plan
veille/management/commands/   commandes ci-dessus
```
