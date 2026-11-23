#!/usr/bin/env bash
# Installation interne de l'outil AO + Prospection sur un Mac ou un PC Linux du bureau.
# À lancer depuis le dossier du dépôt :  bash deploy/interne/installer.sh [--demo] [--demarrage-auto]
#   --demo            charge des prospects fictifs pour découvrir l'outil (retirables ensuite)
#   --demarrage-auto  démarre l'outil à l'ouverture de session et lance les traitements chaque matin
# Variables facultatives pour une installation sans questions :
#   DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL, DJANGO_SUPERUSER_PASSWORD, PORT (8000 par défaut)
set -euo pipefail
cd "$(dirname "$0")/../.."
RACINE="$(pwd)"
if [ ! -f manage.py ] || [ ! -f requirements.txt ] || [ ! -d prospection ]; then
  echo "Ce script doit rester dans le dossier deploy/interne/ d'une copie complète du dépôt FORM-AO."
  echo "Dossier actuel : $RACINE (manage.py, requirements.txt ou prospection/ introuvable)."
  echo "Récupérez le dépôt avec git (voir deploy/interne/INSTALLATION_INTERNE.md), pas en copiant des fichiers avec le Finder."
  exit 1
fi
PORT="${PORT:-8000}"
DEMO=0; AUTO=0
for a in "$@"; do
  case "$a" in
    --demo) DEMO=1 ;;
    --demarrage-auto) AUTO=1 ;;
    *) echo "Option inconnue : $a"; exit 1 ;;
  esac
done

if [ "$AUTO" = "1" ] && [ "$(uname)" = "Darwin" ]; then
  case "$RACINE" in
    "$HOME/Documents"*|"$HOME/Desktop"*|"$HOME/Downloads"*|"$HOME/Library/Mobile Documents"*)
      echo "macOS interdit au démarrage automatique de lire les dossiers Documents, Bureau, Téléchargements et iCloud."
      echo "Déplacez l'outil, par exemple :  mv \"$RACINE\" ~/outil-ao && cd ~/outil-ao && rm -rf .venv"
      echo "puis relancez :  bash deploy/interne/installer.sh $*"
      echo "(Sans --demarrage-auto, l'installation fonctionne ici : vous démarrerez l'outil à la main.)"
      exit 1 ;;
  esac
fi

echo "==> Python"
PY=""
for p in python3.13 python3.12 python3; do
  if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'; then PY="$p"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.12 ou plus récent est nécessaire."
  echo "  Mac : installez Homebrew (https://brew.sh) puis :  brew install python@3.12"
  echo "  Linux (Debian, Ubuntu) :  sudo apt install python3 python3-venv"
  exit 1
fi
echo "    $($PY --version)"

echo "==> Environnement Python et dépendances"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> Fichier de configuration .env"
NOUVEAU_ENV=0
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
  else
    # Fichier modèle absent (copie par le Finder, qui ignore les fichiers commençant par un point) : modèle intégré
    cat > .env <<'MODELE'
DJANGO_SECRET_KEY=
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=localhost
BASE_URL=http://localhost:8000

# IA (console.anthropic.com > API Keys). Sans clé, le score se fait par règles.
ANTHROPIC_API_KEY=
CLAUDE_MODEL=claude-opus-5-5
CLAUDE_EFFORT=medium

# Envoi des e-mails (digest et alertes)
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=1
DEFAULT_FROM_EMAIL=veille-ao@localhost

# Prospection : option LinkedIn (à activer aussi dans Paramètres > Prospection)
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
MODELE
  fi
  NOUVEAU_ENV=1
fi
IP_LOCALE="$(.venv/bin/python - <<'PYEOF'
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); print(s.getsockname()[0])
except Exception:
    print("")
PYEOF
)"
NOM_MACHINE="$(hostname 2>/dev/null || echo localhost)"
.venv/bin/python - "$NOUVEAU_ENV" "$PORT" "$IP_LOCALE" "$NOM_MACHINE" <<'PYEOF'
import re, secrets, sys
nouveau, port, ip, nom = sys.argv[1] == "1", sys.argv[2], sys.argv[3], sys.argv[4]
lignes = open(".env", encoding="utf-8").read().splitlines()
def regler(cle, valeur, seulement_si_vide=False):
    global lignes
    for i, l in enumerate(lignes):
        if l.startswith(cle + "="):
            if seulement_si_vide and l.split("=", 1)[1].strip() and "changer-moi" not in l:
                return
            lignes[i] = f"{cle}={valeur}"
            return
    lignes.append(f"{cle}={valeur}")
hotes = ",".join(h for h in ["localhost", "127.0.0.1", nom, nom if nom.endswith(".local") else nom + ".local", ip] if h)
regler("DJANGO_SECRET_KEY", secrets.token_urlsafe(50), seulement_si_vide=True)
if nouveau:
    regler("DJANGO_DEBUG", "0")
    regler("DJANGO_HTTPS", "0")
    regler("DJANGO_ALLOWED_HOSTS", hotes)
    regler("BASE_URL", f"http://localhost:{port}")
    regler("DJANGO_CSRF_TRUSTED_ORIGINS", ",".join(f"http://{h}:{port}" for h in hotes.split(",")))
    # Sans serveur d'e-mail renseigné, les e-mails s'affichent dans le journal au lieu d'être envoyés
    regler("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
open(".env", "w", encoding="utf-8").write("\n".join(lignes) + "\n")
PYEOF
chmod 600 .env
if [ "$NOUVEAU_ENV" = "1" ]; then
  echo "    .env créé. Ajoutez votre clé ANTHROPIC_API_KEY (IA) quand vous l'aurez : l'outil fonctionne sans."
fi

echo "==> Base de données"
mkdir -p logs sauvegardes media
BASE_NEUVE=0; [ -f db.sqlite3 ] || BASE_NEUVE=1
.venv/bin/python manage.py migrate --noinput -v0
.venv/bin/python manage.py collectstatic --noinput -v0
if [ "$BASE_NEUVE" = "1" ] && [ -f data/seed_formast.json ]; then
  .venv/bin/python manage.py charger_profil >/dev/null && echo "    Profil FORMA'ST, catalogue et veille chargés."
fi

echo "==> Compte administrateur"
if .venv/bin/python manage.py shell --no-imports -c "from django.contrib.auth.models import User; import sys; sys.exit(0 if User.objects.filter(is_superuser=True).exists() else 1)"; then
  echo "    Un administrateur existe déjà."
elif [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
  .venv/bin/python manage.py createsuperuser --noinput --username "$DJANGO_SUPERUSER_USERNAME" --email "${DJANGO_SUPERUSER_EMAIL:-admin@localhost}"
else
  echo "    Choisissez votre identifiant et un mot de passe solide :"
  .venv/bin/python manage.py createsuperuser
fi

if [ "$DEMO" = "1" ]; then
  .venv/bin/python manage.py charger_demo_prospection
fi

chmod +x deploy/interne/*.sh

if [ "$AUTO" = "1" ]; then
  echo "==> Démarrage automatique et traitements du matin"
  if [ "$(uname)" = "Darwin" ]; then
    AGENTS="$HOME/Library/LaunchAgents"; mkdir -p "$AGENTS"
    cat > "$AGENTS/fr.formast.outil-ao.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>fr.formast.outil-ao</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$RACINE/deploy/interne/demarrer.sh</string></array>
  <key>EnvironmentVariables</key><dict><key>PORT</key><string>$PORT</string></dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$RACINE/logs/serveur.log</string><key>StandardErrorPath</key><string>$RACINE/logs/serveur.log</string>
</dict></plist>
PLIST
    cat > "$AGENTS/fr.formast.outil-ao.matin.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>fr.formast.outil-ao.matin</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$RACINE/deploy/interne/traitements_du_matin.sh</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>10</integer></dict>
  <key>StandardOutPath</key><string>$RACINE/logs/matin.log</string><key>StandardErrorPath</key><string>$RACINE/logs/matin.log</string>
</dict></plist>
PLIST
    for f in fr.formast.outil-ao fr.formast.outil-ao.matin; do
      launchctl bootout "gui/$(id -u)/$f" 2>/dev/null || true
      launchctl bootstrap "gui/$(id -u)" "$AGENTS/$f.plist"
    done
    echo "    Lancé maintenant, et à chaque ouverture de session. Traitements chaque matin à 7 h 10 (Mac allumé)."
  else
    ( crontab -l 2>/dev/null | grep -v "deploy/interne/" ; \
      echo "@reboot PORT=$PORT /bin/bash $RACINE/deploy/interne/demarrer.sh >> $RACINE/logs/serveur.log 2>&1"; \
      echo "10 7 * * * /bin/bash $RACINE/deploy/interne/traitements_du_matin.sh >> $RACINE/logs/matin.log 2>&1" ) | crontab -
    nohup env PORT="$PORT" bash deploy/interne/demarrer.sh >> logs/serveur.log 2>&1 &
    echo "    Lancé maintenant, et à chaque redémarrage. Traitements chaque matin à 7 h 10."
  fi
fi

echo
echo "Installation terminée."
echo "  Sur cet ordinateur :           http://localhost:$PORT/prospection/"
[ -n "$IP_LOCALE" ] && echo "  Depuis le réseau du bureau :   http://$IP_LOCALE:$PORT/prospection/"
[ "$AUTO" = "1" ] || echo "  Pour démarrer l'outil :        bash deploy/interne/demarrer.sh"
