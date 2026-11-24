# FORM'AO sur un Mac, pas à pas

Le Mac sert de serveur : FORM'AO y tourne en permanence, fait la veille chaque matin et sauvegarde ses données chaque jour. Un collègue y accède à distance de façon sécurisée avec Tailscale. Compter environ 20 minutes.

**Condition importante** : le Mac doit rester **allumé, branché et sans veille** pendant la journée. S'il dort à l'heure prévue (7 h 10 par défaut, réglable dans Paramètres), la veille du jour se lance à son réveil. Si le couvercle d'un MacBook est fermé, l'application n'est plus joignable pour le collègue.

## 1. Récupérer le projet

Le plus simple, sans ligne de commande :
1. Sur GitHub, ouvrez le dépôt **forma-st/FORM-AO**, bouton vert **Code → Download ZIP**.
2. Décompressez-le dans **Documents** et renommez le dossier en **FORMAO**. Ne le placez pas dans un dossier caché, ni dans ~/Library.

Pour profiter plus tard des mises à jour (`mise-a-jour.sh`), clonez-le plutôt avec GitHub Desktop, ou dans le Terminal :

```bash
git clone https://github.com/forma-st/FORM-AO.git ~/Documents/FORMAO
```

## 2. Lancer l'installation

Ouvrez le **Terminal** (Applications → Utilitaires), puis :

```bash
cd ~/Documents/FORMAO
```

```bash
bash deploy/mac/installer.sh
```

Le script vous demande :
1. **La clé API Anthropic** (`sk-ant-…`). Elle ne s'affiche pas à la saisie. Créez de préférence une clé dédiée à ce Mac dans la console Anthropic, avec un plafond de dépense.
2. **L'adresse e-mail** qui recevra le digest (facultatif).
3. **Votre compte** : identifiant, e-mail, mot de passe.

S'il manque Python 3.10 ou plus récent, le script l'installe avec Homebrew si Homebrew est présent. Sinon, il vous indique de l'installer depuis python.org, puis de relancer la même commande.

À la fin, FORM'AO s'ouvre dans le navigateur : **http://localhost:8000**. Les avis déjà notés, l'analyse et le mémoire Picard de la phase de test sont repris.

Ce que le script met en place, et qui redémarre tout seul avec le Mac :

| Quoi | Quand |
|---|---|
| L'application | En permanence, relancée automatiquement en cas de problème |
| La veille (collecte, score, e-mails) | Chaque jour à l'heure choisie dans Paramètres (7 h 10 par défaut), ou au réveil du Mac |
| La sauvegarde (base + fichiers déposés, gardée 30 jours) dans `Documents/FORMAO-sauvegardes` | Chaque jour à 12 h 30 |

## 3. Empêcher la mise en veille

**Réglages Système → Batterie → Options** (ou **Économiseur d'énergie** sur un Mac de bureau) :
- activez **« Empêcher la suspension automatique lorsque l'écran est éteint »** quand le Mac est branché ;
- activez **« Réactiver pour l'accès au réseau »**.

L'écran peut s'éteindre, l'application continue de tourner.

## 4. Donner l'accès à votre collègue (Tailscale)

Tailscale crée un réseau privé entre vos deux appareils. Rien n'est exposé sur Internet et aucun réglage de box n'est nécessaire. C'est gratuit pour un usage comme le vôtre.

1. **Sur votre Mac** : installez Tailscale (App Store ou tailscale.com/download), puis connectez-vous avec le compte de FORMA'ST (Google ou Microsoft).
2. **Invitez votre collègue** : console d'administration Tailscale → **Users → Invite users**. Il installe Tailscale sur son ordinateur et accepte l'invitation.
3. **Sur votre Mac**, relancez le script : il publie FORM'AO sur votre réseau privé.

   ```bash
   bash deploy/mac/installer.sh
   ```

   Le script affiche alors l'adresse à donner à votre collègue, de la forme **https://matbook-pro.xxxx.ts.net**, avec le cadenas HTTPS.
4. **Créez son compte** dans FORM'AO : **Réglages avancés → Utilisateurs → Ajouter**. Cochez « Statut équipe » pour qu'il accède aussi aux réglages avancés.

## 5. Premiers réglages dans FORM'AO

- **Profil** : chiffre d'affaires, e-mail, téléphone, dates d'expiration Qualiopi et INRS.
- **Coffre-fort** : déposez les pièces administratives.
- **E-mails** : pour recevoir vraiment le digest, complétez dans le fichier `.env` les lignes `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` et `DEFAULT_FROM_EMAIL`, et remplacez la ligne `EMAIL_BACKEND` par `EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`. Pour une boîte OVH : `ssl0.ovh.net`, port `587`. Ensuite, redémarrez l'application :

  ```bash
  launchctl kickstart -k gui/$(id -u)/com.formast.formao.web
  ```

## Au quotidien

Mettre à jour après une évolution du code (projet cloné avec git) :

```bash
bash ~/Documents/FORMAO/deploy/mac/mise-a-jour.sh
```

Voir les journaux (application, veille, sauvegarde) :

```bash
open ~/Library/Logs/FORMAO
```

Lancer une veille tout de suite :

```bash
cd ~/Documents/FORMAO && .venv/bin/python manage.py veille_quotidienne
```

Arrêter FORM'AO et retirer le démarrage automatique (les données sont conservées) :

```bash
bash ~/Documents/FORMAO/deploy/mac/desinstaller.sh
```

Conseil : laissez **Time Machine** actif sur ce Mac. Il garde en plus une copie du dossier FORMAO et des sauvegardes sur un disque externe.
