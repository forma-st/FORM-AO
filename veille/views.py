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
