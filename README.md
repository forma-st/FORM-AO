# Veille AO – outil interne FORMA'ST

Veille des appels d'offres publics et privés, score Go/No-Go par IA et suivi des réponses.
Le cahier des charges complet est dans [SPEC.md](SPEC.md).

## Ce qui marche aujourd'hui (phase 1)

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

Le fichier `data/seed_formast.json` contient des données internes (prix, CV) : il n'est volontairement **pas versionné** (voir `.gitignore`). Gardez-en une copie.

À faire ensuite dans *Paramètres* (`/admin`) :
1. **Profils de veille** : renseigner les **destinataires** des e-mails (sinon aucun digest n'est envoyé).
2. **Entreprise** : compléter le code postal, le N° de déclaration d'activité, le CA, l'effectif et les dates d'expiration Qualiopi et INRS.
3. **Pièces administratives** : déposer Kbis, attestation URSSAF, attestation fiscale, RC Pro et Qualiopi, avec leurs dates d'expiration.

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

## Coûts

- **IA** : environ 60 à 80 avis par mois passent le filtre. Chaque score coûte quelques centimes (Claude Opus 5.5, profil mis en cache). Comptez **moins de 10 € par mois**.
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
veille/management/commands/   commandes ci-dessus
```
