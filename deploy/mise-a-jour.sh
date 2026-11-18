#!/usr/bin/env bash
# Met à jour l'application après une modification du code (en root).
set -euo pipefail
cd /opt/veille-ao
sudo -u veilleao git pull --ff-only
sudo -u veilleao .venv/bin/pip install -q -r requirements.txt
sudo -u veilleao .venv/bin/python manage.py migrate --noinput
sudo -u veilleao .venv/bin/python manage.py collectstatic --noinput -v0
systemctl restart veille-ao
echo "Application mise à jour."
