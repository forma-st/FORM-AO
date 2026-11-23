#!/usr/bin/env bash
# Met à jour FORM'AO sur le Mac après une évolution du code (git pull, dépendances, base).
set -euo pipefail
cd "$(dirname "$0")/../.."
git pull --ff-only
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput -v0
launchctl kickstart -k "gui/$(id -u)/com.formast.formao.web"
echo "FORM'AO mis à jour et redémarré : http://localhost:8000"
