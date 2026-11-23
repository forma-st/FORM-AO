#!/usr/bin/env bash
# Sauvegarde quotidienne de FORM'AO : base de données + fichiers déposés, gardée 30 jours.
set -euo pipefail
DEST="${1:-$HOME/Documents/FORMAO-sauvegardes}"
cd "$(dirname "$0")/../.."
mkdir -p "$DEST"
JOUR="$(date +%F)"
# Copie cohérente de la base, même si l'application tourne (API de sauvegarde de SQLite)
.venv/bin/python - "$DEST/formao-$JOUR.sqlite3" <<'PY'
import sqlite3, sys
src = sqlite3.connect("db.sqlite3"); dst = sqlite3.connect(sys.argv[1])
with dst:
    src.backup(dst)
dst.close(); src.close()
PY
[ -d media ] && tar czf "$DEST/fichiers-$JOUR.tgz" media
find "$DEST" -type f -mtime +30 -delete
echo "$(date '+%F %T') sauvegarde OK dans $DEST"
