#!/usr/bin/env bash
# Veille AO (collecte, score, e-mails), puis prospection (reprises, relances, annuaire, scores), puis sauvegarde.
set -uo pipefail
cd "$(dirname "$0")/../.."
echo "=== $(date '+%d/%m/%Y %H:%M') ==="
.venv/bin/python manage.py veille_quotidienne || echo "Veille AO : erreur (voir ci-dessus)"
.venv/bin/python manage.py prospection_quotidienne --sirene || echo "Prospection : erreur (voir ci-dessus)"
bash deploy/interne/sauvegarder.sh
