#!/usr/bin/env bash
# Arrête FORM'AO et retire le démarrage automatique. Le dossier, la base et les sauvegardes sont conservés.
set -uo pipefail
for n in web veille sauvegarde; do
  launchctl bootout "gui/$(id -u)/com.formast.formao.$n" 2>/dev/null
  rm -f "$HOME/Library/LaunchAgents/com.formast.formao.$n.plist"
done
command -v tailscale >/dev/null 2>&1 && tailscale serve reset 2>/dev/null
echo "FORM'AO est arrêté. Les données restent dans ce dossier et dans ~/Documents/FORMAO-sauvegardes."
