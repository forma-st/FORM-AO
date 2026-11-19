from django.contrib import admin

from .models import (
    AnalyseDCE,
    BlocContenu,
    DocumentDCE,
    Memoire,
    AvisMarche,
    Collecte,
    Entreprise,
    Formateur,
    PieceAdministrative,
    Prestation,
    ProfilVeille,
    Reference,
)

admin.site.site_header = "FORM'AO – réglages avancés"
admin.site.site_title = "FORM'AO"


@admin.register(Entreprise)
class EntrepriseAdmin(admin.ModelAdmin):
    fieldsets = [
        ("Identité", {"fields": ["raison_sociale", "nom_commercial", "forme_juridique", "siret",
                                  "tva_intracommunautaire", "code_naf", "date_creation", "capital", "etablissements",
                                  "numero_declaration_activite", "adresse", "code_postal", "ville",
                                  "representant_nom", "representant_qualite", "email", "telephone", "site_web"]}),
        ("Certifications", {"fields": ["qualiopi", "qualiopi_expiration", "habilitation_inrs_sst",
                                        "habilitation_inrs_sst_expiration", "autres_certifications"]}),
        ("Chiffres", {"fields": ["effectif", "tranche_effectif", "ca_n1", "ca_n2", "ca_n3"]}),
        ("Positionnement", {"fields": ["zone_intervention", "presentation", "points_forts"]}),
    ]

    def has_add_permission(self, request):
        return not Entreprise.objects.exists()


@admin.register(Prestation)
class PrestationAdmin(admin.ModelAdmin):
    list_display = ["intitule", "categorie", "duree", "groupe_min", "groupe_max", "prix_intra_ht", "prix_inter_ht", "actif"]
    list_filter = ["categorie", "actif"]
    list_editable = ["prix_intra_ht", "prix_inter_ht", "actif"]
    search_fields = ["intitule", "description"]


@admin.register(Formateur)
class FormateurAdmin(admin.ModelAdmin):
    list_display = ["__str__", "fonction", "domaines", "actif"]


@admin.register(Reference)
class ReferenceAdmin(admin.ModelAdmin):
    list_display = ["client", "objet", "public", "date_debut", "date_fin", "citable"]
    list_filter = ["public", "citable"]


@admin.register(PieceAdministrative)
class PieceAdmin(admin.ModelAdmin):
    list_display = ["__str__", "type", "date_emission", "date_expiration", "jours_avant_expiration"]
    list_filter = ["type"]


@admin.register(ProfilVeille)
class ProfilVeilleAdmin(admin.ModelAdmin):
    list_display = ["nom", "actif", "seuil_digest", "seuil_alerte"]


@admin.register(AvisMarche)
class AvisMarcheAdmin(admin.ModelAdmin):
    list_display = ["source_id", "objet_court", "acheteur", "score", "recommandation", "statut", "date_limite", "prefiltre_ok"]
    list_filter = ["source", "nature", "prefiltre_ok", "recommandation", "statut"]
    search_fields = ["objet", "acheteur", "texte", "source_id"]
    readonly_fields = ["brut", "score_details", "cree_le", "modifie_le"]
    date_hierarchy = "date_publication"

    @admin.display(description="Objet")
    def objet_court(self, obj):
        return obj.objet[:90]


@admin.register(Collecte)
class CollecteAdmin(admin.ModelAdmin):
    list_display = ["source", "debut", "fin", "depuis", "nb_lus", "nb_nouveaux", "nb_retenus", "erreur"]


@admin.register(BlocContenu)
class BlocContenuAdmin(admin.ModelAdmin):
    list_display = ["titre", "categorie", "source", "actif", "modifie_le"]
    list_filter = ["categorie", "actif"]
    search_fields = ["titre", "texte"]


@admin.register(DocumentDCE)
class DocumentDCEAdmin(admin.ModelAdmin):
    list_display = ["nom", "type", "avis", "nb_pages", "cree_le"]
    list_filter = ["type"]


@admin.register(AnalyseDCE)
class AnalyseDCEAdmin(admin.ModelAdmin):
    list_display = ["avis", "statut", "modele", "cree_le"]


@admin.register(Memoire)
class MemoireAdmin(admin.ModelAdmin):
    list_display = ["__str__", "statut", "modele", "cree_le"]
