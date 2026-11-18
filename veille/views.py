from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import AvisMarche, Collecte, Entreprise, ProfilVeille
from .services import prefiltre, scoring
from .services.digest import pieces_a_renouveler

COLONNES_PIPELINE = ["A_QUALIFIER", "GO", "REDACTION", "DEPOSE", "GAGNE", "PERDU"]


@login_required
def tableau_de_bord(request):
    qs = AvisMarche.objects.filter(prefiltre_ok=True).select_related("profil")
    ouverts = request.GET.get("ouverts", "1") == "1"
    if ouverts:
        qs = qs.filter(Q(date_limite__isnull=True) | Q(date_limite__gte=timezone.now()))
    reco = request.GET.get("reco")
    if reco:
        qs = qs.filter(recommandation=reco)
    statut = request.GET.get("statut")
    if statut:
        qs = qs.filter(statut=statut)
    else:
        qs = qs.exclude(statut__in=["NO_GO", "ECARTE"])
    q = request.GET.get("q")
    if q:
        qs = qs.filter(Q(objet__icontains=q) | Q(acheteur__icontains=q) | Q(texte__icontains=q))
    qs = qs.order_by("-score", "date_limite")

    stats = AvisMarche.objects.aggregate(
        total=Count("id"),
        retenus=Count("id", filter=Q(prefiltre_ok=True)),
        go=Count("id", filter=Q(recommandation="GO")),
    )
    return render(
        request,
        "veille/tableau.html",
        {
            "avis": qs[:300],
            "stats": stats,
            "derniere_collecte": Collecte.objects.first(),
            "pieces": pieces_a_renouveler(),
            "statuts": AvisMarche.STATUTS,
            "filtres": request.GET,
            "entreprise": Entreprise.get(),
        },
    )


class SuiviForm(forms.ModelForm):
    class Meta:
        model = AvisMarche
        fields = ["statut", "responsable", "decision_motif", "notes"]
        widgets = {
            "decision_motif": forms.Textarea(attrs={"rows": 2}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }


@login_required
def detail(request, pk):
    avis = get_object_or_404(AvisMarche, pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "scorer":
            try:
                scoring.scorer(avis)
                messages.success(request, f"Avis scoré : {avis.score}/100.")
            except scoring.ScoringIndisponible as e:
                r = scoring.score_regles(avis)
                scoring.enregistrer(avis, r, modele="règles")
                messages.warning(request, f"{e} Score par règles appliqué.")
            return redirect("detail", pk=pk)
        if action == "repecher":
            avis.prefiltre_ok = True
            avis.prefiltre_motif = "repêché manuellement"
            avis.profil = ProfilVeille.objects.filter(actif=True).first()
            if avis.statut == "ECARTE":
                avis.statut = "DETECTE"
            avis.save()
            return redirect("detail", pk=pk)
        form = SuiviForm(request.POST, instance=avis)
        if form.is_valid():
            form.save()
            messages.success(request, "Suivi enregistré.")
            return redirect("detail", pk=pk)
    else:
        form = SuiviForm(instance=avis)
    return render(request, "veille/detail.html", {"a": avis, "form": form, "d": avis.score_details or {}})


@login_required
def pipeline(request):
    colonnes = []
    libelles = dict(AvisMarche.STATUTS)
    for s in COLONNES_PIPELINE:
        colonnes.append(
            (libelles[s], AvisMarche.objects.filter(statut=s).order_by("date_limite")[:100])
        )
    return render(request, "veille/pipeline.html", {"colonnes": colonnes})


class AvisPriveForm(forms.ModelForm):
    class Meta:
        model = AvisMarche
        fields = ["objet", "acheteur", "date_limite", "lieu_execution", "montant_estime", "url", "texte"]
        widgets = {
            "date_limite": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "texte": forms.Textarea(attrs={"rows": 12}),
        }
        labels = {"texte": "Texte de la consultation (copier-coller du cahier des charges ou du mail)"}


@login_required
def ajouter(request):
    """Saisie d'une consultation privée ou d'un avis repéré ailleurs."""
    if request.method == "POST":
        form = AvisPriveForm(request.POST)
        if form.is_valid():
            avis = form.save(commit=False)
            avis.source = "PRIVE"
            avis.source_id = f"PRIVE-{timezone.now():%Y%m%d%H%M%S}"
            avis.acheteur_type = "privé"
            avis.type_marche = "SERVICES"
            avis.date_publication = timezone.localdate()
            prefiltre.appliquer(avis, list(ProfilVeille.objects.filter(actif=True)))
            avis.prefiltre_ok = True  # saisi à la main : on le garde toujours
            if avis.statut == "ECARTE":
                avis.statut = "DETECTE"
            avis.save()
            messages.success(request, "Consultation ajoutée. Lancez le score depuis sa fiche.")
            return redirect("detail", pk=avis.pk)
    else:
        form = AvisPriveForm()
    return render(request, "veille/ajouter.html", {"form": form})


# ---------------------------------------------------------------------------
# Phase 2 : coffre-fort et pièces de candidature
# ---------------------------------------------------------------------------

from django.http import Http404, HttpResponse  # noqa: E402
from django.views.decorators.http import require_POST  # noqa: E402

from .models import AnalyseDCE, DocumentDCE, Memoire, PieceAdministrative  # noqa: E402
from .services import dce as dce_service  # noqa: E402
from .services import documents  # noqa: E402
from .services import memoire as memoire_service  # noqa: E402
from .services.taches import lancer  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _telecharger(contenu: bytes, nom: str, type_mime: str) -> HttpResponse:
    r = HttpResponse(contenu, content_type=type_mime)
    r["Content-Disposition"] = f'attachment; filename="{nom}"'
    return r


class PieceForm(forms.ModelForm):
    class Meta:
        model = PieceAdministrative
        fields = ["type", "libelle", "fichier", "date_emission", "date_expiration"]
        widgets = {
            "date_emission": forms.DateInput(attrs={"type": "date"}),
            "date_expiration": forms.DateInput(attrs={"type": "date"}),
        }


@login_required
def coffre_fort(request):
    suivant = request.GET.get("suivant", "")
    if not suivant.startswith("/") or suivant.startswith("//"):
        suivant = ""
    if request.method == "POST":
        form = PieceForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Pièce ajoutée au coffre-fort : elle sera jointe aux prochains dossiers.")
            return redirect(suivant or "coffre_fort")
    else:
        form = PieceForm(initial={"type": request.GET.get("type", "")})
    pieces = PieceAdministrative.objects.all().order_by("type", "-date_expiration")
    presentes = set(pieces.exclude(fichier="").values_list("type", flat=True))
    manquantes = [lib for t, lib in documents.PIECES_ATTENDUES if t not in presentes]
    return render(request, "veille/coffre_fort.html", {"pieces": pieces, "form": form, "manquantes": manquantes, "suivant": suivant})


@login_required
@require_POST
def supprimer_piece(request, pk):
    get_object_or_404(PieceAdministrative, pk=pk).delete()
    messages.success(request, "Pièce supprimée.")
    return redirect("coffre_fort")


@login_required
def document_genere(request, pk, cle):
    a = get_object_or_404(AvisMarche, pk=pk)
    if cle not in documents.GENERATEURS:
        raise Http404
    nom, fn = documents.GENERATEURS[cle]
    try:
        return _telecharger(fn(a), nom, DOCX)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect("reponse", pk=pk)


@login_required
def dossier_zip(request, pk):
    a = get_object_or_404(AvisMarche, pk=pk)
    m = a.memoires.filter(statut="OK").first()
    memoire_docx = None
    if m and m.fichier:
        with m.fichier.open("rb") as f:
            memoire_docx = f.read()
    try:
        contenu = documents.dossier_zip(a, memoire_docx)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect("reponse", pk=pk)
    return _telecharger(contenu, f"Dossier_FORMAST_{a.pk}.zip", "application/zip")


# ---------------------------------------------------------------------------
# Phase 3 : DCE, analyse, mémoire
# ---------------------------------------------------------------------------


class MemoireForm(forms.Form):
    consignes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Ex. insister sur l'UMFI, proposer une session pilote, 2 intervenants…"}),
        label="Consignes pour la rédaction (facultatif)",
    )


@login_required
def reponse(request, pk):
    a = get_object_or_404(AvisMarche, pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "deposer":
            ajoutes = dce_service.ajouter_fichiers(a, request.FILES.getlist("fichiers"))
            messages.success(request, f"{len(ajoutes)} document(s) ajouté(s) au DCE.")
        elif action == "lots":
            a.lots_vises = request.POST.get("lots_vises", "")[:200]
            a.save(update_fields=["lots_vises"])
            messages.success(request, "Lots enregistrés.")
        elif action == "analyser":
            AnalyseDCE.objects.update_or_create(avis=a, defaults={"statut": "EN_COURS", "erreur": ""})
            lancer(dce_service.analyser, a)
            messages.success(request, "Analyse lancée : comptez 1 à 3 minutes, la page se met à jour seule.")
        elif action == "rediger":
            form = MemoireForm(request.POST)
            consignes = form.data.get("consignes", "")
            m = Memoire.objects.create(avis=a, consignes=consignes, statut="EN_COURS")
            lancer(memoire_service.rediger, a, consignes, None, m)
            messages.success(request, "Rédaction lancée : comptez 3 à 8 minutes, la page se met à jour seule.")
        return redirect("reponse", pk=pk)

    analyse = getattr(a, "analyse", None)
    memoires = a.memoires.all()
    en_cours = (analyse and analyse.statut == "EN_COURS") or memoires.filter(statut="EN_COURS").exists()
    return render(
        request,
        "veille/reponse.html",
        {
            "a": a,
            "documents_dce": a.documents.all(),
            "analyse": analyse,
            "r": (analyse.resultat or {}) if analyse else {},
            "pieces_demandees": dce_service.rapprocher_pieces(analyse) if analyse and analyse.statut == "OK" else [],
            "controles": documents.controler_pieces(a),
            "memoires": memoires,
            "form_memoire": MemoireForm(),
            "en_cours": en_cours,
            "generateurs": [(k, documents.GENERATEURS[k][0]) for k in documents.generateurs_pour(a)],
            "profil_manquants": [c["libelle"] for c in annuaire.completude(_Entreprise.get()) if c["obligatoire"] and not c["rempli"]],
        },
    )


@login_required
@require_POST
def supprimer_document(request, pk):
    d = get_object_or_404(DocumentDCE, pk=pk)
    avis_pk = d.avis_id
    d.fichier.delete(save=False)
    d.delete()
    return redirect("reponse", pk=avis_pk)


@login_required
def grille(request, pk):
    a = get_object_or_404(AvisMarche, pk=pk)
    return _telecharger(memoire_service.grille_conformite(a), f"Grille_conformite_{a.pk}.xlsx", XLSX)


@login_required
def memoire_docx(request, pk):
    m = get_object_or_404(Memoire, pk=pk, statut="OK")
    return _telecharger(memoire_service.vers_docx(m), f"Memoire_technique_FORMAST_{m.avis_id}.docx", DOCX)


@login_required
def memoire_voir(request, pk):
    m = get_object_or_404(Memoire, pk=pk)
    return render(request, "veille/memoire.html", {"m": m})


@login_required
def fichier_protege(request, chemin):
    """Fichiers déposés (Kbis, RIB, CV, DCE…) : servis uniquement aux utilisateurs connectés."""
    from pathlib import Path

    from django.conf import settings
    from django.http import FileResponse

    racine = Path(settings.MEDIA_ROOT).resolve()
    cible = (racine / chemin).resolve()
    if racine not in cible.parents or not cible.is_file():
        raise Http404
    return FileResponse(cible.open("rb"), as_attachment=False, filename=cible.name)


# ---------------------------------------------------------------------------
# Profil entreprise : compléter, mettre à jour depuis l'annuaire
# ---------------------------------------------------------------------------

from .models import Entreprise as _Entreprise  # noqa: E402
from .services import annuaire  # noqa: E402


class ProfilForm(forms.ModelForm):
    class Meta:
        model = _Entreprise
        fields = [
            "email", "telephone", "site_web", "capital", "effectif", "ca_n1", "ca_n2", "ca_n3",
            "qualiopi_expiration", "habilitation_inrs_sst_expiration", "etablissements",
        ]
        widgets = {
            "qualiopi_expiration": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "habilitation_inrs_sst_expiration": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "etablissements": forms.Textarea(attrs={"rows": 2}),
        }


@login_required
def profil(request):
    e = _Entreprise.get()
    if not e:
        messages.error(request, "Profil entreprise absent : lancez « manage.py charger_profil ».")
        return redirect("tableau")
    if request.method == "POST" and request.POST.get("action") == "annuaire":
        try:
            modifies = annuaire.mettre_a_jour(e)
            messages.success(
                request,
                f"Fiche mise à jour depuis l'annuaire officiel ({', '.join(modifies)})." if modifies
                else "Fiche déjà à jour avec l'annuaire officiel.",
            )
        except Exception as ex:  # réseau, SIREN introuvable…
            messages.error(request, f"Mise à jour impossible : {ex}")
        return redirect("profil")
    form = ProfilForm(request.POST or None, instance=e)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profil enregistré : les prochains documents générés l'intègrent automatiquement.")
        suivant = request.GET.get("suivant", "")
        return redirect(suivant if suivant.startswith("/") and not suivant.startswith("//") else "profil")
    return render(request, "veille/profil.html", {"e": e, "form": form, "completude": annuaire.completude(e)})
