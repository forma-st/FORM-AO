# Mise en production de FORM'AO, pas à pas

Compter environ 30 minutes, sans compétence technique particulière. Il faut un serveur, un nom de domaine et un terminal (le *Terminal* sur Mac, *PowerShell* sur Windows).

## 1. Louer un serveur (VPS) en France

N'importe quel petit VPS sous **Debian 12** ou **Ubuntu 24.04** suffit (1 vCPU, 2 Go de RAM, 20 Go de disque), par exemple :
- **OVHcloud** : gamme « VPS », environ 5 à 7 €/mois, datacenter en France ;
- **Scaleway** : instance « DEV1-S » ou « STARDUST », Paris.

À la commande, choisir Debian 12 ou Ubuntu 24.04. Vous recevez par e-mail **l'adresse IP** du serveur et un **mot de passe root**, ou un accès par clé SSH.

## 2. Créer l'adresse web

Chez votre registraire (là où est géré le domaine de FORMA'ST : OVH, Gandi, IONOS…), créez un enregistrement DNS :

| Type | Nom | Valeur |
|---|---|---|
| A | `veille` | l'adresse IP du serveur |

L'application sera alors accessible à l'adresse `https://veille.votre-domaine.fr`. La propagation prend de quelques minutes à une heure.

## 3. Se connecter au serveur

```bash
ssh root@ADRESSE_IP_DU_SERVEUR
```

## 4. Lancer l'installation

Remplacez `veille.votre-domaine.fr` par votre adresse dans la dernière commande :

```bash
apt-get update && apt-get install -y git curl
```

```bash
curl -fsSL -o install.sh https://raw.githubusercontent.com/forma-st/FORM-AO/main/deploy/install.sh
```

Le dépôt étant privé, ce téléchargement ne marche pas directement. Le plus simple : ouvrez `deploy/install.sh` sur GitHub (bouton *Raw*), copiez son contenu, puis sur le serveur tapez `nano install.sh`, collez, enregistrez (Ctrl+O, Entrée, Ctrl+X).

```bash
bash install.sh veille.votre-domaine.fr
```

Le script s'arrête trois fois pour vous demander quelque chose :

1. **Clé de déploiement GitHub.** Le script affiche une ligne qui commence par `ssh-ed25519`. Sur GitHub, ouvrez le dépôt **forma-st/FORM-AO**, puis **Settings → Deploy keys → Add deploy key**. Collez la ligne, donnez un nom (« serveur veille »), laissez **Allow write access décoché**, validez. Revenez au terminal et appuyez sur Entrée.
2. **Fichier `.env`.** L'éditeur s'ouvre. Complétez :
   - `ANTHROPIC_API_KEY=` : votre clé `sk-ant-…`. Créez de préférence une clé à part pour le serveur dans la console Anthropic.
   - `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` : la boîte mail qui envoie les alertes. Par exemple, pour une boîte OVH : `ssl0.ovh.net`, port `587`.

   Les lignes `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS` et `BASE_URL` sont déjà remplies. Enregistrez avec Ctrl+O, Entrée, puis Ctrl+X.
3. **Compte administrateur.** Choisissez un identifiant, un e-mail et un mot de passe solide.

Ensuite, ouvrez `https://veille.votre-domaine.fr` et connectez-vous.

## 5. Premiers réglages dans l'application

- **Profil** : compléter le chiffre d'affaires, les contacts et les dates d'expiration.
- **Paramètres → Profils de veille** : ajouter les **destinataires** du digest.
- **Coffre-fort** : déposer les pièces administratives quand vous les avez.
- Pour lancer tout de suite une première collecte sans attendre le lendemain matin :

```bash
sudo -u veilleao bash -c "cd /opt/veille-ao && .venv/bin/python manage.py collecter --depuis $(date -d '-14 days' +%F) && .venv/bin/python manage.py scorer"
```

## Ce que fait le serveur ensuite, tout seul

| Quand | Quoi |
|---|---|
| Chaque jour à 7 h 10 | Collecte BOAMP et TED, score, alertes et digest par e-mail |
| Chaque nuit à 2 h 20 | Sauvegarde de la base et des fichiers déposés dans `/var/backups/veille-ao`, conservée 30 jours |
| En permanence | Redémarrage automatique de l'application en cas de panne ou de redémarrage du serveur |
| Tous les 60 jours | Renouvellement automatique du certificat HTTPS (certbot) |

## Mettre à jour après une évolution du code

```bash
bash /opt/veille-ao/deploy/mise-a-jour.sh
```

## En cas de problème

Journal de l'application :

```bash
journalctl -u veille-ao -n 50
```

Journal de la veille quotidienne :

```bash
tail -n 50 /var/log/veille-ao.log
```

Modifier le `.env` (puis redémarrer l'application) :

```bash
nano /opt/veille-ao/.env
```

```bash
systemctl restart veille-ao
```

Conseil : faites aussi, de temps en temps, une copie des sauvegardes hors du serveur, par exemple depuis l'espace client de l'hébergeur (« backup » ou « snapshot »).
