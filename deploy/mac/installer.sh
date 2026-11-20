#!/usr/bin/env bash
# Installation de FORM'AO sur un Mac utilisé comme serveur.
# À lancer depuis le dossier du projet :  bash deploy/mac/installer.sh
# Le script peut être relancé sans risque : il garde le .env et la base existants.
set -euo pipefail

DOSSIER="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$DOSSIER"
AGENTS="$HOME/Library/LaunchAgents"
JOURNAUX="$HOME/Library/Logs/FORMAO"
SAUVEGARDES="$HOME/Documents/FORMAO-sauvegardes"
PORT=8000

titre() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }

titre "Vérification de Python (3.10 ou plus récent)"
PY=""
for c in python3.13 python3.12 python3.11 python3.10 /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$(command -v "$c")"; break
  fi
done
if [ -z "$PY" ]; then
  if command -v brew >/dev/null 2>&1; then
    echo "Installation de Python 3.12 avec Homebrew…"
    brew install python@3.12
    PY="$(brew --prefix)/bin/python3.12"
  else
    echo "Python 3.10 ou plus récent est nécessaire."
    echo "Installez-le depuis https://www.python.org/downloads/macos/ (paquet « macOS 64-bit universal2 »),"
    echo "puis relancez :  bash deploy/mac/installer.sh"
    exit 1
  fi
fi
echo "Python : $("$PY" --version) ($PY)"

titre "Environnement de l'application"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

titre "Réglages (.env)"
if [ ! -f .env ]; then
  SECRET="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(50))')"
  echo "Clé API Anthropic (commence par sk-ant-). Elle ne s'affiche pas pendant la saisie."
  echo "Laissez vide pour l'ajouter plus tard dans le fichier .env."
  read -r -s -p "Clé API : " CLE; echo
  read -r -p "Adresse e-mail qui recevra le digest (facultatif) : " MAIL_DEST
  cat > .env <<EOF
DJANGO_SECRET_KEY=$SECRET
DJANGO_DEBUG=0
# localhost pour ce Mac, .ts.net pour l'accès à distance par Tailscale
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,.ts.net
DJANGO_CSRF_TRUSTED_ORIGINS=https://*.ts.net
BASE_URL=http://localhost:$PORT
ANTHROPIC_API_KEY=$CLE
CLAUDE_MODEL=claude-opus-5-5
CLAUDE_EFFORT=medium
# E-mails : à compléter pour recevoir le digest (sinon ils s'affichent dans le journal)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=1
DEFAULT_FROM_EMAIL=
EOF
  chmod 600 .env
  echo ".env créé."
else
  echo ".env déjà présent : conservé."
  MAIL_DEST=""
fi

titre "Base de données et profil FORMA'ST"
.venv/bin/python manage.py migrate --noinput -v0
if [ ! -f db.sqlite3.profil_charge ]; then
  .venv/bin/python manage.py charger_profil
  touch db.sqlite3.profil_charge
fi
if [ -f data/reprise.json ] && [ ! -f db.sqlite3.reprise_chargee ]; then
  echo "Reprise des avis, analyses et mémoires de la session de test…"
  .venv/bin/python manage.py loaddata data/reprise.json -v0 && touch db.sqlite3.reprise_chargee
fi
if [ -n "${MAIL_DEST:-}" ]; then
  DEST="$MAIL_DEST" .venv/bin/python manage.py shell -c "import os; from veille.models import ProfilVeille as P; P.objects.update(destinataires=os.environ['DEST'].strip())"
fi
.venv/bin/python manage.py collectstatic --noinput -v0

titre "Compte(s) utilisateur"
if .venv/bin/python manage.py shell -c "from django.contrib.auth.models import User; import sys; sys.exit(0 if User.objects.filter(is_superuser=True).exists() else 1)"; then
  echo "Un compte administrateur existe déjà."
else
  echo "Créez votre compte (identifiant, e-mail, mot de passe) :"
  .venv/bin/python manage.py createsuperuser
fi

titre "Démarrage automatique (application, veille de 7 h 10, sauvegarde de la nuit)"
mkdir -p "$AGENTS" "$JOURNAUX" "$SAUVEGARDES"
for modele in deploy/mac/*.plist; do
  nom="$(basename "$modele")"
  sed -e "s#__DOSSIER__#$DOSSIER#g" -e "s#__JOURNAUX__#$JOURNAUX#g" -e "s#__SAUVEGARDES__#$SAUVEGARDES#g" -e "s#__PORT__#$PORT#g" \
    "$modele" > "$AGENTS/$nom"
  launchctl bootout "gui/$(id -u)/${nom%.plist}" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$nom"
done
sleep 3
if curl -fsS -o /dev/null "http://localhost:$PORT/connexion/"; then
  echo "FORM'AO tourne : http://localhost:$PORT"
  open "http://localhost:$PORT" 2>/dev/null || true
else
  echo "L'application ne répond pas encore. Journal : $JOURNAUX/web.log"
fi

titre "Accès pour votre collègue (Tailscale)"
if command -v tailscale >/dev/null 2>&1 || [ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]; then
  TS="$(command -v tailscale || echo /Applications/Tailscale.app/Contents/MacOS/Tailscale)"
  "$TS" serve --bg "$PORT" && "$TS" serve status || echo "Activez Tailscale (connexion au compte) puis relancez ce script."
else
  echo "Tailscale n'est pas installé : voir deploy/mac/INSTALLATION-MAC.md, étape 4."
fi

cat <<EOF

Terminé.
- Sur ce Mac : http://localhost:$PORT
- Journaux : $JOURNAUX
- Sauvegardes quotidiennes : $SAUVEGARDES
- Pour que la veille tourne chaque matin, le Mac doit rester allumé et branché, sans se mettre en veille.
EOF
