#!/usr/bin/env bash
# Installation de FORM'AO sur un serveur Debian 12 / Ubuntu 24.04 neuf.
# Usage (en root) :  bash install.sh veille.mondomaine.fr
set -euo pipefail

DOMAINE="${1:?Usage : bash install.sh <nom de domaine, ex. veille.forma-st.fr>}"
DEPOT="${DEPOT:-git@github.com:forma-st/FORM-AO.git}"
APP=/opt/veille-ao
UTILISATEUR=veilleao

echo "==> Paquets système"
apt-get update -q
apt-get install -y -q python3 python3-venv git nginx certbot python3-certbot-nginx sqlite3

echo "==> Utilisateur dédié"
id "$UTILISATEUR" >/dev/null 2>&1 || useradd --system --create-home --home-dir /home/$UTILISATEUR --shell /bin/bash $UTILISATEUR

echo "==> Code de l'application"
if [ ! -d "$APP/.git" ]; then
  if [ ! -f /home/$UTILISATEUR/.ssh/id_ed25519 ]; then
    sudo -u $UTILISATEUR mkdir -p /home/$UTILISATEUR/.ssh
    sudo -u $UTILISATEUR ssh-keygen -t ed25519 -N "" -f /home/$UTILISATEUR/.ssh/id_ed25519 -C "veille-ao@$DOMAINE" >/dev/null
  fi
  echo
  echo "Ajoutez cette clé de déploiement (lecture seule) sur GitHub :"
  echo "  dépôt forma-st/FORM-AO > Settings > Deploy keys > Add deploy key"
  echo
  cat /home/$UTILISATEUR/.ssh/id_ed25519.pub
  echo
  read -r -p "Appuyez sur Entrée une fois la clé ajoutée sur GitHub… " _
  sudo -u $UTILISATEUR ssh-keyscan github.com >> /home/$UTILISATEUR/.ssh/known_hosts 2>/dev/null
  mkdir -p "$APP" && chown $UTILISATEUR: "$APP"
  sudo -u $UTILISATEUR git clone "$DEPOT" "$APP"
fi
cd "$APP"

echo "==> Environnement Python"
sudo -u $UTILISATEUR python3 -m venv .venv
sudo -u $UTILISATEUR .venv/bin/pip install -q --upgrade pip
sudo -u $UTILISATEUR .venv/bin/pip install -q -r requirements.txt

echo "==> Fichier .env"
if [ ! -f .env ]; then
  SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
  sudo -u $UTILISATEUR cp .env.example .env
  sed -i "s#^DJANGO_SECRET_KEY=.*#DJANGO_SECRET_KEY=$SECRET#" .env
  sed -i "s#^DJANGO_ALLOWED_HOSTS=.*#DJANGO_ALLOWED_HOSTS=$DOMAINE#" .env
  sed -i "s#^BASE_URL=.*#BASE_URL=https://$DOMAINE#" .env
  chmod 600 .env
  echo
  echo "Complétez maintenant la clé API Anthropic et le serveur d'e-mails :"
  read -r -p "Appuyez sur Entrée pour ouvrir l'éditeur… " _
  nano .env
fi

echo "==> Base de données et données FORMA'ST"
sudo -u $UTILISATEUR .venv/bin/python manage.py migrate --noinput
sudo -u $UTILISATEUR .venv/bin/python manage.py charger_profil
sudo -u $UTILISATEUR .venv/bin/python manage.py collectstatic --noinput -v0

echo "==> Service de l'application (gunicorn)"
cp deploy/veille-ao.service /etc/systemd/system/veille-ao.service
systemctl daemon-reload
systemctl enable --now veille-ao

echo "==> Serveur web (nginx) et HTTPS"
sed "s#__DOMAINE__#$DOMAINE#g" deploy/nginx.conf > /etc/nginx/sites-available/veille-ao
ln -sf /etc/nginx/sites-available/veille-ao /etc/nginx/sites-enabled/veille-ao
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
certbot --nginx -d "$DOMAINE" --non-interactive --agree-tos --register-unsafely-without-email --redirect || \
  echo "!! HTTPS non activé : vérifiez que $DOMAINE pointe vers ce serveur, puis relancez : certbot --nginx -d $DOMAINE"

echo "==> Tâches planifiées (veille chaque matin, sauvegarde chaque nuit)"
cp deploy/veille-ao.cron /etc/cron.d/veille-ao
chmod 644 /etc/cron.d/veille-ao
mkdir -p /var/backups/veille-ao && chown $UTILISATEUR: /var/backups/veille-ao
touch /var/log/veille-ao.log && chown $UTILISATEUR: /var/log/veille-ao.log

echo
echo "==> Création du compte administrateur"
sudo -u $UTILISATEUR .venv/bin/python manage.py createsuperuser

echo
echo "Terminé : https://$DOMAINE"
