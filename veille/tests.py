from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from .models import AvisMarche, Entreprise, Prestation, ProfilVeille
from .services import boamp, digest, prefiltre, scoring, ted
from .services.texte import mots_cles_trouves, normaliser


def profil(**kw):
    defaults = dict(
        nom="Test",
        mots_cles_forts="sauveteur secouriste\ngestes et postures",
        mots_cles="incendie\nevacuation",
        mots_contexte="formation*\nsensibilisation*",
        mots_contexte_texte="stagiaire*",
        mots_cles_exclus="maintenance\ngardiennage",
        cpv="80550",
        destinataires="ao@example.com",
        seuil_digest=50,
        seuil_alerte=80,
    )
    defaults.update(kw)
    return ProfilVeille.objects.create(**defaults)


def avis(**kw):
    defaults = dict(
        source="BOAMP",
        source_id=str(AvisMarche.objects.count() + 1),
        objet="Objet",
        nature="AVIS",
        type_marche="SERVICES",
        date_limite=timezone.now() + timedelta(days=20),
    )
    defaults.update(kw)
    return AvisMarche(**defaults)


class TexteTests(TestCase):
    def test_normalisation_et_troncature(self):
        self.assertEqual(normaliser("Équipier d'Évacuation"), "equipier d evacuation")
        self.assertEqual(mots_cles_trouves("Formation des SECOURISTES", ["secouriste*"]), ["secouriste*"])
        # pas de correspondance au milieu d'un mot
        self.assertEqual(mots_cles_trouves("assistance", ["sst"]), [])


class PrefiltreTests(TestCase):
    def setUp(self):
        self.p = profil()

    def test_mot_fort_suffit(self):
        a = avis(objet="Marché de sauveteur secouriste du travail")
        self.assertTrue(prefiltre.appliquer(a, [self.p]))

    def test_mot_generique_exige_un_contexte(self):
        a = avis(objet="Prestations de sécurité incendie du musée")
        self.assertFalse(prefiltre.appliquer(a, [self.p]))
        self.assertIn("sans contexte", a.prefiltre_motif)
        b = avis(objet="Formation incendie des agents")
        self.assertTrue(prefiltre.appliquer(b, [self.p]))

    def test_exclusion_travaux_attribution_et_date(self):
        self.assertFalse(prefiltre.appliquer(avis(objet="Maintenance des extincteurs, formation incendie"), [self.p]))
        self.assertFalse(prefiltre.appliquer(avis(objet="Formation incendie", type_marche="TRAVAUX"), [self.p]))
        self.assertFalse(prefiltre.appliquer(avis(objet="Formation incendie", nature="ATTRIBUTION"), [self.p]))
        passe = avis(objet="Formation incendie", date_limite=timezone.now() - timedelta(days=1))
        self.assertFalse(prefiltre.appliquer(passe, [self.p]))
        self.assertEqual(passe.statut, "ECARTE")

    def test_cpv_et_departements(self):
        self.assertTrue(prefiltre.appliquer(avis(objet="Divers", cpv="80550000"), [self.p]))
        p2 = profil(nom="Local", departements="78,92")
        self.assertFalse(prefiltre.appliquer(avis(objet="Formation incendie", departements="13"), [p2]))
        self.assertTrue(prefiltre.appliquer(avis(objet="Formation incendie", departements="92"), [p2]))


class ExtractionTests(TestCase):
    def test_boamp_fnsimple(self):
        donnees = {
            "FNSimple": {
                "initial": {
                    "natureMarche": {
                        "codeCPV": {"objetPrincipal": {"classPrincipale": "80550000"}},
                        "description": "Formations SST et incendie",
                        "lieuExecution": "Rouen (76)",
                    },
                    "lots": {"lot": [{"description": "Lot 1 - SST"}, {"description": "Lot 2 - EPI"}]},
                }
            }
        }
        ext = boamp.extraire_donnees(donnees)
        self.assertEqual(ext["cpv"], ["80550000"])
        self.assertIn("Lot 2 - EPI", ext["texte"])

    def test_boamp_eforms_montant(self):
        donnees = {
            "EFORMS": {
                "ContractNotice": {
                    "cac:ProcurementProject": {
                        "cbc:Description": {"#text": "Accord-cadre de formations"},
                        "cac:RequestedTenderTotal": {"cbc:EstimatedOverallContractAmount": {"#text": "120000"}},
                        "cac:MainCommodityClassification": {"cbc:ItemClassificationCode": {"#text": "80500000"}},
                    }
                }
            }
        }
        ext = boamp.extraire_donnees(donnees)
        self.assertEqual(ext["cpv"], ["80500000"])
        self.assertEqual(int(ext["montant"]), 120000)

    def test_ted_normalisation(self):
        n = {
            "publication-number": "123-2026",
            "notice-type": "cn-standard",
            "notice-title": {"fra": "France – Services de formation – Formations SST"},
            "buyer-name": {"fra": ["Ville de Test"]},
            "classification-cpv": ["80550000", "80550000"],
            "deadline-receipt-tender-date-lot": ["2026-12-05+01:00"],
            "place-of-performance-post-code-proc": ["78190"],
            "description-proc": {"fra": "Formations &quot;SST&quot;"},
        }
        a = ted.normaliser_avis(n)
        self.assertEqual(a["objet"], "Formations SST")
        self.assertEqual(a["nature"], "AVIS")
        self.assertEqual(a["cpv"], "80550000")
        self.assertEqual(a["departements"], "78")
        self.assertIn('"SST"', a["texte"])


def faux_resultat(score=85, reco="GO", eliminatoire=False):
    return scoring.ScoreAvis(
        score=score,
        recommandation=reco,
        resume="Formations SST pour 200 agents.",
        pourquoi="Cœur de métier, MAPA.",
        criteres=[
            scoring.Critere(
                critere="Adéquation",
                evaluation="eliminatoire" if eliminatoire else "favorable",
                commentaire="SST",
            )
        ],
        prestations_concernees=["SST"],
        part_du_besoin_couverte="totale",
        lots_a_viser=[],
        exigences_bloquantes=[],
        concurrence_estimee="faible",
        points_de_vigilance=[],
        questions_a_verifier=[],
    )


class ScoringTests(TestCase):
    def setUp(self):
        Entreprise.objects.create(raison_sociale="FORMA'ST", qualiopi=True, habilitation_inrs_sst=True)
        Prestation.objects.create(intitule="SST initial", categorie="SECOURISME", duree="2j", prix_intra_ht=990)
        self.p = profil()
        self.a = avis(objet="Formations sauveteur secouriste du travail", profil=self.p, prefiltre_ok=True)
        self.a.save()

    def test_profil_contient_catalogue_et_habilitations(self):
        texte = scoring.profil_entreprise()
        self.assertIn("SST initial", texte)
        self.assertIn("INRS", texte)

    def test_appel_ia_structure(self):
        client = mock.Mock()
        client.beta.messages.parse.return_value = SimpleNamespace(
            stop_reason="end_turn", parsed_output=faux_resultat(), model="claude-opus-5-5"
        )
        scoring.scorer(self.a, client=client, profil="profil")
        kwargs = client.beta.messages.parse.call_args.kwargs
        self.assertEqual(kwargs["output_format"], scoring.ScoreAvis)
        self.assertEqual(kwargs["fallbacks"], "default")
        self.assertIn("cache_control", kwargs["system"][0])
        self.a.refresh_from_db()
        self.assertEqual((self.a.score, self.a.recommandation, self.a.statut), (85, "GO", "A_QUALIFIER"))

    def test_eliminatoire_plafonne(self):
        scoring.enregistrer(self.a, faux_resultat(score=90, eliminatoire=True))
        self.assertEqual((self.a.score, self.a.recommandation), (30, "NO_GO"))

    def test_refus_ia(self):
        client = mock.Mock()
        client.beta.messages.parse.return_value = SimpleNamespace(stop_reason="refusal", parsed_output=None, model="x")
        with self.assertRaises(scoring.ScoringIndisponible):
            scoring.scorer(self.a, client=client, profil="profil")

    def test_score_regles(self):
        r = scoring.score_regles(self.a)
        self.assertLessEqual(r.score, 70)
        self.assertEqual(r.recommandation, "A_ETUDIER")


class DigestTests(TestCase):
    def test_digest_et_alerte(self):
        p = profil()
        a = avis(objet="Formations SST", profil=p, prefiltre_ok=True, score=85, recommandation="GO", resume="r")
        a.save()
        avis(source_id="bas", objet="Autre", profil=p, prefiltre_ok=True, score=20).save()
        self.assertEqual(digest.envoyer_alertes(p), 1)
        self.assertEqual(digest.envoyer_digest(p), 1)
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("Formations SST", mail.outbox[1].body)
        # rien de neuf : pas de nouveau digest
        self.assertEqual(digest.envoyer_digest(p), 0)


class VuesTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_superuser("admin", "a@example.com", "x")
        self.client.force_login(self.u)
        p = profil()
        self.a = avis(objet="Formations SST", profil=p, prefiltre_ok=True, score=80, recommandation="GO")
        self.a.save()

    def test_pages(self):
        for url in ["/", f"/avis/{self.a.pk}/", "/pipeline/", "/avis/ajouter/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_suivi_et_ajout(self):
        r = self.client.post(f"/avis/{self.a.pk}/", {"statut": "GO", "responsable": "ML", "decision_motif": "", "notes": ""})
        self.assertEqual(r.status_code, 302)
        self.a.refresh_from_db()
        self.assertEqual(self.a.statut, "GO")
        r = self.client.post("/avis/ajouter/", {"objet": "Consultation privée SST", "acheteur": "Client", "texte": "SST"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(AvisMarche.objects.filter(source="PRIVE", prefiltre_ok=True).exists())

    def test_connexion_requise(self):
        self.client.logout()
        self.assertEqual(self.client.get("/").status_code, 302)


class EformsDetailsTests(TestCase):
    def test_criteres_poids_date_et_attributs(self):
        donnees = {
            "EFORMS": {
                "ContractNotice": {
                    "cac:ProcurementProject": {"cbc:Description": {"@languageID": "FRA", "#text": "Formations"}},
                    "cac:ProcurementProjectLot": {
                        "cac:TenderingTerms": {
                            "cac:AwardingTerms": {
                                "cac:AwardingCriterion": {
                                    "cac:SubordinateAwardingCriterion": [
                                        {
                                            "ext:UBLExtensions": {"efac:AwardCriterionParameter": {"efbc:ParameterNumeric": "60"}},
                                            "cbc:Description": {"@languageID": "FRA", "#text": "Valeur technique"},
                                        },
                                        {
                                            "ext:UBLExtensions": {"efac:AwardCriterionParameter": {"efbc:ParameterNumeric": "40"}},
                                            "cbc:Description": {"#text": "Prix"},
                                        },
                                    ]
                                }
                            }
                        },
                        "cac:TenderingProcess": {
                            "cac:TenderSubmissionDeadlinePeriod": {"cbc:EndDate": "2027-01-11+01:00", "cbc:EndTime": "12:00:00+01:00"}
                        },
                    },
                }
            }
        }
        ext = boamp.extraire_donnees(donnees)
        self.assertIn("Critère : Valeur technique (60)", ext["texte"])
        self.assertIn("Critère : Prix (40)", ext["texte"])
        self.assertNotIn("FRA", ext["texte"].split("\n"))
        self.assertEqual(ext["date_limite"].isoformat(), "2027-01-11T12:00:00+01:00")


# ---------------------------------------------------------------------------
# Phases 2 et 3
# ---------------------------------------------------------------------------

import io as _io  # noqa: E402
import shutil  # noqa: E402
import tempfile  # noqa: E402
import zipfile as _zipfile  # noqa: E402

from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from django.test import override_settings  # noqa: E402

from .models import AnalyseDCE, BlocContenu, DocumentDCE, Memoire, PieceAdministrative, Reference  # noqa: E402
from .services import dce, documents, memoire  # noqa: E402

MEDIA_TEST = tempfile.mkdtemp()


def _docx_bytes(texte):
    from docx import Document

    d = Document()
    d.add_paragraph(texte)
    buf = _io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _texte_docx(contenu: bytes) -> str:
    from docx import Document

    d = Document(_io.BytesIO(contenu))
    morceaux = [p.text for p in d.paragraphs]
    for t in d.tables:
        for r in t.rows:
            morceaux += [c.text for c in r.cells]
    return "\n".join(morceaux)


def faux_resultat_analyse():
    return dce.AnalyseResultat(
        synthese="Formations SST pour 120 agents.",
        objet="Formations SST",
        lots=[dce.Lot(numero="1", intitule="SST", pertinent_pour_nous=True, commentaire="cœur de métier")],
        duree_et_volumes="1 an, 10 sessions",
        lieux_et_organisation="Rouen",
        forme_du_prix="BPU",
        date_limite_offres="14/12/2026",
        date_limite_questions="non précisé",
        visite_ou_soutenance="non",
        criteres_jugement=[
            dce.CritereJugement(nom="Valeur technique", ponderation="60 %", sous_criteres=["Méthodologie"], source="RC p. 5")
        ],
        pieces_a_fournir=[
            dce.Piece(piece="Formulaire DC1", etape="candidature", source="RC p. 3"),
            dce.Piece(piece="Attestation de vigilance URSSAF", etape="candidature", source="RC p. 3"),
            dce.Piece(piece="Planning prévisionnel", etape="offre", source="RC p. 4"),
        ],
        exigences=[dce.Exigence(exigence="Habilitation INRS", source="CCTP p. 2", statut="remplie", commentaire="ok")],
        pieges_et_clauses_sensibles=["Pénalités de retard"],
        questions_a_poser=["Nombre de sites ?"],
        plan_memoire=[
            dce.SectionPlan(titre="Méthodologie", critere_lie="Valeur technique", attendus=["déroulé"], longueur_conseillee="3 pages")
        ],
        prix_a_chiffrer=["Session SST initiale"],
        score=78,
        recommandation="GO",
        justification="Cœur de métier.",
    )


@override_settings(MEDIA_ROOT=MEDIA_TEST)
class Phase2Tests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_TEST, ignore_errors=True)

    def setUp(self):
        Entreprise.objects.create(
            raison_sociale="FORMA'ST", nom_commercial="FORMA'ST", forme_juridique="SARL", siret="89952630500011",
            numero_declaration_activite="11950722095", ville="Méry-sur-Oise", representant_nom="Steven Tabart",
            qualiopi=True, habilitation_inrs_sst=True,
        )
        Reference.objects.create(client="Picard", objet="Formations incendie")
        self.a = avis(objet="Formations SST", acheteur="Ville de Test", lots_vises="2")
        self.a.save()

    def test_dc1_dc2_contenu(self):
        t1 = _texte_docx(documents.dc1(self.a))
        self.assertIn("89952630500011", t1)
        self.assertIn("L. 2141-1", t1)
        self.assertIn("☒ au(x) lot(s) n° 2", t1)
        t2 = _texte_docx(documents.dc2(self.a))
        self.assertIn("11950722095", t2)
        self.assertIn("[À COMPLÉTER]", t2)  # CA non renseigné
        self.assertIn("Picard", t2)

    def test_controle_pieces_a_la_date_limite(self):
        PieceAdministrative.objects.create(
            type="URSSAF", fichier=SimpleUploadedFile("u.pdf", b"%PDF"), date_expiration=timezone.localdate() + timedelta(days=5)
        )
        PieceAdministrative.objects.create(type="KBIS", fichier=SimpleUploadedFile("k.pdf", b"%PDF"))
        etats = {c.type: c.statut for c in documents.controler_pieces(self.a)}
        self.assertEqual(etats["URSSAF"], "expiree")  # date limite dans 20 jours
        self.assertEqual(etats["KBIS"], "ok")
        self.assertEqual(etats["FISCAL"], "manquante")

    def test_dossier_zip(self):
        PieceAdministrative.objects.create(type="KBIS", fichier=SimpleUploadedFile("k.pdf", b"%PDF-kbis"))
        z = _zipfile.ZipFile(_io.BytesIO(documents.dossier_zip(self.a, memoire_docx=b"docx")))
        noms = z.namelist()
        self.assertIn("1_Candidature/01_DC1_lettre_de_candidature.docx", noms)
        self.assertTrue(any(n.endswith("_KBIS.pdf") for n in noms))
        self.assertIn("2_Offre/Memoire_technique_FORMAST.docx", noms)
        self.assertIn("[MANQUANTE]", z.read("A_LIRE_check-list.txt").decode())

    def test_consultation_privee_sans_formulaires_publics(self):
        self.a.source = "PRIVE"
        noms = _zipfile.ZipFile(_io.BytesIO(documents.dossier_zip(self.a))).namelist()
        self.assertFalse(any("DC1" in n or "DC2" in n for n in noms))
        self.assertTrue(any("Presentation" in n for n in noms))


@override_settings(MEDIA_ROOT=MEDIA_TEST)
class Phase3Tests(TestCase):
    def setUp(self):
        Entreprise.objects.create(raison_sociale="FORMA'ST", qualiopi=True, habilitation_inrs_sst=True)
        BlocContenu.objects.create(titre="Contact unique", categorie="ORGANISATION", texte="Un interlocuteur unique.")
        self.a = avis(objet="Formations SST", acheteur="Ville")
        self.a.save()

    def test_depot_zip_securise_et_types(self):
        buf = _io.BytesIO()
        with _zipfile.ZipFile(buf, "w") as z:
            z.writestr("DCE/RC_reglement_consultation.docx", _docx_bytes("Critère valeur technique 60 %"))
            z.writestr("DCE/CCTP.txt", "Formation SST")
            z.writestr("../evil.txt", "x")
            z.writestr("__MACOSX/._RC.docx", "x")
            z.writestr("DCE/image.exe", "x")
        docs = dce.ajouter_fichiers(self.a, [SimpleUploadedFile("dce.zip", buf.getvalue())])
        self.assertEqual(sorted(d.type for d in docs), ["CCTP", "RC"])
        rc = next(d for d in docs if d.type == "RC")
        self.assertIn("valeur technique", rc.texte)

    def test_analyse_mockee_et_rapprochement(self):
        DocumentDCE.objects.create(avis=self.a, nom="CCTP.txt", type="CCTP", texte="SST",
                                   fichier=SimpleUploadedFile("CCTP.txt", b"SST"))
        client = mock.Mock()
        client.beta.messages.parse.return_value = SimpleNamespace(
            stop_reason="end_turn", parsed_output=faux_resultat_analyse(), model="claude-opus-5-5"
        )
        an = dce.analyser(self.a, client=client)
        self.assertEqual(an.statut, "OK")
        kwargs = client.beta.messages.parse.call_args.kwargs
        contenu = kwargs["messages"][0]["content"]
        self.assertEqual(contenu[0]["type"], "document")
        self.assertEqual(kwargs["output_format"], dce.AnalyseResultat)
        etats = {p["piece"]: p["etat"] for p in dce.rapprocher_pieces(an)}
        self.assertEqual(etats["Formulaire DC1"], "genere")
        self.assertEqual(etats["Attestation de vigilance URSSAF"], "manquante")
        self.assertEqual(etats["Planning prévisionnel"], "a_faire")

    def test_analyse_erreur_enregistree(self):
        client = mock.Mock()
        client.beta.messages.parse.side_effect = RuntimeError("panne")
        self.a.texte = "Formations SST pour les agents"
        an = dce.analyser(self.a, client=client)
        self.assertEqual(an.statut, "ERREUR")
        self.assertIn("panne", an.erreur)

    def test_memoire_mocke_et_export(self):
        AnalyseDCE.objects.create(avis=self.a, statut="OK", resultat=faux_resultat_analyse().model_dump())
        texte = "## Méthodologie\nDéroulé en 3 temps.\n\n| Séquence | Durée |\n|---|---|\n| Accueil | 15 min |\n\n- Point **clé**\n\n[À COMPLÉTER : nombre de sessions]"
        message = SimpleNamespace(stop_reason="end_turn", model="claude-opus-5-5",
                                  content=[SimpleNamespace(type="text", text=texte)])
        flux = mock.MagicMock()
        flux.__enter__.return_value.get_final_message.return_value = message
        client = mock.Mock()
        client.beta.messages.stream.return_value = flux
        m = memoire.rediger(self.a, consignes="insister sur l'UMFI", client=client)
        self.assertEqual(m.statut, "OK", m.erreur)
        self.assertEqual(m.nb_a_completer, 1)
        demande = client.beta.messages.stream.call_args.kwargs["messages"][0]["content"][-1]["text"]
        self.assertIn("Plan imposé", demande)
        self.assertIn("insister sur l'UMFI", demande)
        self.assertIn("Contact unique", client.beta.messages.stream.call_args.kwargs["system"][0]["text"])
        doc_texte = _texte_docx(memoire.vers_docx(m))
        self.assertIn("MÉMOIRE TECHNIQUE", doc_texte)
        self.assertIn("Accueil", doc_texte)
        self.a.refresh_from_db()
        self.assertEqual(self.a.statut, "REDACTION")

    def test_grille_conformite(self):
        from openpyxl import load_workbook

        AnalyseDCE.objects.create(avis=self.a, statut="OK", resultat=faux_resultat_analyse().model_dump())
        wb = load_workbook(_io.BytesIO(memoire.grille_conformite(self.a)))
        self.assertEqual(wb.sheetnames, ["Critères et mémoire", "Exigences", "Pièces"])
        self.assertEqual(wb["Critères et mémoire"]["E2"].value, "Méthodologie")


@override_settings(MEDIA_ROOT=MEDIA_TEST)
class VuesPhase23Tests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@example.com", "x"))
        Entreprise.objects.create(raison_sociale="FORMA'ST")
        self.a = avis(objet="Formations SST", acheteur="Ville")
        self.a.save()

    def test_pages_et_telechargements(self):
        for url in [f"/avis/{self.a.pk}/reponse/", "/coffre-fort/", f"/avis/{self.a.pk}/document/dc1/",
                    f"/avis/{self.a.pk}/dossier.zip", f"/avis/{self.a.pk}/grille.xlsx"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_media_protege(self):
        p = PieceAdministrative.objects.create(type="RIB", fichier=SimpleUploadedFile("rib.pdf", b"%PDF"))
        self.assertEqual(self.client.get(f"/media/{p.fichier.name}").status_code, 200)
        self.assertEqual(self.client.get("/media/../config/settings.py").status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(f"/media/{p.fichier.name}").status_code, 302)

    def test_lancement_analyse_en_arriere_plan(self):
        with mock.patch("veille.views.lancer") as lancer:
            r = self.client.post(f"/avis/{self.a.pk}/reponse/", {"action": "analyser"})
        self.assertEqual(r.status_code, 302)
        lancer.assert_called_once()
        self.assertEqual(AnalyseDCE.objects.get(avis=self.a).statut, "EN_COURS")
        self.assertContains(self.client.get(f"/avis/{self.a.pk}/reponse/"), 'http-equiv="refresh"')


# ---------------------------------------------------------------------------
# Profil : annuaire, complétude, ajout ultérieur des pièces
# ---------------------------------------------------------------------------

from .services import annuaire  # noqa: E402

REPONSE_ANNUAIRE = {
    "results": [
        {
            "siren": "899526305",
            "nom_complet": "FORMA'ST",
            "nom_raison_sociale": "FORMA'ST",
            "nature_juridique": "5499",
            "activite_principale": "85.59A",
            "date_creation": "2021-05-10",
            "tranche_effectif_salarie": "02",
            "siege": {
                "siret": "89952630500011",
                "adresse": "31 RUE DE L'ISLE-ADAM 95540 MERY-SUR-OISE",
                "code_postal": "95540",
                "libelle_commune": "MERY-SUR-OISE",
            },
            "dirigeants": [{"nom": "TABART", "prenoms": "STEVEN TIMOTHY", "qualite": "Gérant", "type_dirigeant": "personne physique"}],
            "complements": {"est_qualiopi": True, "liste_id_organisme_formation": ["11950722095"]},
        }
    ]
}


@override_settings(MEDIA_ROOT=MEDIA_TEST)
class ProfilTests(TestCase):
    def setUp(self):
        self.e = Entreprise.objects.create(raison_sociale="X", siret="89952630500011", ville="Méry-sur-Oise", email="ao@forma-st.fr")

    def test_tva(self):
        self.assertEqual(annuaire.tva_intracommunautaire("899526305"), "FR30899526305")

    def test_mise_a_jour_annuaire_sans_ecraser(self):
        with mock.patch("veille.services.annuaire.get_json", return_value=REPONSE_ANNUAIRE):
            modifies = annuaire.mettre_a_jour(self.e)
        self.e.refresh_from_db()
        self.assertEqual(self.e.raison_sociale, "FORMA'ST")
        self.assertEqual(self.e.forme_juridique, "SARL")
        self.assertEqual(self.e.adresse, "31 rue de l'Isle-Adam")
        self.assertEqual(self.e.ville, "Méry-sur-Oise")  # accent conservé
        self.assertEqual(self.e.representant_nom, "Steven Timothy Tabart")
        self.assertEqual(self.e.tranche_effectif, "3 à 5 salariés")
        self.assertEqual(self.e.email, "ao@forma-st.fr")  # saisi à la main : conservé
        self.assertNotIn("ville", modifies)

    def test_info_ajoutee_apparait_dans_les_documents(self):
        a = avis(objet="Formations SST", acheteur="Ville")
        a.save()
        self.assertIn("[À COMPLÉTER]", _texte_docx(documents.dc2(a)))
        self.e.ca_n1, self.e.ca_n2, self.e.ca_n3 = 250000, 180000, 120000
        self.e.capital = 5000
        self.e.forme_juridique = "SARL"
        self.e.save()
        texte = _texte_docx(documents.dc2(a))
        self.assertIn("250 000 € HT", texte)
        self.assertIn("SARL – capital de 5 000 €", texte)

    def test_page_profil_et_ajout_piece_depuis_la_reponse(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@example.com", "x"))
        a = avis(objet="Formations SST", acheteur="Ville")
        a.save()
        self.assertContains(self.client.get("/profil/"), "Complétude des documents")
        r = self.client.post("/profil/?suivant=/avis/%d/reponse/" % a.pk, {"email": "ao@forma-st.fr", "telephone": "01 02 03 04 05", "ca_n1": "250000"})
        self.assertRedirects(r, f"/avis/{a.pk}/reponse/", fetch_redirect_response=False)
        self.assertEqual(Entreprise.get().telephone, "01 02 03 04 05")
        page = self.client.get(f"/avis/{a.pk}/reponse/").content.decode()
        self.assertIn("?type=KBIS", page)
        r = self.client.get("/coffre-fort/?type=KBIS")
        self.assertContains(r, 'value="KBIS" selected')
        r = self.client.post(f"/coffre-fort/?suivant=/avis/{a.pk}/reponse/",
                             {"type": "KBIS", "fichier": SimpleUploadedFile("kbis.pdf", b"%PDF")})
        self.assertRedirects(r, f"/avis/{a.pk}/reponse/", fetch_redirect_response=False)
        self.assertEqual({c.type: c.statut for c in documents.controler_pieces(a)}["KBIS"], "ok")
        # redirection externe refusée
        r = self.client.post("/profil/?suivant=//evil.example", {"email": "ao@forma-st.fr"})
        self.assertRedirects(r, "/profil/", fetch_redirect_response=False)
