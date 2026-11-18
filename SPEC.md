# Veille & réponse aux appels d'offres — Cahier des charges (v0.3)

Outil **interne** de FORMA'ST (SARL, SIRET 899 526 305 00011, Méry-sur-Oise), non commercialisé. **Profil unique** utilisé pour toutes les réponses, y compris Picard. Objectif : **décider vite et bien où se positionner**, puis réduire au minimum le temps de constitution des dossiers.

| Paramètre | Valeur retenue |
|---|---|
| Périmètre métier | Santé, sécurité et prévention au travail : secourisme (SST, MAC SST, PSC), incendie et évacuation, gestes et postures / TMS, QVT / RPS, digital sécurité |
| Habilitations | Qualiopi, habilitation INRS SST |
| Zone | **Nationale** |
| Cible | Marchés **publics et privés**, de taille moyenne, **peu concurrentiels** |
| Stack | Libre (proposition ci-dessous) |

---

## 1. Principes directeurs

1. **Décider avant de rédiger.** Le cœur de l'outil est le score Go/No-Go. Un AO non pertinent ne doit jamais coûter plus de 30 secondes de lecture.
2. **La concurrence se mesure.** Les données DECP (marchés attribués) donnent le nombre d'offres reçues, le titulaire et le montant. On s'en sert pour viser les marchés peu disputés.
3. **Zéro double saisie.** Toute information sur l'entreprise est saisie une seule fois et réutilisée dans tous les documents.
4. **L'humain décide et signe.** L'IA trie, analyse et rédige des brouillons. La décision, le prix, la relecture et le dépôt restent humains.
5. **Simple à maintenir** : petite équipe, peu d'utilisateurs.

---

## 2. Profil entreprise — ✅ en place

Entreprise (identité, certifications avec dates d'expiration, chiffres), catalogue (durées, groupes, prix intra et inter), formateurs, références, pièces administratives avec dates d'expiration. Le tout est pré-chargé depuis les documents Picard 2026 et modifiable dans l'admin.

Différenciants identifiés dans les documents, et utilisés par l'IA :
- unité mobile de formation incendie (UMFI) et bac à flammes ;
- formateurs sapeurs-pompiers ;
- approche globale du capital santé (gestes, sommeil, nutrition, stress) ;
- organisation nationale multi-sites avec contact unique ;
- distanciel sur Teams ;
- référence grand compte Picard (1 200 magasins).

---

## 3. Veille et alertes

### 3.1 Sources

| Source | Mode | État |
|---|---|---|
| **BOAMP** | API open data DILA, tous les avis | ✅ collecte quotidienne |
| **TED** | API de recherche v3 (acheteurs français, CPV formation et prévention) | ✅ collecte quotidienne, dédoublonnée avec le BOAMP |
| **DECP** | Fichiers consolidés data.gouv.fr | ⏳ phase 4 (accès réseau déjà autorisé) |
| **Profils acheteurs** (PLACE, AWS-Achat, Maximilien, Mégalis, achatpublic, e-marchespublics, Atexo…) | **Recherche et collecte régulières**, plateforme par plateforme | ⏳ phase 4 : c'est là que se trouvent beaucoup de MAPA de formation |
| **Consultations privées** | Saisie dans l'app ✅, puis import automatique depuis une boîte mail dédiée ⏳ | Partiel |

> Une partie des prestations de formation relève du régime des « services sociaux et autres services spécifiques ». Elles peuvent alors être passées en procédure adaptée jusqu'à un seuil élevé et publiées seulement sur un profil acheteur. **À faire confirmer juridiquement.** Cela renforce l'intérêt de la collecte sur les profils acheteurs.

### 3.2 Paramétrage — ✅ en place

Profils de veille paramétrables :
- **mots-clés forts**, qui suffisent seuls ;
- **mots-clés génériques**, retenus seulement avec un **mot de contexte** (formation, sensibilisation…) ;
- **exclusions** dans l'objet de l'avis ;
- préfixes CPV, départements, fourchette de montant, seuils d'alerte, destinataires.

Mesuré sur 4 semaines réelles (20/10 au 17/11/2026) : 9 540 avis lus, **79 retenus**, dont une vingtaine au cœur de métier :
- formations SST et incendie ;
- santé-sécurité de collectivités ;
- RPS (SNCF) ;
- animations prévention santé ;
- formations sécurité d'Action Logement.

### 3.3 Alertes — ✅ en place

- Digest quotidien au-dessus du seuil.
- Alerte immédiate pour un score très élevé.
- Rappels des dates limites des réponses en cours.
- Alertes sur les pièces administratives arrivant à expiration.

---

## 4. Go/No-Go

### 4.1 Score de pré-qualification — ✅ en place

Le score est calculé par l'IA (Claude) sur chaque avis retenu, en sortie structurée. Il évalue :
- l'adéquation métier ;
- les exigences bloquantes (éliminatoires : SSIAP, CACES, travaux, gardiennage…) ;
- la taille par rapport à la capacité ;
- la concurrence probable ;
- le poids du prix face à la technique ;
- le délai ;
- la géographie.

Un critère éliminatoire plafonne le score à 30 et impose un No-Go. Sans clé API, un score par règles prend le relais.

Prévu ensuite : recalibrer le score à partir des décisions et des résultats réels (gagné ou perdu), enregistrés dans le suivi.

### 4.2 Fiche Go/No-Go détaillée sur le DCE — ✅ en place

On dépose le ZIP du DCE dans l'app. L'IA produit :
- une synthèse d'une page ;
- les critères de jugement et leurs sous-critères ;
- la liste des pièces à fournir, cochée automatiquement d'après le coffre-fort ;
- les pièges et les questions à poser à l'acheteur.

Chaque affirmation cite la page du document source.

### 4.3 Radar de renouvellement — ⏳ phase 4

À partir des DECP et des avis d'attribution (déjà conservés) : les marchés de nos CPV arrivant à échéance dans 3 à 12 mois, avec le titulaire et le nombre d'offres reçues la dernière fois. Le but est d'approcher l'acheteur avant la publication.

---

## 5. Pipeline — ✅ en place

Les statuts : Détecté → À qualifier → Go / No-Go → En rédaction → Déposé → Gagné / Perdu / Sans suite. Chaque dossier porte un responsable, un motif de décision et des notes.

Prévu ensuite : statistiques de taux de succès par activité, type d'acheteur, montant et niveau de concurrence.

---

## 6. Génération des documents — ✅ en place (sauf remplissage des BPU)

### Candidature

**DC1, DC2, DC4, DUME** et attestations sur l'honneur, pré-remplis depuis le profil. Les pièces du coffre-fort sont assemblées, avec vérification de leur validité à la date limite.

### Offre

- **Acte d'engagement** pré-rempli.
- **BPU / DPGF** remplis depuis le catalogue (ligne non reconnue = signalée, jamais inventée).
- **Mémoire technique** en brouillon, structuré selon les sous-critères du règlement de consultation et nourri par la bibliothèque. Toute information manquante est marquée `[À COMPLÉTER]`.
- **Programmes, CV, grille de conformité.**
- **Réponses aux consultations privées** (ex. Picard) : présentation de la structure, programmes, modalités d'évaluation, devis par formation.

### Bibliothèque de contenus

Blocs réutilisables et versionnés, alimentés par les réponses gagnées.

Matière disponible : la proposition Picard 2026 (contenus Gestes et postures 50+, grilles tarifaires, intervenants), la convention de partenariat incendie.

### Dépôt

Le dépôt reste manuel. L'app produit un dossier prêt à déposer (arborescence, nommage, check-list).

---

## 7. Architecture technique

| Brique | Choix |
|---|---|
| Langage, application | Python 3.12+, **Django** (admin, authentification, formulaires inclus) |
| Base de données | SQLite (suffisant en interne). PostgreSQL + pgvector quand la bibliothèque de contenus arrivera. |
| Tâches planifiées | Commande `veille_quotidienne` lancée par cron |
| IA | **API Claude**, modèle `claude-opus-5-5` : sortie structurée validée (Pydantic), profil entreprise mis en cache, bascule automatique sur un autre modèle en cas de refus |
| Collecte | `httpx` avec reprises automatiques |
| Documents (phase 2) | `docxtpl` (Word), `openpyxl` (Excel), `pypdf` |
| Hébergement | VPS en France (OVH ou Scaleway), sauvegarde quotidienne de la base et des fichiers |

**Coût d'IA mesuré sur le volume réel** : environ 80 avis à scorer par mois, soit moins de 10 €/mois. L'analyse d'un DCE coûtera environ 0,50 € et un brouillon de mémoire 1 à 3 €.

**Confidentialité** : les DCE sont publics. Nos prix, mémoires et CV sont envoyés à l'API Anthropic, qui ne les utilise pas pour entraîner ses modèles. Les données restent stockées chez nous, et le JSON du profil (prix, CV) n'est pas versionné.

---

## 8. Phasage

| Phase | Contenu | État |
|---|---|---|
| **P1 — Veille utile** | Profil, collecte BOAMP et TED, filtre, score IA, digest et alertes, interface et pipeline, consultations privées | ✅ livrée |
| **P2 — Dossier administratif** | Coffre-fort avec échéances, DC1, DC2, déclaration sur l'honneur, présentation, aide DUME, dossier ZIP contrôlé à la date limite | ✅ livrée (DC4 non fait) |
| **P3 — Analyse DCE et mémoire** | Dépôt du DCE, analyse IA détaillée, bibliothèque de contenus, brouillon de mémoire en Word, grille de conformité | ✅ livrée (remplissage des BPU à faire) |
| **P4 — Intelligence et couverture** | DECP (score de concurrence, sortants), radar de renouvellement, collecte régulière des profils acheteurs, import des AO privés par e-mail, statistiques et recalibrage | ⏳ |

---

## 9. Questions ouvertes

1. Code postal, N° de déclaration d'activité, CA et effectif : à compléter dans l'admin.
2. Dates d'expiration Qualiopi et INRS SST.
3. Destinataires des e-mails de veille, et serveur SMTP à utiliser.
4. Hébergement : quel serveur (VPS existant ? nom de domaine ?).
5. Autres mémoires ou réponses passés (gagnés ou perdus) pour la bibliothèque.
