# Installation interne (Mac ou PC Linux du bureau)

Pour utiliser l'outil AO et la Prospection au quotidien **sans serveur loué** : l'outil tourne sur un ordinateur du bureau, et l'équipe y accède par le réseau local. Compter 15 minutes.

Plus tard, le passage sur un serveur en ligne se fera avec [deploy/INSTALLATION.md](../INSTALLATION.md), en reprenant la même base de données.

## 1. Prérequis (une seule fois)

Sur Mac, ouvrez l'application **Terminal**.

1. **Homebrew** (gestionnaire de logiciels), s'il n'est pas déjà installé. Suivez la commande indiquée sur https://brew.sh.
2. **Python 3.12 et Git** :

```bash
brew install python@3.12 git
```

Sur Linux (Debian, Ubuntu) :

```bash
sudo apt install python3 python3-venv git
```

## 2. Récupérer le code

**Sur Mac, n'installez pas l'outil dans Documents, Bureau, Téléchargements ou iCloud** : macOS interdit au démarrage automatique d'y accéder (« Operation not permitted »). Utilisez par exemple `~/outil-ao`. Si l'application de votre autre environnement occupe déjà le port 8000, ajoutez `PORT=8010` devant la commande d'installation.

Clonez le dépôt. Le dépôt est privé : connectez-vous d'abord à GitHub (GitHub Desktop, ou `gh auth login`).

```bash
git clone https://github.com/forma-st/FORM-AO.git ~/outil-ao && cd ~/outil-ao
```

Tant que la version de test n'est pas fusionnée dans `main`, prenez sa branche :

```bash
git fetch origin claude/focused-hamilton-9ee51e && git checkout claude/focused-hamilton-9ee51e
```

## 3. Installer

```bash
bash deploy/interne/installer.sh --demarrage-auto
```

Le script installe les dépendances, crée le fichier `.env`, prépare la base, charge le profil FORMA'ST et le catalogue, puis vous demande un **identifiant et un mot de passe administrateur**.

Avec `--demarrage-auto`, l'outil démarre aussitôt et redémarre seul à chaque ouverture de session. Les traitements du matin sont planifiés à 7 h 10 : veille AO, prospection, sauvegarde.

Option `--demo` : ajoute des prospects **fictifs** pour faire le tour de l'outil. Vous les retirerez avant d'importer vos vrais fichiers :

```bash
.venv/bin/python manage.py charger_demo_prospection --effacer
```

Sur Mac, autorisez Python à accepter les connexions entrantes si le pare-feu vous le demande. C'est ce qui permet à l'équipe d'y accéder.

## 4. Utiliser

- Sur l'ordinateur qui héberge l'outil : http://localhost:8000/prospection/
- Depuis un autre poste du bureau : l'adresse affichée à la fin de l'installation, par exemple `http://192.168.1.20:8000/prospection/`.

Chaque personne a son propre compte. Pour en créer, allez dans *Paramètres → Utilisateurs → Ajouter*.

## 5. Réglages à faire ensuite (dans `.env`, puis redémarrer)

| Réglage | Pourquoi |
|---|---|
| `ANTHROPIC_API_KEY=sk-ant-…` | Score IA des appels d'offres, analyse des DCE, bouton « Améliorer avec l'IA ». Sans clé, tout le reste fonctionne |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_HOST_USER`… | Envoi des alertes et du digest de la veille. Par défaut, les e-mails s'écrivent dans `logs/` au lieu de partir |
| `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | Option LinkedIn. Activez-la aussi dans *Paramètres → Prospection* |

Pour **LinkedIn**, déclarez dans l'application LinkedIn l'URL de redirection `http://localhost:8000/prospection/linkedin/retour/`, puis connectez votre compte **depuis l'ordinateur qui héberge l'outil**. LinkedIn n'accepte en général l'adresse `http` que pour `localhost` : ce point est à confirmer lors de votre premier essai.

Pour redémarrer l'outil après une modification du `.env` sur Mac :

```bash
launchctl kickstart -k gui/$(id -u)/fr.formast.outil-ao
```

## 6. Au quotidien

| Besoin | Commande |
|---|---|
| Mettre à jour vers la dernière version | `bash deploy/interne/mettre_a_jour.sh` (sauvegarde d'abord, puis redémarre) |
| Sauvegarder maintenant | `bash deploy/interne/sauvegarder.sh` → dossier `sauvegardes/` (30 jours) |
| Démarrer à la main (sans démarrage automatique) | `bash deploy/interne/demarrer.sh` |
| Voir les journaux | `logs/serveur.log`, `logs/matin.log` |

**Copiez régulièrement le dossier `sauvegardes/`** sur un disque externe ou un partage réseau : c'est votre seule copie des données.

## Limites de l'installation interne

- L'outil n'est joignable que lorsque l'ordinateur est **allumé et réveillé**. Sur Mac, dans *Réglages → Économiseur d'énergie*, empêchez la mise en veille automatique.
- L'accès se fait en `http` sur le réseau du bureau : ne l'ouvrez pas sur Internet. Pour un accès hors du bureau, passez au serveur en ligne (HTTPS).
- La base SQLite convient pour quelques utilisateurs.
