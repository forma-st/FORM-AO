from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from veille import views

urlpatterns = [
    path("", views.tableau_de_bord, name="tableau"),
    path("collecter/", views.collecter_maintenant, name="collecter"),
    path("avis/<int:pk>/", views.detail, name="detail"),
    path("avis/<int:pk>/decider/", views.decider, name="decider"),
    path("avis/<int:pk>/statut/", views.changer_statut, name="changer_statut"),
    path("avis/ajouter/", views.ajouter, name="ajouter"),
    path("pipeline/", views.pipeline, name="pipeline"),
    path("coffre-fort/", views.coffre_fort, name="coffre_fort"),
    path("coffre-fort/<int:pk>/supprimer/", views.supprimer_piece, name="supprimer_piece"),
    path("profil/", views.profil, name="profil"),
    path("avis/<int:pk>/reponse/", views.reponse, name="reponse"),
    path("avis/<int:pk>/document/<str:cle>/", views.document_genere, name="document_genere"),
    path("avis/<int:pk>/dossier.zip", views.dossier_zip, name="dossier_zip"),
    path("avis/<int:pk>/grille.xlsx", views.grille, name="grille"),
    path("dce/<int:pk>/supprimer/", views.supprimer_document, name="supprimer_document"),
    path("memoire/<int:pk>/", views.memoire_voir, name="memoire_voir"),
    path("memoire/<int:pk>/word/", views.memoire_docx, name="memoire_docx"),
    path("connexion/", auth_views.LoginView.as_view(template_name="veille/connexion.html"), name="connexion"),
    path("deconnexion/", auth_views.LogoutView.as_view(next_page="connexion"), name="deconnexion"),
    path("admin/", admin.site.urls),
    path("media/<path:chemin>", views.fichier_protege, name="fichier_protege"),
]
