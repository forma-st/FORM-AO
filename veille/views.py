from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.management import call_command
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .models import (
    AnalyseDCE,
    AvisMarche,
    Collecte,
    DocumentDCE,
    Entreprise,
    Memoire,
    Parametres,
    PieceAdministrative,
    PreferencesUtilisateur,
    ProfilVeille,
)
from .services import accueil as accueil_service
from .services import annuaire, couts, documents, notifications, planification, prefiltre, scoring
from .services import dce as dce_service
from .services import memoire as memoire_service
from .services import recuperation
from .services.digest import echeances_proches, pieces_a_renouveler
from .services.taches import lancer

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

COLONNES_PIPELINE = ["A_QUALIFIER", "GO", "REDACTION", "DEPOSE", "GAGNE", "PERDU"]

# Onglets du tableau : (clé, libellé, filtre sur les statuts)
ONGLETS = [
    ("a_trier", "À trier", ["DETECTE", "A_QUALIFIER"]),
    ("go", "Go", ["GO"]),
    ("en_cours", "En cours", ["REDACTION", "DEPOSE"]),
    ("resultats", "Résultats", ["GAGNE", "PERDU", "SANS_SUITE"]),
    ("ecartes", "No-Go", ["NO_GO"]),
]


def _retour(request, defaut):
    """Revient à la page d'origine (paramètre « suivant »), sans redirection externe."""
    suivant = request.POST.get("suivant") or request.GET.get("suivant") or ""
    if suivant and url_has_allowed_host_and_scheme(suivant, allowed_hosts={request.get_host()}):
        return redirect(suivant)
    return redirect(defaut)


def _ouverts(qs):
    return qs.filter(Q(date_limite__isnull=True) | Q(date_limite__gte=timezone.now()))


def _collecte_en_cours():
    return Collecte.objects.filter(fin__isnull=True, debut__gte=timezone.now() - timezone.timedelta(minutes=30)).exists()


# ---------------------------------------------------------------------------
# Tableau de tri
# ---------------------------------------------------------------------------


JOURS_FILTRE = 7  # onglet « Écartés par le filtre » : avis publiés ces derniers jours


def _ecartes_par_filtre():
    depuis = timezone.localdate() - timezone.timedelta(days=JOURS_FILTRE - 1)
    return _ouverts(AvisMarche.objects.filter(prefiltre_ok=False, date_publication__gte=depuis, nature__in=["AVIS", "AUTRE"]))


@login_required
def tableau_de_bord(request):
    onglet = request.GET.get("onglet", "a_trier")
    base = AvisMarche.objects.filter(prefiltre_ok=True)
    q = request.GET.get("q", "").strip()

    if onglet == "filtre" and not q:
        qs = _ecartes_par_filtre().order_by("-date_publication", "date_limite")
    else:
        statuts = dict((k, s) for k, _, s in ONGLETS).get(onglet, ONGLETS[0][2])
        qs = base.filter(statut__in=statuts).select_related("profil")
        if q:
            # la recherche porte sur tous les avis retenus, quel que soit l'onglet
            qs = base.filter(Q(objet__icontains=q) | Q(acheteur__icontains=q) | Q(texte__icontains=q))
        elif onglet in ("a_trier", "go"):
            qs = _ouverts(qs)
        if onglet == "a_trier" and not q:
            qs = qs.order_by("-score", "date_limite")
        else:
            qs = qs.order_by("date_limite", "-score")

    compteurs = {}
    for cle, _, sts in ONGLETS:
        c = base.filter(statut__in=sts)
        compteurs[cle] = (_ouverts(c) if cle in ("a_trier", "go") else c).count()
    onglets = [(k, l, compteurs[k]) for k, l, _ in ONGLETS] + [("filtre", "Écartés par le filtre", _ecartes_par_filtre().count())]

    a_renoter = scoring.notes_par_regles().count() if scoring.ia_disponible() else 0
    hier = timezone.now() - timezone.timedelta(days=1)
    return render(
        request,
        "veille/tableau.html",
        {
            "avis": qs[:300],
            "onglets": onglets,
            "onglet": onglet,
            "jours_filtre": JOURS_FILTRE,
            "a_renoter": a_renoter,
            "cout_renoter": couts.estimer_euros("SCORE", nombre=a_renoter) if a_renoter else 0,
            "q": q,
            "nouveaux": base.filter(cree_le__gte=hier).count(),
            "echeances": echeances_proches(),
            "pieces": pieces_a_renouveler(),
            "derniere_collecte": Collecte.objects.filter(fin__isnull=False).first(),
            "collecte_en_cours": _collecte_en_cours(),
            "total": AvisMarche.objects.count(),
            "no_go_recommandes": _ouverts(base.filter(statut__in=["DETECTE", "A_QUALIFIER"], recommandation="NO_GO"))
            .exclude(score_modele="règles").count(),
        },
    )


def _collecter_et_scorer():
    call_command("collecter")
    call_command("scorer")


@login_required
@require_POST
def collecter_maintenant(request):
    if _collecte_en_cours():
        messages.info(request, "Une collecte est déjà en cours.")
    else:
        lancer(_collecter_et_scorer)
        messages.success(request, "Collecte lancée : les nouveaux avis arrivent d'ici quelques minutes.")
    return redirect("tableau")


@login_required
@require_POST
def renoter_regles(request):
    """Fait noter par l'IA, en arrière-plan, les avis notés par règles (IA absente ou budget atteint)."""
    n = scoring.notes_par_regles().count()
    if not scoring.ia_disponible():
        messages.error(request, "IA inactive : ajoutez la clé API dans le fichier .env.")
    elif couts.budget_atteint():
        messages.error(request, scoring.MESSAGE_BUDGET)
    elif not n:
        messages.info(request, "Aucun avis à re-noter.")
    else:
        lancer(call_command, "scorer", refaire_regles=True)
        messages.success(request, f"{n} avis en cours de notation par l'IA : rechargez la page dans une minute ou deux.")
    return _retour(request, "tableau")


@login_required
@require_POST
def decider(request, pk):
    """Tri en un clic : Go, No-Go (avec motif) ou retour « à trier »."""
    a = get_object_or_404(AvisMarche, pk=pk)
    decision = request.POST.get("decision")
    if decision not in ("GO", "NO_GO", "A_QUALIFIER") and not (
        request.POST.get("annulation") and decision in dict(AvisMarche.STATUTS)
    ):
        raise Http404
    precedent = a.statut
    a.statut = decision
    motif = request.POST.get("motif", "").strip()
    if motif:
        a.decision_motif = motif
    a.save(update_fields=["statut", "decision_motif", "modifie_le"])
    libelle = {"GO": "Go", "NO_GO": "No-Go", "A_QUALIFIER": "à trier"}[decision]
    texte = f"« {a.objet[:70]} » classé {libelle}."
    if request.POST.get("annulation"):
        texte = f"Décision annulée : « {a.objet[:70]} » revient à l'étape « {a.get_statut_display()} »."
    # « annuler:<pk>:<statut précédent> » permet d'afficher un bouton Annuler dans le message
    tags = "" if request.POST.get("annulation") else f"annuler:{a.pk}:{precedent}"
    if decision == "GO" and _lancer_recuperation(a, auto=True):
        texte += " Récupération du dossier de consultation lancée."
    messages.success(request, texte, extra_tags=tags)
    return _retour(request, "tableau")


# ---------------------------------------------------------------------------
# Fiche d'un avis
# ---------------------------------------------------------------------------


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
                messages.success(request, f"Score recalculé : {avis.score}/100.")
            except scoring.ScoringIndisponible as e:
                scoring.enregistrer(avis, scoring.score_regles(avis), modele="règles")
                messages.warning(request, f"{e} Score calculé par règles à la place.")
            return redirect("detail", pk=pk)
        if action == "repecher":
            avis.prefiltre_ok = True
            avis.prefiltre_motif = "repêché manuellement"
            avis.profil = ProfilVeille.objects.filter(actif=True).first()
            if avis.statut == "ECARTE":
                avis.statut = "A_QUALIFIER"
            avis.save()
            try:
                scoring.scorer(avis)
                messages.success(request, f"Avis remis dans la veille et évalué par l'IA : {avis.score}/100.")
            except scoring.ScoringIndisponible as e:
                scoring.enregistrer(avis, scoring.score_regles(avis), modele="règles")
                messages.success(request, f"Avis remis dans la veille ({e} Score provisoire par règles.)")
            except Exception:  # réseau : l'avis est remis, le score pourra être relancé
                messages.success(request, "Avis remis dans la veille. Score à relancer depuis cette page.")
            return redirect("detail", pk=pk)
        form = SuiviForm(request.POST, instance=avis)
        if form.is_valid():
            form.save()
            messages.success(request, "Suivi enregistré.")
            return redirect("detail", pk=pk)
    else:
        form = SuiviForm(instance=avis)
    return render(
        request,
        "veille/detail.html",
        {"a": avis, "form": form, "d": avis.score_details or {}, "page": "evaluation"},
    )


@login_required
def pipeline(request):
    libelles = dict(AvisMarche.STATUTS)
    colonnes = [
        (s, libelles[s], AvisMarche.objects.filter(statut=s).order_by("date_limite")[:100]) for s in COLONNES_PIPELINE
    ]
    return render(request, "veille/pipeline.html", {"colonnes": colonnes, "statuts": AvisMarche.STATUTS})


@login_required
@require_POST
def changer_statut(request, pk):
    a = get_object_or_404(AvisMarche, pk=pk)
    statut = request.POST.get("statut")
    if statut not in dict(AvisMarche.STATUTS):
        raise Http404
    a.statut = statut
    a.save(update_fields=["statut", "modifie_le"])
    return _retour(request, "pipeline")


class AvisPriveForm(forms.ModelForm):
    class Meta:
        model = AvisMarche
        fields = ["objet", "acheteur", "date_limite", "lieu_execution", "montant_estime", "url", "texte"]
        widgets = {
            "date_limite": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "texte": forms.Textarea(attrs={"rows": 10}),
        }
        labels = {
            "objet": "Intitulé de la consultation",
            "acheteur": "Client",
            "date_limite": "Date limite de réponse",
            "lieu_execution": "Lieu(x)",
            "montant_estime": "Budget estimé (€ HT, si connu)",
            "url": "Lien (si la consultation est en ligne)",
            "texte": "Texte de la consultation",
        }
        help_texts = {"texte": "Copiez le mail ou le cahier des charges : l'IA s'en sert pour le score. Vous pourrez joindre les fichiers ensuite."}


@login_required
def ajouter(request):
    """Consultation privée ou avis repéré hors BOAMP/TED."""
    form = AvisPriveForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        avis = form.save(commit=False)
        avis.source = "PRIVE"
        avis.source_id = f"PRIVE-{timezone.now():%Y%m%d%H%M%S}"
        avis.acheteur_type = "privé"
        avis.type_marche = "SERVICES"
        avis.date_publication = timezone.localdate()
        prefiltre.appliquer(avis, list(ProfilVeille.objects.filter(actif=True)))
        avis.prefiltre_ok = True  # saisi à la main : toujours gardé
        avis.statut = "A_QUALIFIER"
        avis.save()
        try:
            scoring.scorer(avis)
        except scoring.ScoringIndisponible:
            scoring.enregistrer(avis, scoring.score_regles(avis), modele="règles")
        except Exception:  # l'avis est créé ; le score pourra être relancé depuis la fiche
            pass
        messages.success(request, "Consultation ajoutée et évaluée.")
        return redirect("detail", pk=avis.pk)
    return render(request, "veille/ajouter.html", {"form": form})


# ---------------------------------------------------------------------------
# Coffre-fort et pièces de candidature
# ---------------------------------------------------------------------------


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
        labels = {"libelle": "Libellé (facultatif)", "date_emission": "Émise le", "date_expiration": "Expire le"}


@login_required
def coffre_fort(request):
    suivant = request.GET.get("suivant", "")
    if request.method == "POST":
        form = PieceForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Pièce ajoutée : elle sera jointe aux prochains dossiers.")
            return _retour(request, "coffre_fort")
    else:
        form = PieceForm(initial={"type": request.GET.get("type", "")})
    pieces = PieceAdministrative.objects.all().order_by("type", "-date_expiration")
    presentes = set(pieces.exclude(fichier="").values_list("type", flat=True))
    attendues = [(t, lib, t in presentes) for t, lib in documents.PIECES_ATTENDUES]
    return render(
        request,
        "veille/coffre_fort.html",
        {"pieces": pieces, "form": form, "attendues": attendues, "suivant": suivant},
    )


@login_required
@require_POST
def supprimer_piece(request, pk):
    p = get_object_or_404(PieceAdministrative, pk=pk)
    p.fichier.delete(save=False)
    p.delete()
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
    try:
        contenu = documents.dossier_zip(a, memoire_service.vers_docx(m) if m else None)
    except ValueError as e:
        messages.error(request, str(e))
        return redirect("reponse", pk=pk)
    return _telecharger(contenu, f"Dossier_FORMAST_{a.pk}.zip", "application/zip")


# ---------------------------------------------------------------------------
# Préparer la réponse : DCE, analyse, mémoire
# ---------------------------------------------------------------------------


def _lancer_recuperation(
    a: AvisMarche, url: str | None = None, analyser: bool = False, forcer: bool = False, auto: bool = False
) -> bool:
    """Lance la récupération du DCE en arrière-plan (au Go, ou depuis la page Réponse)."""
    if a.dce_en_cours or (auto and (a.documents.exists() or a.dce_statut)):
        return False
    AvisMarche.objects.filter(pk=a.pk).update(dce_statut="EN_COURS", dce_message="", dce_recupere_le=timezone.now())
    if analyser:
        lancer(recuperation.recuperer_puis_analyser, a, url, forcer_budget=forcer)
    else:
        lancer(recuperation.recuperer, a, url)
    return True


@login_required
def reponse(request, pk):
    a = get_object_or_404(AvisMarche, pk=pk)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "recuperer":
            url = request.POST.get("url_dce", "").strip()
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            try:
                if url:
                    forms.URLField().clean(url)
            except forms.ValidationError:
                messages.error(request, "Ce lien n'est pas une adresse web valide.")
                return redirect("reponse", pk=pk)
            if url != a.url_dce:
                a.url_dce = url[:500]
                a.save(update_fields=["url_dce"])
            analyser = request.POST.get("analyser") == "1"
            forcer = request.POST.get("depasser_budget") == "1"
            if analyser and couts.budget_atteint() and not forcer:
                analyser = False
                messages.warning(request, "Budget IA atteint : le dossier sera récupéré, sans analyse automatique.")
            if _lancer_recuperation(a, url or None, analyser=analyser, forcer=forcer) or a.dce_en_cours:
                messages.success(request, "Récupération du dossier lancée" + (", puis analyse." if analyser else "."))
        elif action == "deposer":
            ajoutes = dce_service.ajouter_fichiers(a, request.FILES.getlist("fichiers"))
            if ajoutes:
                messages.success(request, f"{len(ajoutes)} document(s) ajouté(s) au dossier de consultation.")
            else:
                messages.error(request, "Aucun fichier lisible : formats acceptés ZIP, PDF, Word, Excel ou texte.")
        elif action == "lots":
            a.lots_vises = request.POST.get("lots_vises", "")[:200]
            a.save(update_fields=["lots_vises"])
            messages.success(request, "Lots enregistrés : ils apparaissent dans le DC1 et le DC2.")
        elif action in ("analyser", "rediger"):
            forcer = request.POST.get("depasser_budget") == "1"
            if couts.budget_atteint() and not forcer:
                messages.error(
                    request,
                    f"{scoring.MESSAGE_BUDGET} Cochez « Lancer quand même » pour dépasser le budget cette fois-ci.",
                )
            elif action == "analyser":
                AnalyseDCE.objects.update_or_create(avis=a, defaults={"statut": "EN_COURS", "erreur": ""})
                lancer(dce_service.analyser, a, forcer_budget=forcer)
                messages.success(request, "Analyse lancée : comptez 1 à 3 minutes.")
            else:
                consignes = request.POST.get("consignes", "")
                m = Memoire.objects.create(avis=a, consignes=consignes, statut="EN_COURS")
                lancer(memoire_service.rediger, a, consignes, None, m, forcer_budget=forcer)
                messages.success(request, "Rédaction lancée : comptez 3 à 8 minutes.")
        return redirect("reponse", pk=pk)

    analyse = getattr(a, "analyse", None)
    memoires = a.memoires.all()
    en_cours = (
        a.dce_en_cours
        or bool(analyse and analyse.statut == "EN_COURS")
        or memoires.filter(statut="EN_COURS").exists()
    )
    documents_dce = a.documents.all()
    lien_propose = a.url_dce or next(iter(recuperation.liens_candidats(a, distant=False)), "")
    controles = documents.controler_pieces(a)
    return render(
        request,
        "veille/reponse.html",
        {
            "a": a,
            "page": "reponse",
            "documents_dce": documents_dce,
            "lien_propose": lien_propose,
            "analyse": analyse,
            "r": (analyse.resultat or {}) if analyse else {},
            "pieces_demandees": dce_service.rapprocher_pieces(analyse) if analyse and analyse.statut == "OK" else [],
            "controles": controles,
            "nb_pieces_ok": sum(c.statut == "ok" for c in controles),
            "memoires": memoires,
            "en_cours": en_cours,
            "generateurs": [(k, documents.GENERATEURS[k][0]) for k in documents.generateurs_pour(a)],
            "profil_manquants": [
                c["libelle"] for c in annuaire.completude(Entreprise.get()) if c["obligatoire"] and not c["rempli"]
            ],
            "cout_analyse": couts.estimer_euros("ANALYSE", a),
            "cout_memoire": couts.estimer_euros("MEMOIRE", a),
            "cout_avis": couts.en_euros(sum(c.cout_usd for c in a.consommations.all())),
        },
    )


@login_required
@require_POST
def supprimer_document(request, pk):
    d = get_object_or_404(DocumentDCE, pk=pk)
    avis_pk = d.avis_id
    d.fichier.delete(save=False)
    d.delete()
    messages.success(request, "Document retiré.")
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
    if request.method == "POST" and m.statut == "OK":
        m.contenu = request.POST.get("contenu", m.contenu)
        m.save(update_fields=["contenu"])
        messages.success(request, "Mémoire enregistré : le fichier Word reprend vos modifications.")
        return redirect("memoire_voir", pk=pk)
    return render(request, "veille/memoire.html", {"m": m, "a": m.avis, "page": "reponse"})


@login_required
def fichier_protege(request, chemin):
    """Fichiers déposés (Kbis, RIB, CV, DCE…) : servis uniquement aux utilisateurs connectés."""
    racine = Path(settings.MEDIA_ROOT).resolve()
    cible = (racine / chemin).resolve()
    if racine not in cible.parents or not cible.is_file():
        raise Http404
    return FileResponse(cible.open("rb"), as_attachment=False, filename=cible.name)


# ---------------------------------------------------------------------------
# Profil entreprise
# ---------------------------------------------------------------------------


class ProfilForm(forms.ModelForm):
    class Meta:
        model = Entreprise
        fields = [
            "email", "telephone", "site_web", "capital", "effectif", "ca_n1", "ca_n2", "ca_n3",
            "qualiopi_expiration", "habilitation_inrs_sst_expiration", "etablissements",
        ]
        widgets = {
            "qualiopi_expiration": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "habilitation_inrs_sst_expiration": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "etablissements": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {
            "qualiopi_expiration": "Qualiopi valable jusqu'au",
            "habilitation_inrs_sst_expiration": "Habilitation INRS SST valable jusqu'au",
            "ca_n1": "CA dernier exercice (€ HT)",
            "ca_n2": "CA exercice précédent (€ HT)",
            "ca_n3": "CA il y a 3 ans (€ HT)",
        }


@login_required
def profil(request):
    e = Entreprise.get()
    if not e:
        messages.error(request, "Profil entreprise absent : lancez « manage.py charger_profil ».")
        return redirect("tableau")
    if request.method == "POST" and request.POST.get("action") == "annuaire":
        try:
            modifies = annuaire.mettre_a_jour(e)
            messages.success(
                request,
                f"Identité mise à jour depuis l'annuaire officiel ({', '.join(modifies)})." if modifies
                else "Identité déjà à jour avec l'annuaire officiel.",
            )
        except Exception as ex:  # réseau, SIREN introuvable…
            messages.error(request, f"Mise à jour impossible : {ex}")
        return redirect("profil")
    form = ProfilForm(request.POST or None, instance=e)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profil enregistré : les prochains documents l'intègrent automatiquement.")
        return _retour(request, "profil")
    return render(request, "veille/profil.html", {"e": e, "form": form, "completude": annuaire.completude(e)})


# ---------------------------------------------------------------------------
# Accueil : tableau de bord personnalisable
# ---------------------------------------------------------------------------


@login_required
def accueil(request):
    return render(
        request,
        "veille/accueil.html",
        {
            "widgets": accueil_service.construire(request.user),
            "tous": accueil_service.preferences(request.user),
            "personnaliser": request.GET.get("personnaliser") == "1",
            "entreprise": Entreprise.get(),
        },
    )


@login_required
@require_POST
def accueil_personnaliser(request):
    if request.POST.get("action") == "reinitialiser":
        accueil_service.reinitialiser(request.user)
        messages.success(request, "Accueil remis dans sa disposition d'origine.")
        return redirect("accueil")
    ordre = [c for c in request.POST.get("ordre", "").split(",") if c]
    accueil_service.enregistrer(
        request.user,
        ordre,
        set(request.POST.getlist("visible")),
        set(request.POST.getlist("large")),
    )
    messages.success(request, "Accueil enregistré.")
    return redirect("accueil")


@login_required
@require_POST
def ecarter_no_go(request):
    """Classe No-Go, en une fois, les avis à trier que l'IA recommande d'écarter."""
    qs = AvisMarche.objects.filter(
        prefiltre_ok=True, statut__in=["DETECTE", "A_QUALIFIER"], recommandation="NO_GO"
    ).exclude(score_modele="règles")
    ids = list(qs.values_list("pk", flat=True))
    qs.update(statut="NO_GO", decision_motif="No-Go recommandé par l'IA", modifie_le=timezone.now())
    request.session["derniers_ecartes"] = ids
    messages.success(request, f"{len(ids)} avis écartés (No-Go recommandés par l'IA). Ils restent consultables dans l'onglet No-Go.",
                     extra_tags="annuler_lot")
    return _retour(request, "tableau")


@login_required
@require_POST
def annuler_ecart(request):
    ids = request.session.pop("derniers_ecartes", [])
    n = AvisMarche.objects.filter(pk__in=ids, statut="NO_GO").update(statut="A_QUALIFIER", decision_motif="")
    messages.success(request, f"{n} avis remis dans « À trier ».")
    return _retour(request, "tableau")


# ---------------------------------------------------------------------------
# Paramètres : affichage, veille automatique, notifications, budget IA
# ---------------------------------------------------------------------------


class ParametresForm(forms.ModelForm):
    class Meta:
        model = Parametres
        fields = [
            "collecte_auto", "heure_collecte", "notif_macos", "notif_email",
            "budget_mensuel", "seuil_alerte_budget", "max_avis_par_collecte", "taux_usd_eur",
        ]
        widgets = {"heure_collecte": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}

    def clean_seuil_alerte_budget(self):
        v = self.cleaned_data["seuil_alerte_budget"]
        if not 1 <= v <= 100:
            raise forms.ValidationError("Entre 1 et 100 %.")
        return v


def _email_configure() -> bool:
    return "console" not in settings.EMAIL_BACKEND and "locmem" not in settings.EMAIL_BACKEND and bool(
        getattr(settings, "EMAIL_HOST", "")
    )


@login_required
def parametres(request):
    p = Parametres.get()
    prefs, _ = PreferencesUtilisateur.objects.get_or_create(utilisateur=request.user)
    if request.method == "POST" and request.POST.get("action") == "theme":
        theme = request.POST.get("theme")
        if theme in dict(PreferencesUtilisateur.THEMES):
            prefs.theme = theme
            prefs.save(update_fields=["theme"])
        return _retour(request, "parametres")
    form = ParametresForm(request.POST or None, instance=p)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Paramètres enregistrés.")
        return redirect("parametres")
    return render(
        request,
        "veille/parametres.html",
        {
            "form": form,
            "p": p,
            "themes": PreferencesUtilisateur.THEMES,
            "theme_choisi": prefs.theme,
            "budget": couts.etat_budget(),
            "par_usage": couts.depense_par_usage(),
            "historique": couts.historique_mensuel(),
            "estimation_avis": couts.estimer_euros("SCORE"),
            "prochaine": planification.prochaine_execution(p),
            "automatisation": planification.automatisation_installee(),
            "derniere": planification.derniere_collecte(),
            "notif_possible": notifications.disponible(),
            "email_configure": _email_configure(),
            "destinataires": [d for pr in ProfilVeille.objects.filter(actif=True) for d in pr.liste_destinataires],
            "modele": settings.CLAUDE_MODEL,
        },
    )


@login_required
@require_POST
def changer_theme(request):
    """Bouton du rail : passe au thème suivant (système → clair → sombre)."""
    prefs, _ = PreferencesUtilisateur.objects.get_or_create(utilisateur=request.user)
    ordre = [t for t, _ in PreferencesUtilisateur.THEMES]
    demande = request.POST.get("theme")
    prefs.theme = demande if demande in ordre else ordre[(ordre.index(prefs.theme) + 1) % len(ordre)]
    prefs.save(update_fields=["theme"])
    return _retour(request, "accueil")


@login_required
@require_POST
def tester_notification(request):
    titre, texte, sous_titre = notifications.message_collecte(notifications.resume_collecte(), couts.etat_budget())
    if notifications.notifier(f"Test – {titre}", texte, sous_titre):
        messages.success(request, "Notification envoyée : elle apparaît en haut à droite de l'écran du Mac.")
    else:
        messages.error(request, "Notification impossible : elle ne fonctionne que sur le Mac qui fait tourner FORM'AO.")
    return redirect("parametres")
