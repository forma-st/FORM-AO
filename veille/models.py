from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# Profil entreprise (saisi une fois, réutilisé partout)
# ---------------------------------------------------------------------------


class Entreprise(models.Model):
    """Fiche unique de l'entreprise. Une seule ligne attendue."""

    raison_sociale = models.CharField(max_length=200)
    nom_commercial = models.CharField(max_length=200, blank=True)
    forme_juridique = models.CharField(max_length=50, blank=True)
    siret = models.CharField(max_length=14, blank=True)
    numero_declaration_activite = models.CharField(
        "N° de déclaration d'activité (OF)", max_length=30, blank=True
    )
    adresse = models.CharField(max_length=255, blank=True)
    code_postal = models.CharField(max_length=10, blank=True)
    ville = models.CharField(max_length=100, blank=True)
    representant_nom = models.CharField("Représentant légal", max_length=150, blank=True)
    representant_qualite = models.CharField(max_length=100, blank=True, default="Gérant")
    email = models.EmailField(blank=True)
    telephone = models.CharField(max_length=30, blank=True)
    site_web = models.URLField(blank=True)

    qualiopi = models.BooleanField(default=False)
    qualiopi_expiration = models.DateField(null=True, blank=True)
    habilitation_inrs_sst = models.BooleanField("Habilitation INRS SST", default=False)
    habilitation_inrs_sst_expiration = models.DateField(null=True, blank=True)
    autres_certifications = models.TextField(blank=True)

    effectif = models.PositiveIntegerField(null=True, blank=True)
    ca_n1 = models.DecimalField("CA N-1 (€ HT)", max_digits=12, decimal_places=2, null=True, blank=True)
    ca_n2 = models.DecimalField("CA N-2 (€ HT)", max_digits=12, decimal_places=2, null=True, blank=True)
    ca_n3 = models.DecimalField("CA N-3 (€ HT)", max_digits=12, decimal_places=2, null=True, blank=True)

    zone_intervention = models.CharField(max_length=200, default="National")
    presentation = models.TextField("Présentation (pour les mémoires)", blank=True)
    points_forts = models.TextField(
        "Points forts différenciants",
        blank=True,
        help_text="Utilisé par l'IA pour juger l'adéquation et rédiger.",
    )

    class Meta:
        verbose_name = "Entreprise"
        verbose_name_plural = "Entreprise"

    def __str__(self):
        return self.nom_commercial or self.raison_sociale

    @classmethod
    def get(cls):
        return cls.objects.first()


class Formateur(models.Model):
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    fonction = models.CharField(max_length=200, blank=True)
    experience = models.TextField(blank=True)
    qualifications = models.TextField(
        blank=True, help_text="Certificats, habilitations, diplômes (un par ligne)."
    )
    domaines = models.CharField(max_length=255, blank=True)
    cv = models.FileField(upload_to="formateurs/", blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["nom"]

    def __str__(self):
        return f"{self.prenom} {self.nom}"


class Prestation(models.Model):
    """Catalogue : ce que l'on sait vendre, et à quel prix de référence."""

    CATEGORIES = [
        ("SECOURISME", "Secourisme (SST, MAC SST, PSC)"),
        ("INCENDIE", "Incendie / évacuation"),
        ("ERGONOMIE", "Gestes et postures / TMS"),
        ("QVT", "QVT / RPS / santé"),
        ("DIGITAL", "Digital / vidéo"),
        ("CONSEIL", "Conseil / accompagnement"),
        ("AUTRE", "Autre"),
    ]

    intitule = models.CharField(max_length=200)
    categorie = models.CharField(max_length=20, choices=CATEGORIES)
    duree = models.CharField(max_length=50, blank=True, help_text="Ex. 2j, 3h, 2h30")
    groupe_min = models.PositiveIntegerField(null=True, blank=True)
    groupe_max = models.PositiveIntegerField(null=True, blank=True)
    prix_intra_ht = models.DecimalField(
        "Prix intra HT (session)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    prix_inter_ht = models.DecimalField(
        "Prix inter HT (par participant)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    description = models.TextField(blank=True)
    actif = models.BooleanField(default=True)

    class Meta:
        ordering = ["categorie", "intitule"]

    def __str__(self):
        return f"{self.intitule} ({self.duree})" if self.duree else self.intitule


class Reference(models.Model):
    client = models.CharField(max_length=200)
    secteur = models.CharField(max_length=100, blank=True)
    public = models.BooleanField("Client public", default=False)
    objet = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    date_debut = models.DateField(null=True, blank=True)
    date_fin = models.DateField(null=True, blank=True)
    montant_ht = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    volume = models.CharField(max_length=200, blank=True, help_text="Ex. 4 500 salariés, 1 200 sites")
    contact = models.CharField(max_length=200, blank=True)
    citable = models.BooleanField(
        "Peut être cité", default=True, help_text="Le client accepte d'être cité en référence."
    )
    document = models.FileField(upload_to="references/", blank=True)

    class Meta:
        ordering = ["-date_debut"]

    def __str__(self):
        return f"{self.client} – {self.objet}"


class PieceAdministrative(models.Model):
    TYPES = [
        ("KBIS", "Extrait Kbis"),
        ("URSSAF", "Attestation de vigilance URSSAF"),
        ("FISCAL", "Attestation de régularité fiscale"),
        ("RCPRO", "Attestation d'assurance RC Pro"),
        ("QUALIOPI", "Certificat Qualiopi"),
        ("INRS", "Habilitation INRS"),
        ("RIB", "RIB"),
        ("NDA", "Déclaration d'activité OF"),
        ("AUTRE", "Autre"),
    ]

    type = models.CharField(max_length=20, choices=TYPES)
    libelle = models.CharField(max_length=200, blank=True)
    fichier = models.FileField(upload_to="pieces/", blank=True)
    date_emission = models.DateField(null=True, blank=True)
    date_expiration = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["date_expiration"]
        verbose_name = "Pièce administrative"
        verbose_name_plural = "Pièces administratives"

    def __str__(self):
        return self.libelle or self.get_type_display()

    @property
    def jours_avant_expiration(self):
        if not self.date_expiration:
            return None
        return (self.date_expiration - timezone.localdate()).days


# ---------------------------------------------------------------------------
# Veille
# ---------------------------------------------------------------------------


class ProfilVeille(models.Model):
    """Paramétrage d'une veille : ce que l'on cherche et à qui on l'envoie."""

    nom = models.CharField(max_length=100)
    actif = models.BooleanField(default=True)
    mots_cles_forts = models.TextField(
        "Mots-clés forts",
        blank=True,
        help_text="Spécifiques au métier : suffisent seuls (ex. sauveteur secouriste). Un par ligne, "
        "sans accents ni casse ; « * » en fin de mot = troncature.",
    )
    mots_cles = models.TextField(
        "Mots-clés génériques",
        blank=True,
        help_text="Comptent seulement si un mot de contexte est présent (ex. incendie + formation). Un par ligne.",
    )
    mots_contexte = models.TextField(
        "Mots de contexte",
        blank=True,
        help_text="Cherchés dans l'objet de l'avis (ex. formation, sensibilisation). Un par ligne.",
    )
    mots_contexte_texte = models.TextField(
        "Mots de contexte (texte complet)",
        blank=True,
        help_text="Cherchés dans tout le texte de l'avis : termes sans ambiguïté (ex. stagiaire*). Un par ligne.",
    )
    mots_cles_exclus = models.TextField(blank=True, help_text="Un par ligne.")
    cpv = models.TextField(
        "Codes CPV",
        blank=True,
        help_text="Un préfixe CPV par ligne (ex. 8055 couvre 80550000).",
    )
    departements = models.CharField(
        max_length=500,
        blank=True,
        help_text="Codes séparés par des virgules. Vide = national.",
    )
    montant_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    montant_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    seuil_digest = models.PositiveIntegerField(
        "Score minimum pour le digest", default=50
    )
    seuil_alerte = models.PositiveIntegerField(
        "Score déclenchant une alerte immédiate", default=80
    )
    destinataires = models.TextField(blank=True, help_text="E-mails, un par ligne.")

    class Meta:
        verbose_name = "Profil de veille"
        verbose_name_plural = "Profils de veille"

    def __str__(self):
        return self.nom

    @staticmethod
    def _lines(text):
        return [l.strip() for l in (text or "").splitlines() if l.strip()]

    @property
    def liste_mots_cles(self):
        return self._lines(self.mots_cles)

    @property
    def liste_forts(self):
        return self._lines(self.mots_cles_forts)

    @property
    def liste_contexte(self):
        return self._lines(self.mots_contexte)

    @property
    def liste_contexte_texte(self):
        return self._lines(self.mots_contexte_texte)

    @property
    def liste_exclus(self):
        return self._lines(self.mots_cles_exclus)

    @property
    def liste_cpv(self):
        return [c.replace(" ", "") for c in self._lines(self.cpv)]

    @property
    def liste_departements(self):
        return [d.strip() for d in self.departements.split(",") if d.strip()]

    @property
    def liste_destinataires(self):
        return self._lines(self.destinataires)


class AvisMarche(models.Model):
    SOURCES = [
        ("BOAMP", "BOAMP"),
        ("TED", "TED (JOUE)"),
        ("PROFIL", "Profil acheteur"),
        ("PRIVE", "Consultation privée"),
        ("MANUEL", "Saisie manuelle"),
    ]
    NATURES = [
        ("AVIS", "Avis de marché"),
        ("RECTIFICATIF", "Rectificatif"),
        ("ATTRIBUTION", "Avis d'attribution"),
        ("AUTRE", "Autre"),
    ]
    STATUTS = [
        ("DETECTE", "Détecté"),
        ("A_QUALIFIER", "À qualifier"),
        ("GO", "Go"),
        ("NO_GO", "No-Go"),
        ("REDACTION", "En rédaction"),
        ("DEPOSE", "Déposé"),
        ("GAGNE", "Gagné"),
        ("PERDU", "Perdu"),
        ("SANS_SUITE", "Sans suite"),
        ("ECARTE", "Écarté (hors cible)"),
    ]
    RECOMMANDATIONS = [("GO", "Go"), ("A_ETUDIER", "À étudier"), ("NO_GO", "No-Go")]

    source = models.CharField(max_length=10, choices=SOURCES)
    source_id = models.CharField(max_length=100)
    procedure_id = models.CharField(
        max_length=100,
        blank=True,
        db_index=True,
        help_text="Identifiant de procédure (eForms ContractFolderID) : sert au dédoublonnage BOAMP/TED.",
    )
    url = models.URLField(max_length=500, blank=True)

    nature = models.CharField(max_length=15, choices=NATURES, default="AVIS")
    objet = models.TextField()
    acheteur = models.CharField(max_length=300, blank=True)
    acheteur_type = models.CharField(
        max_length=20, blank=True, help_text="public / privé"
    )
    departements = models.CharField(max_length=200, blank=True)
    lieu_execution = models.CharField(max_length=300, blank=True)
    date_publication = models.DateField(null=True, blank=True)
    date_limite = models.DateTimeField(null=True, blank=True)
    type_marche = models.CharField(max_length=50, blank=True)
    procedure = models.CharField(max_length=100, blank=True)
    cpv = models.CharField(max_length=500, blank=True, help_text="Codes séparés par des virgules")
    montant_estime = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    texte = models.TextField(blank=True, help_text="Texte utile de l'avis (description, lots…)")
    brut = models.JSONField(null=True, blank=True)

    # Pré-filtre (règles)
    prefiltre_ok = models.BooleanField(default=False)
    prefiltre_motif = models.CharField(max_length=300, blank=True)
    mots_cles_trouves = models.CharField(max_length=500, blank=True)
    profil = models.ForeignKey(
        ProfilVeille, null=True, blank=True, on_delete=models.SET_NULL
    )

    # Score IA
    score = models.PositiveSmallIntegerField(null=True, blank=True)
    recommandation = models.CharField(max_length=10, choices=RECOMMANDATIONS, blank=True)
    resume = models.TextField(blank=True)
    score_details = models.JSONField(null=True, blank=True)
    score_modele = models.CharField(max_length=50, blank=True)
    score_le = models.DateTimeField(null=True, blank=True)
    alerte_envoyee = models.BooleanField(default=False)
    digest_envoye = models.BooleanField(default=False)

    # Pipeline
    statut = models.CharField(max_length=15, choices=STATUTS, default="DETECTE")
    responsable = models.CharField("Responsable", max_length=100, blank=True)
    decision_motif = models.TextField("Motif de la décision", blank=True)
    notes = models.TextField(blank=True)

    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["source", "source_id"], name="avis_unique_par_source")
        ]
        ordering = ["-date_publication", "-id"]
        verbose_name = "Avis de marché"
        verbose_name_plural = "Avis de marché"

    def __str__(self):
        return f"[{self.source} {self.source_id}] {self.objet[:80]}"

    @property
    def jours_restants(self):
        if not self.date_limite:
            return None
        return (self.date_limite.date() - timezone.localdate()).days

    @property
    def liste_cpv(self):
        return [c for c in self.cpv.split(",") if c]


class Collecte(models.Model):
    """Journal des collectes, pour reprendre là où on s'est arrêté."""

    source = models.CharField(max_length=10)
    debut = models.DateTimeField(default=timezone.now)
    fin = models.DateTimeField(null=True, blank=True)
    depuis = models.DateField(null=True, blank=True)
    nb_lus = models.PositiveIntegerField(default=0)
    nb_nouveaux = models.PositiveIntegerField(default=0)
    nb_retenus = models.PositiveIntegerField(default=0)
    erreur = models.TextField(blank=True)

    class Meta:
        ordering = ["-debut"]

    def __str__(self):
        return f"{self.source} {self.debut:%d/%m %H:%M} ({self.nb_nouveaux} nouveaux)"
