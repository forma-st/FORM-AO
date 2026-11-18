# Agent d'aide à la prospection — Cahier des charges (v0.2)

Module **interne** de FORMA'ST, testé d'abord seul, puis intégré en tout ou partie au **CRM interne** (développé avec Claude Code) et à l'**application AO** (Veille AO, ce dépôt).

> **v0.2 (18/11/2026)** : le CRM est un outil interne, l'intégration se fait donc directement (3.14) ; ajout du module de messagerie (3.16) et d'une base « historique des formations » en attendant la connexion au CRM (3.17).

Maquette fonctionnelle : [`maquettes/prospection.html`](maquettes/prospection.html) (données fictives).

| Paramètre | Valeur retenue (à valider) |
|---|---|
| Objectif | Trouver, qualifier et contacter des entreprises et organismes ayant un **besoin réel** en formation santé-sécurité, puis transmettre au CRM des rendez-vous qualifiés |
| Offre vendue | SST et MAC SST, incendie / évacuation / UMFI, gestes et postures / TMS, QVT / RPS, digital sécurité |
| Cibles | Privé (PME et ETI multi-sites en priorité, grands comptes) et public (collectivités, établissements de santé, bailleurs) |
| Zone | Nationale, avec un poids plus fort pour l'Île-de-France et les zones déjà couvertes par les formateurs |
| Utilisateurs | 2 à 5 personnes (dirigeant, commercial, assistante) |
| Intégration | CRM interne et application AO, développés avec Claude Code : intégration directe, sans connecteur tiers |
| Mode de test | Module autonome (sa propre base), puis branchement au CRM par une simple bascule de configuration |
| Objectif chiffré proposé | 8 à 12 rendez-vous qualifiés par mois après 3 mois, pour moins de 2 h de travail commercial par jour |

---

## 1. Principes directeurs

1. **Les signaux avant les listes.** Une entreprise qui ouvre un site, recrute un responsable QSE ou dont les SST arrivent à échéance vaut dix fiches tirées d'un annuaire. L'agent cherche d'abord un *motif de contact*.
2. **Le besoin se calcule.** Chaque prospect affiche un besoin estimé (nombre de SST à former, exercices d'évacuation, recyclages) et un chiffre d'affaires potentiel tiré du catalogue. On parle au prospect de *son* obligation, pas de notre offre.
3. **L'humain valide ce qui part.** L'IA trouve, résume, rédige et classe. Le premier message de chaque séquence, les messages LinkedIn et les appels restent humains. Rien n'est envoyé sans un modèle validé.
4. **Conforme par construction (RGPD, CNIL, CGU LinkedIn).** Base légale, information, opposition et durée de conservation sont gérées par l'outil, pas par la mémoire des utilisateurs.
5. **Zéro double saisie.** Un prospect existe une seule fois (clé SIREN / SIRET), quelles que soient ses sources. Ce qui est saisi dans l'agent remonte au CRM, et inversement.
6. **Réutiliser l'existant.** Profil entreprise, catalogue, formateurs, références, bibliothèque de contenus, client IA, envoi d'e-mails, tâches de fond et digest de Veille AO.
7. **Coût maîtrisé et mesuré.** Chaque appel IA et chaque crédit d'enrichissement est compté et affiché par prospect, par source et par mois.

### Ce que l'agent ne fait pas

- Pas de collecte automatisée de LinkedIn (voir 3.1.3).
- Pas d'envoi de masse : plafond quotidien par boîte d'envoi, jours ouvrés uniquement.
- Pas de prospection vers des particuliers (B2C).
- Pas de signature de devis ni de saisie de prix hors catalogue : le prix reste humain, comme pour les AO.

---

## 2. Utilisateurs et droits

| Rôle | Fait | Ne fait pas |
|---|---|---|
| **Administrateur** | Paramètres, sources, clés API, boîtes d'envoi, modèles, automatisations, purge RGPD | — |
| **Commercial** | Prospects, séquences, réponses, tâches, RDV, envoi vers le CRM | Modifier les règles RGPD, les plafonds d'envoi |
| **Assistant(e)** | Import, nettoyage, enrichissement, tâches qui lui sont assignées | Lancer une séquence, envoyer |
| **Lecture seule** (dirigeant, associé) | Tableaux de bord, fiches | Modifier |

Chaque action est journalisée (qui, quoi, quand, avant/après). Double authentification recommandée pour les rôles Administrateur et Commercial.

---

## 3. Périmètre fonctionnel

### 3.1 Sources de données

#### 3.1.1 Tableau des sources

| # | Source | Données utiles | Mode | Coût | Priorité |
|---|---|---|---|---|---|
| S1 | **Bases fournies** (fichiers clients, CCI, salons, achats de fichiers, exports d'autres outils) | Tout | Import CSV / XLSX avec correspondance des colonnes | Gratuit | **MVP** |
| S2 | **Base clients interne / CRM** | Clients, stagiaires formés, dates de formation, devis perdus | Synchronisation CRM | Gratuit | **MVP** |
| S3 | **API Recherche d'entreprises** (DINUM, déjà utilisée pour le profil) | SIREN, SIRET, NAF, tranche d'effectif, établissements, dirigeants, conventions collectives (IDCC), date de création, état | API publique | Gratuit | **MVP** |
| S4 | **Veille AO** (données déjà collectées) | Acheteurs publics actifs en formation, titulaires (concurrents), attributions, avis écartés mais acheteur pertinent | Interne | Gratuit | **MVP** |
| S5 | **BODACC** (même plateforme open data que le BOAMP) | Créations, nouveaux établissements, transferts de siège, changements de dirigeant, procédures collectives (exclusion) | API open data | Gratuit | P3 |
| S6 | **France Travail — Offres d'emploi** | Recrutements QSE / HSE / RH, ouvertures de postes en nombre (nouveaux arrivants à former), métiers exposés | API (inscription développeur) | Gratuit | P3 |
| S7 | **Géorisques — installations classées (ICPE)** | Sites industriels classés, régime (autorisation, Seveso) : besoin incendie et évacuation fort | API publique | Gratuit | P3 |
| S8 | **Annuaire de l'administration** (Service-Public) | Mairies, EPCI, établissements publics : adresses, services, contacts génériques | API publique | Gratuit | P3 |
| S9 | **DECP** (données essentielles des marchés publics) | Marchés de formation attribués, dates de fin, titulaires, montants : **radar de renouvellement** | Fichiers data.gouv.fr | Gratuit | P3 (commun avec Veille AO P4) |
| S10 | **Veille web et presse** | Ouvertures de sites, inaugurations, levées de fonds, accidents rapportés (usage prudent), labels | Recherche web + flux RSS + extraction IA | Quelques centimes / article | P3 |
| S11 | **Enrichissement de contacts** (prestataire conforme RGPD, ex. un service qui calcule et vérifie l'e-mail sans base revendue) | E-mail professionnel vérifié, téléphone standard | API payante à l'usage | ~0,05 à 0,15 € / contact trouvé | P2 (option) |
| S12 | **LinkedIn** | Contacts, changements de poste, publications | Manuel assisté uniquement (3.1.3) | Licence Sales Navigator éventuelle | P2 |
| S13 | **Listes d'exposants et de visiteurs de salons** (Préventica, salons RH et logistique) | Entreprises sensibilisées à la prévention | Import S1 | Gratuit | P2 |
| S14 | **Site web FORMA'ST** (formulaires, simulateur d'obligation, voir 3.15) | Demandes entrantes, intentions | Webhook | Gratuit | P4 |

#### 3.1.2 Import de bases fournies (S1)

- Formats : CSV (séparateur `;` ou `,` détecté), XLSX, encodage UTF-8 ou Windows-1252 détecté.
- **Correspondance des colonnes automatique** par synonymes (« Raison sociale », « Société », « Entreprise » → `nom` ; « Siret », « N° SIRET » → `siret`…), modifiable, mémorisée par modèle de fichier.
- **Normalisation** : majuscules, accents, téléphones au format E.164, codes postaux, suppression des formes juridiques dans le nom de comparaison.
- **Dédoublonnage** par ordre de fiabilité : SIRET → SIREN → nom normalisé + code postal → domaine du site web. Fusion proposée, jamais imposée.
- **Rapprochement SIRENE** automatique pour chaque ligne sans SIREN (recherche par nom + commune) avec un indice de confiance ; en dessous de 80 %, la ligne passe en « à vérifier ».
- **Contrôles** : SIREN valide (clé de Luhn), entreprise fermée, procédure collective, présence sur la liste d'opposition, adresse e-mail personnelle (gmail, orange…) signalée.
- **Provenance** conservée pour chaque champ (source, date, fichier) : indispensable pour l'information RGPD et pour mesurer le rendement de chaque source.
- Rapport d'import : nouveaux, mis à jour, doublons, rejetés (avec motif), opposés. Annulation possible d'un import complet pendant 30 jours.

#### 3.1.3 LinkedIn : cadre retenu

Le scraping et l'automatisation de LinkedIn sont **exclus** : ils violent les conditions d'utilisation (risque de fermeture du compte) et la CNIL sanctionne la collecte de profils sans information des personnes (sanction de 240 000 € contre un outil d'extraction de contacts en décembre 2024).

L'agent propose à la place :
1. **Tâches LinkedIn manuelles** dans les séquences : « Consulter le profil », « Envoyer une invitation », « Envoyer un message ». L'agent rédige le texte (≤ 300 caractères pour une invitation), l'utilisateur le copie et l'envoie lui-même.
2. **Bouton « Ajouter à l'agent »** (extension de navigateur, P4, à valider juridiquement) : sur une page consultée par l'utilisateur, seuls le nom, la fonction et l'entreprise sont transmis après clic ; l'e-mail est recherché par l'enrichissement S11, et la personne reçoit l'information RGPD au premier contact.
3. **Import de l'export officiel de ses propres relations** (fichier fourni par LinkedIn à la demande de l'utilisateur).
4. **Alertes Sales Navigator** (changement de poste, nouvelle publication) recopiées en signaux par l'utilisateur, ou transférées par e-mail vers la boîte de l'agent qui les lit.
5. **Aide à la publication** : l'agent propose chaque semaine un post (actualité réglementaire, retour d'expérience, saison) pour attirer les contacts au lieu de les chercher.

### 3.2 Ciblage : profil client idéal et segments

#### 3.2.1 Profil client idéal (paramétrable)

Critères, chacun avec un poids réglable :
- **Secteur** (codes NAF, groupés en familles : logistique et entreposage, industrie, santé et médico-social, commerce multi-sites, hôtellerie-restauration, BTP, transport, collectivités, bailleurs sociaux, enseignement) ;
- **Effectif** (tranche INSEE ; cœur de cible proposé : 50 à 1 000 salariés) ;
- **Nombre d'établissements** (multi-sites = argument « contact unique national ») ;
- **Zone** (départements prioritaires, rayon autour des formateurs) ;
- **Exposition au risque** : site ICPE, ERP, activité de manutention, travail isolé, public accueilli ;
- **Ressemblance avec nos meilleurs clients** (sosie : même NAF, taille et organisation que la référence enseigne nationale de distribution) ;
- **Exclusions** : concurrents (organismes de formation sécurité, code NAF 85.59A avec mots-clés), clients actuels gérés par le CRM, procédure collective, opposition.

#### 3.2.2 Segments livrés par défaut

| Segment | Pourquoi | Angle d'approche |
|---|---|---|
| Entrepôts et plateformes logistiques 50+ salariés | Manutention, chariots, rotation du personnel, ICPE fréquents | Gestes et postures, SST, incendie, accueil des intérimaires |
| Commerce multi-sites (enseignes, franchises) | ERP, personnel jeune, nombreux sites | Contact unique national, distanciel, UMFI sur parking |
| Établissements de santé et médico-social (EHPAD, cliniques) | TMS, RPS, évacuation de personnes non autonomes | Évacuation horizontale, gestes et postures soignants, QVT |
| Industrie et agroalimentaire | Risques incendie, SST obligatoire en atelier dangereux | Bac à flammes, formateurs sapeurs-pompiers |
| Collectivités et EPCI | Agents techniques, ERP communaux, marchés < seuils | Accord-cadre ou bon de commande, approche avant marché |
| Hôtellerie-restauration | Turnover, ERP, nuit | Formations courtes, horaires adaptés |
| Clients actuels (réactivation) | Recyclages obligatoires | MAC SST à 24 mois, exercices semestriels |

#### 3.2.3 Calcul du besoin estimé

Affiché sur chaque fiche, avec ses hypothèses (modifiables) :
- **SST** : 10 à 15 % de l'effectif (recommandation INRS ; obligation dans chaque atelier où sont effectués des travaux dangereux et sur les chantiers de 20 personnes et plus, art. R4224-15 du Code du travail) → nombre de stagiaires, nombre de sessions (groupes de 4 à 10), puis **MAC SST tous les 24 mois**.
- **Incendie / évacuation** : exercices et formation au moins **tous les 6 mois** (art. R4227-39), guides et serre-files par zone, équipiers de première intervention.
- **Gestes et postures** : salariés exposés à la manutention manuelle (art. R4541-8), part estimée selon le NAF.
- **Chiffre d'affaires potentiel** = sessions × prix intra du catalogue, première année et récurrent annuel.
- **Financement** : OPCO déduit de la convention collective (IDCC de S3), avec mention « finançable » pour les entreprises de moins de 50 salariés. *Barèmes OPCO à charger et tenir à jour.*

### 3.3 Score de priorité

Trois sous-scores sur 100, combinés par des poids réglables (par défaut 45 / 35 / 20) :

| Sous-score | Ce qu'il mesure | Calcul |
|---|---|---|
| **Adéquation** | Le prospect correspond-il au profil idéal ? | Somme pondérée des critères 3.2.1, plafonnée à 100 |
| **Intention** | A-t-il une raison d'acheter *maintenant* ? | Somme des signaux (3.4) × décroissance exponentielle selon l'âge (demi-vie propre à chaque signal), plafonnée à 100 |
| **Accessibilité** | Peut-on joindre un décideur ? | Décideur identifié (+40), e-mail vérifié (+30), téléphone direct (+15), relation LinkedIn ou recommandation (+15) |

- Paliers : **A** ≥ 70, **B** 50 à 69, **C** < 50. Seuls les A et B entrent dans les séquences automatiques.
- L'IA produit une **explication en une phrase** (« Entrepôt ICPE de 240 salariés, offre d'emploi de responsable HSE il y a 6 jours, aucun contact identifié »).
- **Recalibrage** (P4) : à partir des résultats réels (réponse, RDV, devis, gagné), proposition de nouveaux poids, appliquée seulement après validation.

### 3.4 Signaux et déclencheurs

| Signal | Source | Poids par défaut | Demi-vie | Action suggérée |
|---|---|---|---|---|
| Nouvel établissement créé dans la zone | BODACC, SIRENE | 35 | 60 j | Message « ouverture de site » : formation des équipes avant ouverture |
| Offre d'emploi QSE / HSE / responsable sécurité | France Travail, web | 30 | 30 j | Contacter le DRH ; le futur QSE sera ensuite l'interlocuteur |
| Recrutement en nombre (≥ 10 postes ouverts) | France Travail | 20 | 30 j | Accueil sécurité des nouveaux arrivants |
| Changement de dirigeant ou de DRH | BODACC, LinkedIn (manuel) | 20 | 90 j | Présentation au nouvel arrivant |
| Marché public de formation arrivant à échéance (3 à 12 mois) | DECP, attributions Veille AO | 40 | 180 j | Rendez-vous de découverte avant publication |
| Acheteur public ayant publié un AO non retenu (lot hors périmètre) | Veille AO | 15 | 120 j | Se faire connaître pour les besoins futurs |
| MAC SST d'un client arrivant à 24 mois | CRM / historique | 50 | 90 j | Séquence de réactivation |
| Exercice d'évacuation semestriel non programmé chez un client | CRM | 30 | 60 j | Proposition de date |
| Site classé ICPE ou Seveso | Géorisques | 15 (permanent) | — | Angle incendie et évacuation |
| Article de presse : ouverture, extension, rachat, levée de fonds | Veille web | 25 | 45 j | Message de félicitations + besoin |
| Visite répétée du site web ou téléchargement d'un guide (si consentement cookies) | Site FORMA'ST | 25 | 14 j | Appel |
| Ouverture répétée de nos e-mails sans réponse | Séquences | 10 | 14 j | Appel plutôt qu'un e-mail de plus |
| Procédure collective | BODACC | **Exclusion** | — | Retrait des séquences |

Chaque signal garde sa **source vérifiable** (lien, date, extrait). Un signal sans source n'est pas utilisé dans un message.

### 3.5 Fiche prospect

**Compte** : identité (SIREN, NAF, effectif, établissements, dirigeants), segment, score et explication, besoin estimé et CA potentiel, OPCO, signaux, historique complet (e-mails, appels, tâches, notes), statut, responsable, provenance des données, base légale et date d'information RGPD.

**Contacts** (plusieurs par compte) : nom, fonction, rôle dans la décision (décideur, prescripteur, utilisateur, standard), e-mail et statut (vérifié, probable, invalide, bloqué), téléphone, profil LinkedIn (lien saisi à la main), consentement ou opposition, dernier contact.

**Statuts** : Nouveau → À qualifier → À contacter → En séquence → A répondu → RDV fixé → Transmis au CRM (opportunité) → Client. Sorties : Pas maintenant (avec date de reprise), Écarté (motif), Opposé.

**Actions rapides** : enrichir, rafraîchir SIRENE, générer le brief, rédiger un message, inscrire en séquence, créer une tâche, planifier un appel, transmettre au CRM, écarter, marquer opposé.

### 3.6 Rédaction par l'IA

| Production | Contenu | Règles |
|---|---|---|
| **Brief compte** (5 lignes) | Qui ils sont, risques métier, obligations, signaux, angle | Toute affirmation cite sa source |
| **E-mail d'approche** | Objet court, accroche sur le signal, besoin chiffré, une référence comparable, une seule question d'appel à l'action | 90 à 140 mots, vouvoiement, pas de pièce jointe au premier envoi, pied de page RGPD et lien d'opposition |
| **Invitation et message LinkedIn** | Version courte du même angle | ≤ 300 caractères pour l'invitation |
| **Script d'appel** | Ouverture en 20 s, 3 questions de découverte, réponses aux 6 objections courantes (« on a déjà un prestataire », « pas de budget », « on fait en interne »…) | Adapté au segment et au rôle |
| **Relances** | Nouvel angle à chaque étape (preuve, contenu utile, question fermée, message de fin) | Jamais « je me permets de relancer » seul |
| **Préparation de RDV** | Fiche d'une page : contexte, besoin estimé, questions, offre à pousser, prix indicatifs du catalogue | — |
| **Proposition express** | Devis brouillon depuis le catalogue (formation, durée, groupe, prix intra) | Envoyé au CRM pour validation, jamais au client directement |

Garde-fous : rien n'est inventé (référence, chiffre, nom), toute donnée manquante est signalée `[À COMPLÉTER]` comme dans les mémoires ; liste de mots interdits (« urgent », « gratuit », promesses de résultats) ; ton réglable (direct, institutionnel pour le public, chaleureux pour la réactivation) ; l'utilisateur peut améliorer un texte par une consigne (« plus court », « insiste sur l'UMFI »).

### 3.7 Séquences multicanales

- **Étapes** : e-mail, tâche LinkedIn, appel, attente, condition (« si ouvert sans réponse », « si poste = DRH »), tâche libre.
- **Séquences livrées** : « Ouverture de site » (5 étapes / 16 jours), « Recrutement QSE » (4 / 12 j), « Réactivation MAC SST » (3 / 21 j), « Acheteur public avant marché » (4 / 30 j), « Nurturing trimestriel » (contenu utile, 1 e-mail / trimestre).
- **Arrêt automatique** : réponse reçue, RDV pris, opposition, rebond définitif, absence avec date de retour (pause jusqu'à la date), changement de statut manuel.
- **Envoi** : depuis la boîte de l'utilisateur ou un sous-domaine dédié ; plafond par boîte (40 / jour au départ, montée progressive), plages 8 h 30–11 h 30 et 14 h–17 h, jours ouvrés, fuseau Europe/Paris, espacement aléatoire de 2 à 6 minutes.
- **Validation** : mode « brouillon » (chaque e-mail validé), mode « modèle validé » (l'IA personnalise un modèle approuvé, envoi automatique), mode « premier envoi validé » (par défaut).
- **Tests A/B** d'objets et d'accroches, avec arrêt à 100 envois par variante.

### 3.8 Réponses : lecture et tri

La boîte d'envoi est relevée toutes les 5 minutes (IMAP ou Microsoft Graph). Chaque réponse est classée par l'IA :

| Classe | Action automatique | Action proposée |
|---|---|---|
| Intéressé / demande de RDV | Séquence arrêtée, statut « A répondu », notification immédiate | Proposer 3 créneaux du calendrier, préparer la fiche RDV |
| Pas maintenant (« revenez en mars ») | Statut « Pas maintenant », date de reprise extraite | Tâche de rappel à la date |
| Mauvais interlocuteur (« voyez avec M. X ») | Nouveau contact créé depuis la réponse | Séquence pour le nouveau contact, mention du recommandant |
| Déjà équipé / prestataire en place | Statut « Pas maintenant », reprise à 11 mois | Noter le prestataire (veille concurrence) |
| Absence / congés | Pause jusqu'à la date de retour | — |
| Demande d'opposition / désinscription | **Opposition immédiate et globale** (toutes boîtes, tous canaux) | — |
| Rebond technique | E-mail marqué invalide | Rechercher un autre contact |
| Autre / incertain (confiance < 80 %) | Aucune | Lecture humaine |

### 3.9 Automatisations

Moteur **Quand → Si → Alors**, activable recette par recette, avec journal d'exécution et mode « simulation » (montre ce qui se serait passé sans rien faire).

**Déclencheurs** : nouveau prospect, signal détecté, changement de score ou de statut, réponse classée, date (relative à un champ), tâche en retard, réception d'un webhook CRM, planification (chaque jour / semaine).
**Conditions** : palier, segment, département, effectif, présence d'un contact, responsable, statut CRM.
**Actions** : enrichir, rafraîchir SIRENE, générer brief ou message, inscrire / retirer d'une séquence, créer une tâche, assigner, changer le statut, notifier (e-mail, Teams), créer ou mettre à jour dans le CRM, ajouter à la liste d'opposition.

**Recettes livrées** :
1. Nouveau prospect palier A → enrichir, générer le brief, assigner au commercial de la zone, tâche « qualifier » sous 48 h.
2. Client dont la MAC SST tombe dans 90 jours → séquence « Réactivation MAC SST » + tâche d'appel à J-60.
3. Nouvel établissement BODACC dans un segment cible et un département prioritaire → création du prospect + signal.
4. Offre d'emploi QSE détectée → signal + tâche LinkedIn « identifier le DRH ».
5. Avis d'attribution d'un marché de formation à un concurrent → acheteur ajouté au radar, tâche à 9 mois de l'échéance.
6. Réponse « pas maintenant » → tâche datée + reprise automatique de la séquence à la date.
7. RDV fixé → opportunité dans le CRM, fiche de préparation, devis brouillon, rappel la veille.
8. Devis envoyé sans réponse à J+7 → tâche de relance téléphonique.
9. Prospect sans interaction depuis 120 jours → passage en nurturing trimestriel.
10. Chaque lundi 8 h → digest commercial (tâches de la semaine, nouveaux A, réponses en attente, RDV).
11. Chaque nuit → rafraîchissement SIRENE des prospects actifs (fermeture, déménagement, effectif).
12. Chaque mois → purge RGPD (prospects sans contact émanant d'eux depuis 3 ans) avec liste préalable à valider.
13. Saison : mai → message « prévention chaleur » aux segments logistique et BTP ; septembre → « rentrée : nouveaux arrivants ».
14. Score passé de B à A → notification au responsable.

### 3.10 Tâches, agenda et rendez-vous

- **File du jour** triée par priorité : appels, LinkedIn, relances, qualifications. Chaque tâche ouvre la fiche avec le texte prêt.
- **Mode « session d'appels »** : enchaînement des appels du jour, script affiché, compte rendu dicté ou tapé, classé par l'IA (résultat, prochaine étape, date).
- **Calendrier** : Outlook / Microsoft 365 (l'équipe utilise Teams) via Microsoft Graph, ou Google Agenda. Créneaux libres proposés dans les réponses, lien de prise de RDV, invitation Teams générée.

### 3.11 Assistant conversationnel

Fenêtre de dialogue dans l'agent et, plus tard, dans le CRM. Exemples :
- « Trouve 20 entrepôts de plus de 100 salariés dans le 95 et le 78 sans contact chez nous. »
- « Quels clients doivent recycler leurs SST avant juin ? »
- « Prépare mon rendez-vous de demain avec la clinique. »
- « Pourquoi ce prospect est-il en palier A ? »
- « Rédige un message pour le DRH qui vient d'arriver chez X. »

Fonctionnement : l'IA dispose d'**outils** (recherche de prospects, lecture de fiche, recherche SIRENE, création de tâche, inscription en séquence, rédaction). Les lectures sont immédiates ; **toute écriture est présentée pour confirmation** avant exécution.

### 3.12 Tableau de bord et statistiques

- Entonnoir : prospects → contactés → réponses → RDV → opportunités → gagnés, par mois.
- Taux de réponse et de RDV par séquence, étape, segment, source, signal et commercial.
- Rendement de chaque source : coût (enrichissement + IA) par RDV obtenu.
- Pipeline transmis au CRM et CA gagné issu de l'agent.
- Délivrabilité : rebonds, plaintes, oppositions, réputation des boîtes.
- Coût IA du mois.
- Échéances à venir : MAC SST clients, marchés publics à renouveler.

### 3.13 Conformité : RGPD, CNIL, délivrabilité

| Exigence | Mise en œuvre |
|---|---|
| Base légale | Intérêt légitime pour la prospection B2B, documenté (analyse d'équilibre fournie en annexe du registre) |
| Pertinence | Message en rapport avec la fonction de la personne (règle CNIL pour l'e-mail B2B sans consentement) : contrôle du rôle avant inscription en séquence |
| Information (art. 14) | Mention au premier contact : source de la donnée, finalité, droit d'opposition, contact. Date d'information conservée par contact |
| Opposition | Lien en un clic dans chaque e-mail (en-tête `List-Unsubscribe` + `List-Unsubscribe-Post`), traitement immédiat, liste d'opposition globale (e-mails et domaines) vérifiée à chaque import et chaque envoi |
| Durée de conservation | 3 ans après le dernier contact émanant du prospect, puis suppression ou anonymisation (purge mensuelle, 3.9 n° 12) |
| Droits d'accès et d'effacement | Export de toutes les données d'une personne, effacement en un clic, journalisé |
| Registre | Fiche de traitement « Prospection commerciale » générée par l'outil |
| Sous-traitants | Hébergeur (France), API Claude (pas d'entraînement sur nos données), prestataire d'enrichissement, Microsoft 365 : contrats et clauses à archiver |
| Téléphone | Prospection B2B vers numéros professionnels ; numéros de mobile d'entrepreneurs individuels traités comme des particuliers (Bloctel, et règles de consentement préalable issues de la loi du 30 juin 2025 : **à faire confirmer**) |
| Données sensibles | Aucun article sur un accident du travail n'est cité dans un message ; il peut seulement orienter l'angle |
| Délivrabilité | SPF, DKIM, DMARC sur le domaine d'envoi, sous-domaine dédié conseillé, montée en charge progressive, taux de rebond < 3 %, plaintes < 0,1 %, arrêt automatique d'une boîte au-delà |
| IA | Textes relus ou issus de modèles validés ; journal des générations ; aucune décision automatisée produisant des effets juridiques |

### 3.14 Intégration au CRM interne et à l'application AO

Le CRM et l'application AO sont des outils internes développés avec Claude Code. Il n'y a donc **pas de connecteur tiers** à écrire : l'agent est conçu comme un **module Django réutilisable** (`prospection/`) qui fonctionne seul pendant les tests, puis se branche sur le CRM.

#### 3.14.1 Deux modes, une seule bascule

| Mode | Usage | Où sont les comptes clients et l'historique |
|---|---|---|
| **Autonome** (`PROSPECTION_CRM = "autonome"`) | Phase de test, démonstration | Tables locales du module : `Compte` (statut client) et `HistoriqueFormation` (3.17), alimentées par import |
| **CRM interne** (`PROSPECTION_CRM = "crm_interne"`) | Production | Lus directement dans le CRM (même base ou API interne, voir 3.14.2) |

Tout le code de l'agent passe par une seule interface, `prospection/crm/base.py` :

```python
class PasserelleCRM(Protocol):
    def clients(self, **filtres) -> Iterable[CompteCRM]: ...            # exclusion, réactivation
    def historique_formations(self, siren=None, avant=None) -> Iterable[Formation]: ...  # recyclages
    def creer_ou_maj_compte(self, prospect) -> str: ...               # renvoie l'identifiant CRM
    def creer_opportunite(self, prospect, besoin, brief) -> str: ...
    def ajouter_activite(self, compte_id, type, texte, date) -> None: ...
    def enregistrer_opposition(self, valeur) -> None: ...
    def est_oppose(self, valeur) -> bool: ...
```

Deux implémentations : `autonome.py` (tables locales) et `crm_interne.py`. Passer de l'une à l'autre ne change ni les écrans ni les automatisations. Une commande `migrer_vers_crm` reverse les comptes, contacts, activités et l'historique saisis pendant le test.

#### 3.14.2 Branchement technique (à choisir avec l'architecture du CRM)

| Option | Quand la choisir | Contenu |
|---|---|---|
| **A — Même projet Django** (recommandée si possible) | Le CRM, l'application AO et l'agent peuvent partager un serveur et une base | Le CRM, `veille` et `prospection` sont des applications d'un même projet ; l'agent lit et écrit les modèles du CRM directement ; un seul identifiant de connexion ; transactions communes |
| **B — Applications séparées** | Le CRM a son propre serveur ou sa propre base | API REST interne entre les applications (jeton par application) + webhooks ; même interface `PasserelleCRM`, implémentée par appels HTTP |

Dans les deux cas : **SIREN comme clé commune** entre CRM, application AO et agent ; utilisateurs et droits du CRM réutilisés ; l'agent ne duplique jamais un client du CRM.

#### 3.14.3 Ce que le CRM gagne (intégration « tout ou partie »)

Chaque brique peut être intégrée séparément :

| Brique | Dans le CRM | Effort |
|---|---|---|
| Panneau « Assistant prospection » sur la fiche compte | Score, explication, besoin estimé, signaux, prochaine action, bouton « Rédiger » | Faible (gabarit inclus dans la fiche) |
| Rédaction assistée | Bouton sur chaque contact : e-mail, LinkedIn, script d'appel, relance | Faible |
| File de tâches | Tâches de l'agent dans l'agenda / les tâches du CRM | Moyen |
| Séquences et messagerie | Envoi et chronologie des e-mails dans la fiche du CRM | Moyen |
| Réactivation clients | Alertes MAC SST et exercices semestriels depuis l'historique du CRM | Faible |
| Assistant conversationnel | Fenêtre de dialogue dans le CRM, avec les outils de l'agent | Moyen |

#### 3.14.4 Lien avec l'application AO

L'application AO fournit déjà : les acheteurs publics actifs, les avis d'attribution (concurrents), le profil FORMA'ST, le catalogue, les références, la bibliothèque de contenus et le client IA. L'agent les **lit sans les recopier**. En retour :
- un acheteur public qualifié dans l'agent apparaît dans l'application AO (suivi de ses futurs avis) ;
- un AO gagné ou perdu met à jour le compte dans l'agent et dans le CRM ;
- le radar de renouvellement (DECP, 3.4) est commun aux deux outils.

#### 3.14.5 Propriété des données

| Objet | Maître | Règle |
|---|---|---|
| Compte prospect (avant qualification) | Agent | Créé dans le CRM au statut « RDV fixé » ou sur demande |
| Compte client | CRM | Lu par l'agent (exclusion, réactivation) |
| Contact | Agent avant transmission, CRM ensuite | Dernier modifié gagne, conflit signalé |
| Opportunité / devis | CRM | Créée par l'agent, mise à jour par le CRM |
| Activités (e-mails, appels, notes) | Agent | Visibles dans la chronologie du CRM |
| Formations réalisées | CRM (ou `HistoriqueFormation` en mode autonome) | Lues par l'agent pour les recyclages |
| Opposition | Agent et CRM | Une seule liste partagée, effet immédiat |
| Avis de marché, attributions | Application AO | Lus par l'agent |

**Événements internes** (signaux Django en option A, webhooks en option B) émis : `prospect.cree`, `prospect.qualifie`, `prospect.score_change`, `reponse.recue`, `rdv.fixe`, `opposition.enregistree`. Reçus : `client.cree`, `opportunite.gagnee`, `opportunite.perdue`, `formation.realisee`, `ao.resultat`.

### 3.15 Possibilités complémentaires (non demandées, recommandées)

1. **Réactivation de la base clients** : la source la plus rentable. MAC SST à 24 mois, exercices semestriels, nouveaux embauchés chez les clients, extension d'une formation réussie à d'autres sites. À activer dès le MVP.
2. **Simulateur d'obligations sur le site web** : « Combien de SST devez-vous avoir ? » (effectif, activité, nombre de sites). Le résultat est envoyé par e-mail : le prospect arrive avec son besoin chiffré et son consentement.
3. **Calculateur de financement OPCO** joint aux propositions des entreprises de moins de 50 salariés.
4. **Radar des marchés publics à renouveler** (DECP + attributions déjà conservées par Veille AO) : approcher l'acheteur 6 à 9 mois avant la publication, au moment où il rédige son cahier des charges.
5. **Prescripteurs** : experts-comptables, cabinets RH, assureurs prévoyance, services de prévention et de santé au travail, élus de CSE. Séquence dédiée et suivi des recommandations.
6. **Parrainage client** : demande de recommandation automatique 15 jours après une formation bien évaluée (questionnaire Qualiopi), avec avis Google.
7. **Référencement fournisseur des grands comptes** : repérer les portails achats privés et préparer le dossier de référencement (réutilise le coffre-fort de Veille AO).
8. **Campagnes saisonnières et réglementaires** : chaleur (été), rentrée, fin d'année (budget formation à consommer), nouvelle réglementation : message préparé pour les segments concernés.
9. **Salons** (Préventica) : import des listes, séquence avant salon (prise de RDV sur le stand) et après salon.
10. **Webinaires courts** (30 min) « DUERP et obligations de formation » : inscription = contact consentant et qualifié.
11. **Vente additionnelle pendant les formations** : le formateur note sur une fiche mobile les besoins repérés sur site (extincteurs, autres équipes) → signal dans l'agent.
12. **Analyse des devis perdus** : relance à 11 mois, motif de perte, prix du concurrent si connu.
13. **Contenu LinkedIn hebdomadaire** proposé par l'agent (3.1.3, n° 5).
14. **Intégration Teams** : notifications et commandes simples (« /prospect clinique des Tilleuls ») dans un canal.

### 3.16 Module de messagerie

Brique commune, réutilisable plus tard par le CRM et l'application AO (envoi des digests, des devis). Les réglages précis (serveurs, domaine, comptes) seront définis plus tard ; le module est conçu pour les accepter sans changement de code.

| Fonction | Détail |
|---|---|
| **Boîtes d'envoi** | Plusieurs boîtes (une par commercial + une générique). Connexion par **Microsoft Graph** (Microsoft 365, choix confirmé) ou SMTP / IMAP en solution de repli. Identifiants dans `.env` ou coffre chiffré, jamais en clair dans la base |
| **Domaine** | Sous-domaine dédié à la prospection (accord donné), avec SPF, DKIM et DMARC ; le domaine principal reste réservé aux échanges courants |
| **Envoi** | File d'attente idempotente (un message n'est jamais envoyé deux fois, même après une coupure), plafond par boîte et par jour, montée en charge progressive, plages horaires et jours ouvrés, espacement aléatoire |
| **Composition** | Éditeur texte simple (pas de HTML lourd), variables (`{prenom}`, `{entreprise}`, `{besoin_sst}`…), signature par utilisateur, pied de page RGPD et lien d'opposition ajoutés automatiquement et non supprimables |
| **Envoi depuis la fiche** | Un e-mail ponctuel peut partir hors séquence, avec les mêmes contrôles (opposition, plafond) |
| **Relève** | Toutes les 5 minutes ; rattachement des réponses par en-têtes `In-Reply-To` / `References`, puis par adresse ; classement par l'IA (3.8) |
| **Fil de discussion** | Chaque échange est visible dans la fiche prospect (et dans la fiche CRM après intégration), envoyés et reçus |
| **Suivi** | Rebonds (définitifs / temporaires), réponses, désinscriptions. Le **suivi d'ouverture par pixel est désactivé par défaut** : la CNIL encadre ces pixels (consentement en principe requis) ; à activer seulement après validation. Sans lui, le signal « e-mails ouverts sans réponse » (3.4) n'est pas utilisé |
| **Santé des boîtes** | Taux de rebond et de plainte par boîte, arrêt automatique au-delà des seuils, alerte à l'administrateur |
| **Mode test** | Tous les envois redirigés vers une adresse interne, ou écrits dans un fichier (comme le `EMAIL_BACKEND` de Veille AO), pour tester les séquences sans rien envoyer |
| **Journal** | Contenu exact envoyé, date, boîte, utilisateur qui a validé, modèle et coût de génération |

Tables ajoutées : `BoiteEnvoi` (§5), `FileEnvoi` (message, boîte, prévu_le, tentatives, statut, erreur), `FilDiscussion` (compte, contact, sujet, messages).

### 3.17 Base « historique des formations » (en attendant le CRM)

En mode autonome, l'agent a sa propre table d'historique pour calculer les recyclages. En mode CRM, la même interface lit l'historique du CRM et cette table sert seulement de reprise.

**Table `HistoriqueFormation`** : compte (SIREN), établissement, prestation (lien vers le catalogue), date de session, nombre de stagiaires, liste des stagiaires (nom, prénom, fonction ; facultatif), formateur, résultat (certificat SST délivré oui / non), date d'échéance calculée, source (import, saisie, CRM), facture / devis lié.

**Règles d'échéance** (paramétrables par prestation) :

| Prestation | Échéance | Relance |
|---|---|---|
| SST initial ou MAC SST | 24 mois après la session | J-90 (séquence), J-60 (appel) |
| Exercice d'évacuation | 6 mois | J-30 |
| Manipulation des extincteurs, EPI | 12 mois (recommandation d'usage) | J-45 |
| Gestes et postures | Pas d'échéance réglementaire : relance à 24 mois et pour les nouveaux embauchés | J-60 |

**Alimentation** : import CSV / XLSX (mêmes écrans que 3.1.2, modèle de fichier fourni), saisie après chaque session, reprise des feuilles d'émargement et des attestations existantes. Les stagiaires sont des données de clients, pas de prospects : conservation selon la durée de la relation commerciale et les obligations Qualiopi, jamais utilisées pour démarcher les stagiaires eux-mêmes.

**Usages** : recyclages (recette 2), tableau « échéances à venir », calcul du CA récurrent, références citables par secteur, preuve d'antériorité dans les messages (« nous avons formé 12 de vos salariés en janvier 2025 »).

---

## 4. Exigences non fonctionnelles

| Domaine | Exigence |
|---|---|
| Performance | Liste de 10 000 prospects filtrée en < 1 s ; fiche ouverte en < 500 ms ; brief IA en < 20 s ; import de 5 000 lignes en < 2 min (rapprochement SIRENE en arrière-plan) |
| Disponibilité | Heures ouvrées ; les envois et relevés reprennent seuls après une coupure, sans doublon (envoi idempotent) |
| Sécurité | Authentification Django, 2FA, droits par rôle, jetons d'API par application, secrets dans `.env`, journal d'audit, HTTPS |
| Hébergement | Le même VPS en France que Veille AO ; sauvegarde quotidienne base + fichiers |
| Données | Passage à PostgreSQL recommandé dès la P2 (volumes, recherche plein texte, accès concurrents des tâches de fond) |
| Coûts IA estimés | Brief ≈ 0,02 €, message ≈ 0,01 €, classement d'une réponse ≈ 0,002 € (modèle économique), assistant ≈ 0,02 € par question. Pour 500 prospects actifs / mois : **15 à 30 € / mois** |
| Qualité | Tests automatiques sur l'import, le dédoublonnage, le score, la classification (jeu de 100 réponses annotées), les règles d'arrêt des séquences et l'opposition |
| Accessibilité | Utilisable au clavier, lisible sur mobile (file de tâches et fiche en priorité) |
| Langue | Interface et messages en français |

---

## 5. Modèle de données (principales tables)

| Table | Champs principaux |
|---|---|
| `Compte` | siren, siret_siege, nom, nom_normalise, naf, segment, tranche_effectif, effectif_estime, nb_etablissements, departement, ville, site_web, idcc, opco, icpe, erp, statut, responsable, score, score_adequation, score_intention, score_acces, palier, explication_score, besoin (JSON), ca_potentiel, crm_id, cree_le, maj_sirene_le, provenance (JSON) |
| `Etablissement` | compte, siret, adresse, effectif, actif |
| `HistoriqueFormation` | compte, etablissement, prestation, date_session, nb_stagiaires, stagiaires (JSON), formateur, certificat_delivre, echeance, source, crm_id |
| `Contact` | compte, civilite, prenom, nom, fonction, role_decision, email, statut_email, telephone, linkedin_url, base_legale, informe_le, oppose, dernier_contact_entrant_le, crm_id |
| `Signal` | compte, type, source, url, extrait, date_signal, poids, demi_vie_jours, actif |
| `Source` / `Import` | nom, type, fichier, mapping (JSON), lignes_lues, crees, maj, doublons, rejets, annulable_jusqu_au |
| `Sequence` / `EtapeSequence` | nom, actif, mode_validation ; ordre, type, delai_jours, condition, modele |
| `Inscription` | contact, sequence, etape_courante, statut, prochaine_action_le, arret_motif |
| `Message` | contact, canal, sens, objet, corps, statut, envoye_le, ouvert_le, repondu_le, message_id, generation (JSON : modèle, coût, consignes) |
| `Reponse` | message, classe, confiance, date_reprise, nouveau_contact, traitee_par |
| `Tache` | compte, contact, type, titre, texte_prepare, echeance, assignee, faite_le, origine |
| `Automatisation` / `ExecutionAutomatisation` | nom, declencheur, conditions (JSON), actions (JSON), actif, simulation ; date, cible, resultat |
| `Opposition` | valeur (e-mail ou domaine), type, source, cree_le |
| `BoiteEnvoi` | adresse, fournisseur, plafond_jour, montee_en_charge, etat, reputation |
| `CoutIA` / `CoutEnrichissement` | date, objet, modele / fournisseur, quantite, montant |
| `Journal` | utilisateur, action, objet, avant, apres, date |

Les tables existantes `Entreprise`, `Prestation`, `Formateur`, `Reference` et `AvisMarche` sont réutilisées telles quelles.

---

## 6. Architecture technique

```
config/                       réglages (inchangés, + app prospection)
veille/                       existant : profil, catalogue, AO, client IA, e-mails
prospection/
  models.py                   tables du §5
  services/
    imports.py                lecture CSV/XLSX, correspondance, normalisation, dédoublonnage
    sirene.py                 rapprochement et rafraîchissement (réutilise veille/services/annuaire.py)
    sources/                  bodacc.py, france_travail.py, georisques.py, decp.py, annuaire_public.py, web.py
    enrichissement.py         adaptateur prestataire d'e-mails (interchangeable)
    besoin.py                 calcul du besoin et du CA potentiel depuis le catalogue
    scoring.py                trois sous-scores, décroissance, explication IA
    redaction.py              brief, e-mails, LinkedIn, scripts, fiche RDV (sorties structurées)
    sequences.py              moteur d'étapes, plafonds, plages horaires, arrêt
    messagerie.py             envoi SMTP / Microsoft Graph, relève IMAP / Graph
    classement.py             classement des réponses (modèle économique)
    automatisations.py        moteur Quand → Si → Alors, simulation, journal
    assistant.py              dialogue avec outils, confirmation des écritures
    crm/                      base.py (interface PasserelleCRM), autonome.py (tables locales), crm_interne.py (CRM maison)
    messagerie/               boîtes, file d'envoi, Graph / SMTP / IMAP, relève, santé des boîtes (3.16)
    rgpd.py                   opposition, purge, export, registre
  api/                        API REST (Django REST Framework) + webhooks
  management/commands/        prospection_horaire, prospection_quotidienne, importer, purger_rgpd
  templates/prospection/      écrans du §7
```

- **Tâches planifiées** : une commande toutes les 5 minutes (relève des réponses, envois dus, automatisations) et une chaque nuit (rafraîchissements, signaux, purge). Le mécanisme cron + threads de Veille AO suffit en P1–P2 ; au-delà de 2 000 envois / mois, passer à une file de tâches (Django-Q2 ou Celery + Redis).
- **IA** : API Claude, sorties structurées validées par Pydantic (comme le score AO), profil FORMA'ST et catalogue mis en cache. Modèle haut de gamme pour la rédaction et l'assistant, modèle économique pour le classement des réponses et l'extraction d'articles.
- **Recherche** : PostgreSQL plein texte et trigrammes pour le dédoublonnage par nom.
- **Front** : même gabarit HTML que Veille AO, quelques composants interactifs (htmx) ; pas de framework lourd.

---

## 7. Écrans (voir la maquette)

| Écran | Contenu |
|---|---|
| Tableau de bord | Indicateurs, entonnoir, signaux récents, échéances, coût IA |
| Prospects | Liste filtrable (palier, segment, département, statut, signal), tri par score, actions groupées |
| Fiche prospect | Score et explication, besoin estimé, signaux, contacts, rédaction IA par canal, historique |
| Import | Dépôt de fichier, correspondance des colonnes, aperçu, rapport de dédoublonnage |
| Séquences | Liste, éditeur d'étapes, statistiques par étape |
| Réponses | Boîte triée par l'IA, actions proposées |
| Tâches | File du jour, mode session d'appels |
| Automatisations | Recettes, éditeur Quand → Si → Alors, journal |
| Assistant | Dialogue avec résultats exploitables |
| Paramètres du score | Poids réglables, aperçu immédiat de l'effet sur les paliers |
| Conformité | Oppositions, purge, registre, état de la délivrabilité |
| Historique des formations | Sessions réalisées, échéances calculées, relances (3.17) |
| Messagerie | Boîtes d'envoi, file d'attente, mode test, santé des boîtes (3.16) |
| Intégration CRM | Bascule autonome / CRM interne, propriété des données, journal des événements, aperçu du panneau dans la fiche CRM |

---

## 8. Phasage et charge estimée

| Phase | Contenu | Charge |
|---|---|---|
| **P1 — MVP « base utile »** (4 semaines) | Module autonome ; import S1 avec dédoublonnage et rapprochement SIRENE, historique des formations (3.17) et recyclages, acheteurs de l'application AO S4, profil idéal, besoin estimé, score (adéquation + accessibilité), fiche, brief et messages IA (copier-coller), tâches, opposition | 15–20 j |
| **P2 — « contacter »** (4 semaines) | Module de messagerie (3.16) avec mode test, séquences e-mail + tâches LinkedIn et appels, relève et classement des réponses, 6 premières automatisations, tableau de bord, RGPD complet, enrichissement S11 (option), PostgreSQL | 15–20 j |
| **P3 — « signaux »** (4 semaines) | BODACC, France Travail, Géorisques, annuaire public, DECP et radar, veille web, score d'intention, assistant conversationnel, recettes 3 à 14 | 15–20 j |
| **P4 — « intégré »** | Passerelle `crm_interne` et reprise des données du test, panneau dans la fiche compte du CRM, briques intégrées au choix (3.14.3), calendrier et prise de RDV, mode session d'appels, recalibrage du score, simulateur web, extension navigateur (après avis juridique), Teams | 15–25 j |

---

## 9. Indicateurs de réussite

| Indicateur | Cible à 3 mois | Cible à 6 mois |
|---|---|---|
| RDV qualifiés par mois | 8 | 12–15 |
| Taux de réponse positive des séquences | ≥ 4 % | ≥ 6 % |
| Temps commercial par RDV obtenu | < 3 h | < 2 h |
| Part des réponses classées sans erreur | ≥ 90 % | ≥ 95 % |
| Taux de rebond | < 3 % | < 2 % |
| CA signé issu de l'agent | suivi | ≥ 20 % du CA nouveau |
| Recyclages MAC SST clients relancés à temps | 100 % | 100 % |

---

## 10. Risques et parades

| Risque | Parade |
|---|---|
| Domaine principal classé en spam | Sous-domaine dédié, montée progressive, plafonds, arrêt automatique sur seuils |
| Plainte CNIL | Information au premier contact, opposition immédiate et globale, purge, registre, pas de LinkedIn automatisé |
| Messages génériques, peu de réponses | Message ancré sur un signal sourcé et un besoin chiffré ; test A/B ; relecture du premier envoi |
| Hallucination de l'IA (fausse référence, faux chiffre) | Sorties structurées, données uniquement issues du profil et des sources, `[À COMPLÉTER]`, liste de références citables |
| Données SIRENE approximatives (effectif en tranche, siège ≠ site) | Effectif affiché en fourchette, choix de l'établissement visé, correction manuelle conservée |
| Doublons avec le CRM | Clé SIREN commune, lecture des clients CRM avant toute inscription |
| Dépendance à un prestataire d'enrichissement | Adaptateur interchangeable ; l'agent fonctionne sans |
| Adoption faible | File du jour courte et prête à l'emploi, digest du lundi, mobile |

---

## 11. Questions ouvertes

Réglées (v0.2) : CRM interne développé avec Claude Code (intégration directe) ; Microsoft 365 et sous-domaine d'envoi acceptés, réglages plus tard ; historique des formations lu dans le CRM, ou base « historique » locale en attendant.

1. **Architecture du CRM** : même projet Django que l'application AO (option A) ou application séparée (option B) ? Quel est son modèle de compte (clé SIREN présente ?) et où sont stockées les formations réalisées ?
2. Bases fournies disponibles aujourd'hui (fichiers, origine, date d'achat, consentements) ?
3. Historique des formations existant (tableur, factures, émargements) pour amorcer la table 3.17 ?
4. Licence **Sales Navigator** en place ou envisagée ?
5. Départements et segments prioritaires, capacité des formateurs par zone.
6. Budget mensuel acceptable pour l'enrichissement des contacts.
7. Qui valide les messages, et à quel rythme (mode de validation par défaut) ?
8. Validation juridique : extension navigateur LinkedIn, démarchage téléphonique des entrepreneurs individuels, pixels de suivi d'ouverture.
9. Objectif chiffré de RDV et de CA à retenir.
