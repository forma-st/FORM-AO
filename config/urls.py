from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from veille import views

urlpatterns = [
    path("", views.tableau_de_bord, name="tableau"),
    path("avis/<int:pk>/", views.detail, name="detail"),
    path("avis/ajouter/", views.ajouter, name="ajouter"),
    path("pipeline/", views.pipeline, name="pipeline"),
    path("admin/", admin.site.urls),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
