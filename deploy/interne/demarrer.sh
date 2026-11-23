#!/usr/bin/env bash
# Démarre l'outil (gunicorn) sur le port 8000, accessible depuis le réseau local. Ctrl+C pour arrêter.
set -euo pipefail
cd "$(dirname "$0")/../.."
PORT="${PORT:-8000}"
echo "Outil AO + Prospection : http://localhost:$PORT/prospection/  (Ctrl+C pour arrêter)"
exec .venv/bin/gunicorn config.wsgi --bind "0.0.0.0:$PORT" --workers 1 --threads 4 --timeout 120
