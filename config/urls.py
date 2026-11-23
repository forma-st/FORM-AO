from django.contrib import admin
from django.urls import include, path

from veille import views

urlpatterns = [
    path("", views.tableau_de_bord, name="tableau"),
    path("avis/<int:pk>/", views.detail, name="detail"),
    path("avis/ajouter/", views.ajouter, name="ajouter"),
    path("pipeline/", views.pipeline, name="pipeline"),
    path("coffre-fort/", views.coffre_fort, name="coffre_fort"),
    path("profil/", views.profil, name="profil"),
    path("coffre-fort/<int:pk>/supprimer/", views.supprimer_piece, name="supprimer_piece"),
    path("avis/<int:pk>/reponse/", views.reponse, name="reponse"),
    path("avis/<int:pk>/document/<str:cle>/", views.document_genere, name="document_genere"),
    path("avis/<int:pk>/dossier.zip", views.dossier_zip, name="dossier_zip"),
    path("avis/<int:pk>/grille.xlsx", views.grille, name="grille"),
    path("dce/<int:pk>/supprimer/", views.supprimer_document, name="supprimer_document"),
    path("memoire/<int:pk>/", views.memoire_voir, name="memoire_voir"),
    path("memoire/<int:pk>/word/", views.memoire_docx, name="memoire_docx"),
    path("prospection/", include("prospection.urls")),
    path("admin/", admin.site.urls),
    path("media/<path:chemin>", views.fichier_protege, name="fichier_protege"),
]
