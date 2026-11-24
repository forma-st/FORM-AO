import json
import os
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


# Les tests ne doivent jamais appeler la vraie API Claude.
for _cle in ("VEILLE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ.pop(_cle, None)


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


# ---------------------------------------------------------------------------
# Ergonomie : tri en un clic, onglets, collecte, mémoire modifiable, connexion
# ---------------------------------------------------------------------------


@override_settings(MEDIA_ROOT=MEDIA_TEST)
class ErgonomieTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("matthieu", "m@example.com", "x"))
        Entreprise.objects.create(raison_sociale="FORMA'ST")
        p = profil()
        self.a = avis(objet="Formations SST", acheteur="Ville", profil=p, prefiltre_ok=True, score=80, statut="A_QUALIFIER")
        self.a.save()

    def test_tri_en_un_clic_et_onglets(self):
        r = self.client.get("/appels-offres/?onglet=a_trier")
        self.assertContains(r, "Formations SST")
        r = self.client.post(f"/avis/{self.a.pk}/decider/", {"decision": "NO_GO", "motif": "trop loin", "suivant": "/appels-offres/?onglet=a_trier"})
        self.assertRedirects(r, "/appels-offres/?onglet=a_trier", fetch_redirect_response=False)
        self.a.refresh_from_db()
        self.assertEqual((self.a.statut, self.a.decision_motif), ("NO_GO", "trop loin"))
        self.assertNotContains(self.client.get("/appels-offres/?onglet=a_trier"), 'class="ligne-titre"')  # hors du message flash
        self.assertContains(self.client.get("/appels-offres/?onglet=ecartes"), "Formations SST")
        self.client.post(f"/avis/{self.a.pk}/decider/", {"decision": "GO"})
        self.a.refresh_from_db()
        self.assertEqual(self.a.statut, "GO")
        # la recherche couvre tous les onglets
        self.assertContains(self.client.get("/appels-offres/?q=SST"), "Formations SST")
        # redirection externe refusée
        r = self.client.post(f"/avis/{self.a.pk}/decider/", {"decision": "GO", "suivant": "https://evil.example/"})
        self.assertRedirects(r, "/appels-offres/", fetch_redirect_response=False)

    def test_changer_statut_pipeline(self):
        self.client.post(f"/avis/{self.a.pk}/statut/", {"statut": "DEPOSE"})
        self.a.refresh_from_db()
        self.assertEqual(self.a.statut, "DEPOSE")
        self.assertContains(self.client.get("/pipeline/"), "Formations SST")
        self.assertEqual(self.client.post(f"/avis/{self.a.pk}/statut/", {"statut": "N_IMPORTE"}).status_code, 404)

    def test_collecter_maintenant_en_arriere_plan(self):
        with mock.patch("veille.views.lancer") as lancer:
            r = self.client.post("/collecter/")
        self.assertEqual(r.status_code, 302)
        lancer.assert_called_once()

    def test_memoire_modifiable(self):
        m = Memoire.objects.create(avis=self.a, statut="OK", contenu="## Section\n[À COMPLÉTER : durée]")
        r = self.client.post(f"/memoire/{m.pk}/", {"contenu": "## Section\nDurée : 3h30."})
        self.assertEqual(r.status_code, 302)
        m.refresh_from_db()
        self.assertEqual(m.nb_a_completer, 0)
        self.assertIn("3h30", _texte_docx(self.client.get(f"/memoire/{m.pk}/word/").content))

    def test_connexion(self):
        self.client.logout()
        r = self.client.get("/")
        self.assertRedirects(r, "/connexion/?next=/", fetch_redirect_response=False)
        self.assertContains(self.client.get("/connexion/"), "Se connecter")
        r = self.client.post("/connexion/", {"username": "matthieu", "password": "x"})
        self.assertRedirects(r, "/", fetch_redirect_response=False)


# ---------------------------------------------------------------------------
# Accueil personnalisable et annulation
# ---------------------------------------------------------------------------

from .models import PreferencesAccueil  # noqa: E402
from .services import accueil as accueil_service  # noqa: E402


@override_settings(MEDIA_ROOT=MEDIA_TEST)
class AccueilTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_superuser("matthieu", "m@example.com", "x", first_name="Matthieu")
        self.client.force_login(self.u)
        Entreprise.objects.create(raison_sociale="FORMA'ST")
        p = profil()
        self.a = avis(objet="Formations SST", acheteur="Ville", profil=p, prefiltre_ok=True, score=82,
                      recommandation="GO", statut="A_QUALIFIER", date_publication=timezone.localdate())
        self.a.save()

    def test_accueil_affiche_les_widgets(self):
        r = self.client.get("/")
        self.assertContains(r, "Matthieu")
        for titre in ["À trier", "Prochaines échéances", "Réponses en cours", "Activité de la veille", "Coffre-fort", "État de la veille"]:
            self.assertContains(r, titre)
        self.assertContains(r, "Formations SST")
        self.assertContains(r, "<svg viewBox=")  # graphique d'activité

    def test_personnaliser_ordre_visibilite_taille(self):
        self.assertContains(self.client.get("/?personnaliser=1"), 'id="liste-widgets"')
        r = self.client.post("/accueil/personnaliser/", {
            "ordre": "veille,a_trier,coffre", "visible": ["veille", "a_trier"], "large": ["veille"],
        })
        self.assertRedirects(r, "/", fetch_redirect_response=False)
        prefs = accueil_service.preferences(self.u)
        self.assertEqual([w["cle"] for w in prefs][:3], ["veille", "a_trier", "coffre"])
        visibles = [w["cle"] for w in prefs if w["visible"]]
        self.assertEqual(visibles, ["veille", "a_trier"])
        self.assertTrue(prefs[0]["large"])
        page = self.client.get("/").content.decode()
        self.assertLess(page.index('id="w-veille"'), page.index('id="w-a_trier"'))
        self.assertNotIn('id="w-coffre"', page)
        self.client.post("/accueil/personnaliser/", {"action": "reinitialiser"})
        self.assertFalse(PreferencesAccueil.objects.filter(utilisateur=self.u).exists())

    def test_nouveau_widget_ajoute_aux_preferences_existantes(self):
        PreferencesAccueil.objects.create(utilisateur=self.u, widgets=[{"cle": "coffre", "visible": True}, {"cle": "inconnu"}])
        cles = [w["cle"] for w in accueil_service.preferences(self.u)]
        self.assertEqual(cles[0], "coffre")
        self.assertEqual(sorted(cles), sorted(w.cle for w in accueil_service.CATALOGUE))

    def test_annuler_une_decision(self):
        r = self.client.post(f"/avis/{self.a.pk}/decider/", {"decision": "NO_GO", "suivant": "/appels-offres/"}, follow=True)
        self.assertContains(r, 'name="annulation"')
        self.client.post(f"/avis/{self.a.pk}/decider/", {"decision": "A_QUALIFIER", "annulation": "1"})
        self.a.refresh_from_db()
        self.assertEqual(self.a.statut, "A_QUALIFIER")
        # une annulation peut restaurer n'importe quelle étape précédente, mais pas une valeur inconnue
        self.assertEqual(self.client.post(f"/avis/{self.a.pk}/decider/", {"decision": "PIRATE", "annulation": "1"}).status_code, 404)

    def test_widgets_vides_donnent_une_consigne(self):
        AvisMarche.objects.all().delete()
        r = self.client.get("/")
        self.assertContains(r, "Tout est trié")
        self.assertContains(r, "Aucune échéance")


class EcartGroupeTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("m", "m@example.com", "x"))
        p = profil()
        self.nogo = [avis(source_id=f"n{i}", objet=f"Hors métier {i}", profil=p, prefiltre_ok=True, score=10,
                          recommandation="NO_GO", statut="A_QUALIFIER", score_modele="claude-opus-5-5") for i in range(3)]
        for a in self.nogo:
            a.save()
        self.regle = avis(source_id="r", objet="Score par règles", profil=p, prefiltre_ok=True, score=20,
                          recommandation="NO_GO", statut="A_QUALIFIER", score_modele="règles")
        self.regle.save()
        self.go = avis(source_id="g", objet="Formations SST", profil=p, prefiltre_ok=True, score=85, recommandation="GO", statut="A_QUALIFIER")
        self.go.save()

    def test_ecarter_puis_annuler(self):
        r = self.client.post("/appels-offres/ecarter-no-go/", {"suivant": "/"}, follow=True)
        self.assertContains(r, "3 avis écartés")
        self.assertEqual(AvisMarche.objects.filter(statut="NO_GO").count(), 3)
        # le score par règles n'est pas assez fiable pour écarter automatiquement, et les Go restent
        self.assertEqual(AvisMarche.objects.get(source_id="r").statut, "A_QUALIFIER")
        self.assertEqual(AvisMarche.objects.get(source_id="g").statut, "A_QUALIFIER")
        self.client.post("/appels-offres/annuler-ecart/")
        self.assertEqual(AvisMarche.objects.filter(statut="NO_GO").count(), 0)


# ---------------------------------------------------------------------------
# Paramètres, coût de l'IA, budget, notifications, veille automatique
# ---------------------------------------------------------------------------

from datetime import time as _time  # noqa: E402
from decimal import Decimal  # noqa: E402

from django.core.management import call_command  # noqa: E402

from .models import ConsommationIA, Parametres, PreferencesUtilisateur  # noqa: E402
from .services import couts, notifications, planification  # noqa: E402


def fausse_reponse(entree=5_000, sortie=2_000, lus=0, ecrits=0, modele="claude-opus-5-5", **kw):
    usage = SimpleNamespace(input_tokens=entree, output_tokens=sortie,
                            cache_read_input_tokens=lus, cache_creation_input_tokens=ecrits)
    return SimpleNamespace(usage=usage, model=modele, **kw)


def depenser(euros, usage="SCORE"):
    """Crée une consommation de ce montant (en €, au taux par défaut)."""
    usd = Decimal(str(euros)) / Parametres.get().taux_usd_eur
    return ConsommationIA.objects.create(usage=usage, modele="claude-opus-5-5", cout_usd=usd)


class CoutsTests(TestCase):
    def setUp(self):
        Entreprise.objects.create(raison_sociale="FORMA'ST")
        self.a = avis(objet="Formations SST", profil=profil(), prefiltre_ok=True)
        self.a.save()

    def test_calcul_du_cout(self):
        # 1 M jetons d'entrée = 4 $, 1 M de sortie = 20 $, cache lu = 0,20 $
        self.assertEqual(couts.cout_usd("claude-opus-5-5", 1_000_000, 0), Decimal("4.0"))
        self.assertEqual(couts.cout_usd("claude-opus-5-5", 0, 1_000_000, 1_000_000), Decimal("20.2"))
        # nom inconnu ou suffixé : tarif le plus proche, sinon Opus 5.5
        self.assertEqual(couts.tarif("claude-sonnet-5-5-xyz"), couts.TARIFS["claude-sonnet-5-5"])
        self.assertEqual(couts.tarif("inconnu"), couts.TARIF_PAR_DEFAUT)

    def test_enregistrement_d_un_appel(self):
        c = couts.enregistrer(fausse_reponse(entree=10_000, sortie=5_000, lus=20_000), "SCORE", self.a)
        self.assertEqual((c.jetons_entree, c.jetons_sortie, c.jetons_cache_lus), (10_000, 5_000, 20_000))
        self.assertEqual(c.cout_usd, Decimal("0.144"))  # 0,04 + 0,10 + 0,004
        self.assertEqual(c.avis, self.a)
        # une réponse sans usage (simulations) ne casse rien
        self.assertIsNone(couts.enregistrer(SimpleNamespace(model="x"), "SCORE"))

    def test_scorer_enregistre_la_consommation(self):
        client = mock.Mock()
        client.beta.messages.parse.return_value = fausse_reponse(stop_reason="end_turn", parsed_output=faux_resultat())
        scoring.scorer(self.a, client=client, profil="profil")
        self.assertEqual(ConsommationIA.objects.filter(usage="SCORE", avis=self.a).count(), 1)

    def test_etat_du_budget(self):
        p = Parametres.get()
        p.budget_mensuel, p.seuil_alerte_budget = Decimal("10"), 80
        p.save()
        depenser(5)
        b = couts.etat_budget()
        self.assertEqual((b.depense, b.part, b.alerte, b.atteint, b.niveau), (Decimal("5.00"), 50, False, False, "ok"))
        depenser(3.5)
        self.assertEqual(couts.etat_budget().niveau, "attente")
        depenser(2)
        self.assertTrue(couts.budget_atteint())
        # le mois précédent ne compte pas
        ConsommationIA.objects.update(date=couts.debut_du_mois() - timedelta(days=1))
        self.assertEqual(couts.etat_budget().depense, Decimal("0.00"))
        # budget 0 = pas de limite
        depenser(1000)
        p.budget_mensuel = 0
        p.save()
        self.assertFalse(couts.budget_atteint())

    def test_budget_atteint_bloque_l_ia(self):
        p = Parametres.get()
        p.budget_mensuel = Decimal("1")
        p.save()
        depenser(2)
        client = mock.Mock()
        with self.assertRaises(scoring.BudgetAtteint):
            scoring.scorer(self.a, client=client, profil="profil")
        client.beta.messages.parse.assert_not_called()
        # l'analyse est refusée… sauf si on force
        self.a.texte = "Formations SST"
        an = dce.analyser(self.a, client=client)
        self.assertEqual(an.statut, "ERREUR")
        self.assertIn("Budget", an.erreur)
        client.beta.messages.parse.return_value = fausse_reponse(stop_reason="end_turn", parsed_output=faux_resultat_analyse())
        self.assertEqual(dce.analyser(self.a, client=client, forcer_budget=True).statut, "OK")

    def test_estimation_selon_les_documents(self):
        petit = couts.estimer_usd("ANALYSE", self.a)
        DocumentDCE.objects.create(avis=self.a, nom="CCTP.txt", type="CCTP", texte="x" * 350_000,
                                   fichier=SimpleUploadedFile("CCTP.txt", b"x"))
        self.assertGreater(couts.estimer_usd("ANALYSE", self.a), petit + Decimal("0.3"))  # +100 k jetons ≈ 0,40 $
        # après quelques notations, l'estimation suit la moyenne réelle
        for _ in range(3):
            ConsommationIA.objects.create(usage="SCORE", cout_usd=Decimal("0.02"))
        self.assertEqual(couts.estimer_usd("SCORE"), Decimal("0.02"))


class CommandeScorerTests(TestCase):
    def setUp(self):
        Entreprise.objects.create(raison_sociale="FORMA'ST")
        p = profil()
        for i in range(3):
            avis(source_id=f"s{i}", objet=f"Formations SST {i}", profil=p, prefiltre_ok=True).save()
        os.environ["ANTHROPIC_API_KEY"] = "test"
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)

    def _scorer(self, **kw):
        client = mock.Mock()
        client.beta.messages.parse.return_value = fausse_reponse(stop_reason="end_turn", parsed_output=faux_resultat())
        with mock.patch.object(scoring, "_client", return_value=client), mock.patch.object(scoring, "profil_entreprise", return_value="p"):
            call_command("scorer", stdout=_io.StringIO(), stderr=_io.StringIO(), **kw)
        return client

    def test_limite_par_collecte(self):
        p = Parametres.get()
        p.max_avis_par_collecte = 2
        p.save()
        self._scorer()
        modeles = sorted(AvisMarche.objects.values_list("score_modele", flat=True))
        self.assertEqual(modeles, ["claude-opus-5-5", "claude-opus-5-5", "règles"])

    def test_budget_atteint_bascule_sur_les_regles_puis_renotation(self):
        p = Parametres.get()
        p.budget_mensuel = Decimal("1")
        p.save()
        depenser(2)
        client = self._scorer()
        client.beta.messages.parse.assert_not_called()
        self.assertEqual(set(AvisMarche.objects.values_list("score_modele", flat=True)), {"règles"})
        self.assertEqual(scoring.notes_par_regles().count(), 3)
        # budget relevé : « re-noter » ne traite que les avis notés par règles
        p.budget_mensuel = 0
        p.save()
        self._scorer(refaire_regles=True)
        self.assertEqual(scoring.notes_par_regles().count(), 0)


class VeilleAutomatiqueTests(TestCase):
    def setUp(self):
        self.p = Parametres.get()
        self.p.heure_collecte = _time(7, 10)
        self.p.save()

    def _a(self, h, m, jour=0):
        d = timezone.localdate() + timedelta(days=jour)
        return timezone.make_aware(timezone.datetime(d.year, d.month, d.day, h, m))

    def test_une_fois_par_jour_apres_l_heure(self):
        self.assertFalse(planification.prevue_maintenant(self.p, self._a(6, 59)))
        self.assertTrue(planification.prevue_maintenant(self.p, self._a(7, 10)))
        self.assertTrue(planification.prevue_maintenant(self.p, self._a(11, 0)))  # Mac réveillé tard : rattrapage
        self.p.derniere_veille_auto = timezone.localdate()
        self.assertFalse(planification.prevue_maintenant(self.p, self._a(11, 0)))
        self.assertEqual(planification.prochaine_execution(self.p, self._a(11, 0)), self._a(7, 10, jour=1))
        self.p.collecte_auto = False
        self.assertFalse(planification.prevue_maintenant(self.p, self._a(8, 0, jour=1)))
        self.assertIsNone(planification.prochaine_execution(self.p))

    def test_commande_si_prevu(self):
        with mock.patch("veille.management.commands.veille_quotidienne.prevue_maintenant", return_value=False), \
             mock.patch("veille.management.commands.veille_quotidienne.call_command") as cc:
            call_command("veille_quotidienne", si_prevu=True, stdout=_io.StringIO())
        cc.assert_not_called()
        self.p.notif_email = False
        self.p.save()
        with mock.patch("veille.management.commands.veille_quotidienne.prevue_maintenant", return_value=True), \
             mock.patch("veille.management.commands.veille_quotidienne.call_command") as cc, \
             mock.patch.object(notifications, "notifier") as notif:
            call_command("veille_quotidienne", si_prevu=True, stdout=_io.StringIO())
        self.assertEqual([c.args[0] for c in cc.call_args_list], ["collecter", "scorer"])  # pas d'e-mail
        notif.assert_called_once()
        self.assertEqual(Parametres.get().derniere_veille_auto, timezone.localdate())

    def test_message_de_notification(self):
        r = {"retenus": 3, "go": 1, "forts": 2, "echeances": 1, "erreurs": ["TED"], "a_trier": 7}
        p = Parametres.get()
        p.budget_mensuel = Decimal("20")
        p.save()
        depenser(4.2)
        titre, texte, sous_titre = notifications.message_collecte(r, couts.etat_budget())
        self.assertEqual(titre, "3 nouveaux appels d'offres")
        self.assertIn("1 Go recommandé", texte)
        self.assertIn("TED en échec", texte)
        self.assertIn("4,20 € sur 20 €", sous_titre)
        titre, texte, _ = notifications.message_collecte({**r, "retenus": 0, "erreurs": [], "echeances": 0})
        self.assertEqual(titre, "Pas de nouvel appel d'offres")

    def test_notification_passe_les_textes_en_arguments(self):
        with mock.patch.object(notifications, "disponible", return_value=True), \
             mock.patch.object(notifications.subprocess, "run") as run:
            self.assertTrue(notifications.notifier('Titre "piégé"', "Texte'; do shell script \"x\""))
        commande = run.call_args.args[0]
        self.assertEqual(commande[0], "osascript")
        self.assertIn('Titre "piégé"', commande)  # argument séparé, jamais dans le script
        self.assertFalse(any("piégé" in c for c in commande if c.startswith("display")))


@override_settings(MEDIA_ROOT=MEDIA_TEST)
class ParametresVuesTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_superuser("matthieu", "m@example.com", "x")
        self.client.force_login(self.u)
        Entreprise.objects.create(raison_sociale="FORMA'ST")
        self.pv = profil()

    def test_page_et_enregistrement(self):
        r = self.client.get("/parametres/")
        self.assertContains(r, "Budget de l'IA")
        self.assertContains(r, "Notifications du matin")
        r = self.client.post("/parametres/", {
            "collecte_auto": "on", "heure_collecte": "08:30", "notif_macos": "on",
            "budget_mensuel": "15", "seuil_alerte_budget": "75", "max_avis_par_collecte": "30", "taux_usd_eur": "0.9",
        })
        self.assertRedirects(r, "/parametres/", fetch_redirect_response=False)
        p = Parametres.get()
        self.assertEqual((p.heure_collecte, p.notif_email, p.budget_mensuel, p.max_avis_par_collecte),
                         (_time(8, 30), False, Decimal("15"), 30))
        r = self.client.post("/parametres/", {"heure_collecte": "08:30", "budget_mensuel": "15", "seuil_alerte_budget": "150",
                                              "max_avis_par_collecte": "30", "taux_usd_eur": "0.9"})
        self.assertContains(r, "Entre 1 et 100")

    def test_theme(self):
        self.assertNotContains(self.client.get("/"), "data-theme=")
        self.client.post("/parametres/theme/", {"theme": "sombre", "suivant": "/"})
        self.assertContains(self.client.get("/"), 'data-theme="dark"')
        self.client.post("/parametres/theme/")  # bouton du rail : thème suivant
        self.assertEqual(PreferencesUtilisateur.objects.get(utilisateur=self.u).theme, "systeme")
        self.client.post("/parametres/", {"action": "theme", "theme": "clair"})
        self.assertContains(self.client.get("/"), 'data-theme="light"')
        self.client.post("/parametres/theme/", {"theme": "n_importe"})
        self.assertEqual(PreferencesUtilisateur.objects.get(utilisateur=self.u).theme, "sombre")

    def test_budget_visible_et_alerte(self):
        os.environ["ANTHROPIC_API_KEY"] = "test"
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)
        p = Parametres.get()
        p.budget_mensuel = Decimal("10")
        p.save()
        depenser(9)
        r = self.client.get("/")
        self.assertContains(r, "90 % du budget IA consommé")
        self.assertContains(r, "9,00 € / 10 €")
        depenser(2)
        self.assertContains(self.client.get("/"), "Budget IA du mois atteint")

    def test_tester_notification(self):
        with mock.patch.object(notifications, "notifier", return_value=True) as n:
            r = self.client.post("/parametres/tester-notification/", follow=True)
        n.assert_called_once()
        self.assertContains(r, "Notification envoyée")

    def test_reponse_affiche_l_estimation_et_exige_confirmation(self):
        os.environ["ANTHROPIC_API_KEY"] = "test"
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)
        a = avis(objet="Formations SST", profil=self.pv, prefiltre_ok=True, statut="GO", texte="SST")
        a.save()
        self.assertContains(self.client.get(f"/avis/{a.pk}/reponse/"), "≈ ")
        p = Parametres.get()
        p.budget_mensuel = Decimal("1")
        p.save()
        depenser(2)
        with mock.patch("veille.views.lancer") as lancer:
            r = self.client.post(f"/avis/{a.pk}/reponse/", {"action": "analyser"}, follow=True)
            self.assertContains(r, "Lancer quand même")
            lancer.assert_not_called()
            self.client.post(f"/avis/{a.pk}/reponse/", {"action": "analyser", "depasser_budget": "1"})
            lancer.assert_called_once()
            self.assertTrue(lancer.call_args.kwargs["forcer_budget"])

    def test_renoter_et_onglet_filtre(self):
        os.environ["ANTHROPIC_API_KEY"] = "test"
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)
        avis(source_id="r", objet="Formations SST", profil=self.pv, prefiltre_ok=True, score=40,
             score_modele="règles", statut="A_QUALIFIER").save()
        avis(source_id="f", objet="Nettoyage des locaux", prefiltre_ok=False, prefiltre_motif="mot exclu : nettoyage",
             date_publication=timezone.localdate()).save()
        r = self.client.get("/appels-offres/")
        self.assertContains(r, "Re-noter par l'IA")
        self.assertContains(r, "Score provisoire")
        with mock.patch("veille.views.lancer") as lancer:
            self.client.post("/appels-offres/renoter/")
        lancer.assert_called_once()
        r = self.client.get("/appels-offres/?onglet=filtre")
        self.assertContains(r, "Nettoyage des locaux")
        self.assertContains(r, "mot exclu : nettoyage")

    def test_badge_nouveau_depuis_la_derniere_visite(self):
        PreferencesUtilisateur.objects.create(utilisateur=self.u, derniere_activite=timezone.now() - timedelta(days=1))
        avis(source_id="n", objet="Formations SST", profil=self.pv, prefiltre_ok=True, score=80, statut="A_QUALIFIER").save()
        self.assertContains(self.client.get("/appels-offres/"), "badge-nouveau")
        # à la visite suivante (plus de 30 min plus tard), l'avis n'est plus nouveau
        PreferencesUtilisateur.objects.filter(utilisateur=self.u).update(derniere_activite=timezone.now() - timedelta(hours=1))
        session = self.client.session
        session.pop("visite_precedente")
        session.save()
        AvisMarche.objects.update(cree_le=timezone.now() - timedelta(hours=2))
        self.assertNotContains(self.client.get("/appels-offres/"), "badge-nouveau")


class RepriseTests(TestCase):
    def test_fusion_sans_doublon_ni_ecrasement(self):
        p = profil()
        ici = avis(source_id="1", objet="Déjà collecté", profil=p, prefiltre_ok=True, score=40,
                   score_modele="règles", statut="GO", responsable="Matthieu")
        ici.save()
        export = [
            {"model": "veille.avismarche", "pk": 500, "fields": {
                "source": "BOAMP", "source_id": "1", "objet": "Déjà collecté", "nature": "AVIS", "statut": "A_QUALIFIER",
                "score": 82, "score_modele": "claude-opus-5-5", "recommandation": "GO", "prefiltre_ok": True,
                "score_le": "2026-11-19T20:00:00Z", "profil": 999}},
            {"model": "veille.avismarche", "pk": 501, "fields": {
                "source": "BOAMP", "source_id": "2", "objet": "Nouveau", "nature": "AVIS", "statut": "NO_GO",
                "score": 20, "score_modele": "claude-opus-5-5", "prefiltre_ok": True, "profil": 999,
                "date_publication": "2026-11-18"}},
            {"model": "veille.analysedce", "pk": 1, "fields": {"avis": 500, "statut": "OK", "resultat": {"a": 1},
                                                              "cree_le": "2026-11-19T20:17:04Z"}},
        ]
        chemin = os.path.join(MEDIA_TEST, "reprise.json")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(export, f)
        for _ in range(2):  # relancer ne crée rien de plus
            call_command("reprendre_donnees", chemin, stdout=_io.StringIO())
        self.assertEqual(AvisMarche.objects.count(), 2)
        ici.refresh_from_db()
        self.assertEqual((ici.score, ici.score_modele, ici.statut, ici.responsable), (82, "claude-opus-5-5", "GO", "Matthieu"))
        nouveau = AvisMarche.objects.get(source_id="2")
        self.assertEqual((nouveau.statut, nouveau.profil), ("NO_GO", p))
        self.assertEqual(AnalyseDCE.objects.get().avis, ici)


# ---------------------------------------------------------------------------
# Récupération automatique du DCE
# ---------------------------------------------------------------------------

import httpx  # noqa: E402

from .services import recuperation  # noqa: E402


def _zip_bytes(fichiers: dict) -> bytes:
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as z:
        for nom, contenu in fichiers.items():
            z.writestr(nom, contenu)
    return buf.getvalue()


@override_settings(MEDIA_ROOT=MEDIA_TEST)
class RecuperationDCETests(TestCase):
    def setUp(self):
        self.a = avis(objet="Formations SST", acheteur="Ville")
        self.a.save()
        # pas de résolution DNS pendant les tests
        p = mock.patch("veille.services.recuperation._verifier_hote")
        p.start()
        self.addCleanup(p.stop)

    def test_liens_eforms_fns_et_texte(self):
        self.a.brut = {"donnees": {"EFORMS": {"cac:CallForTendersDocumentReference": {"cac:Attachment": {
            "cac:ExternalReference": {"cbc:URI": "https://demat.exemple.fr/entreprise/consultation/42?orgAcronyme=x&amp;a=1"}}}},
            "FNSimple": {"initial": {"communication": {"urlProfilAch": "https://www.boamp.fr"}}}}}
        self.a.texte = "Dossier : www.exemple.org/dce.zip. Recours : https://paris.tribunal-administratif.fr"
        liens = recuperation.liens_candidats(self.a, distant=False)
        self.assertEqual(liens, ["https://demat.exemple.fr/entreprise/consultation/42?orgAcronyme=x&a=1",
                                 "https://www.exemple.org/dce.zip"])

    def test_detection_atexo(self):
        self.assertEqual(recuperation._atexo("https://www.marches-publics.gouv.fr/entreprise/consultation/3102522?orgAcronyme=a4n"),
                         ("https://www.marches-publics.gouv.fr", "3102522", "a4n"))
        self.assertEqual(recuperation._atexo("https://x.fr/?page=Entreprise.EntrepriseAdvancedSearch&AllCons&id=99&orgAcronyme=f2h")[1:],
                         ("99", "f2h"))
        self.assertIsNone(recuperation._atexo("https://www.exemple.org/dce.zip"))

    def test_plateforme_manuelle_et_page_accueil(self):
        with self.assertRaisesMessage(recuperation.RecuperationImpossible, "captcha"):
            recuperation.telecharger_depuis("https://www.marches-publics.info/mpiaws/index.cfm?IDM=1")
        with self.assertRaisesMessage(recuperation.RecuperationImpossible, "accueil"):
            recuperation.telecharger_depuis("https://www.plateforme.fr/")

    def _transport(self, routes):
        def repondre(req):
            for motif, reponse in routes.items():
                if motif in str(req.url):
                    return reponse()
            return httpx.Response(404)
        vrai = httpx.Client
        return mock.patch("veille.services.recuperation._client",
                          lambda: vrai(transport=httpx.MockTransport(repondre), follow_redirects=True))

    def test_lien_direct_et_page_listant_les_fichiers(self):
        zip_ = _zip_bytes({"RC.pdf": b"%PDF-1.4", "CCTP.docx": _docx_bytes("Former 120 agents")})
        routes = {
            "/dce.zip": lambda: httpx.Response(200, content=zip_, headers={"content-type": "application/zip"}),
            "/page": lambda: httpx.Response(200, html='<a href="pieces/cctp.pdf">CCTP</a><a href="/x.html">x</a>'),
            "/pieces/cctp.pdf": lambda: httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"}),
        }
        with self._transport(routes):
            self.assertEqual([f.nom for f in recuperation.telecharger_depuis("https://ex.fr/dce.zip")], ["dce.zip"])
            self.assertEqual([f.nom for f in recuperation.telecharger_depuis("https://ex.fr/page")], ["cctp.pdf"])

    def test_recuperer_ajoute_les_documents_sans_doublon(self):
        zip_ = _zip_bytes({"RC_consultation.pdf": b"%PDF-1.4", "CCTP.docx": _docx_bytes("Former 120 agents")})
        self.a.url_dce = "https://ex.fr/consultation/1"
        self.a.save()
        with mock.patch.object(recuperation, "telecharger_depuis", return_value=[recuperation.Fichier("dce.zip", zip_)]):
            a = recuperation.recuperer(self.a)
            self.assertEqual(a.dce_statut, "OK")
            self.assertEqual(sorted(a.documents.values_list("type", flat=True)), ["CCTP", "RC"])
            a = recuperation.recuperer(self.a)
        self.assertEqual(a.documents.count(), 2)
        self.assertIn("aucun document nouveau", a.dce_message)

    def test_recuperer_sans_lien_ou_plateforme_manuelle(self):
        a = recuperation.recuperer(self.a)
        self.assertEqual(a.dce_statut, "MANUEL")
        self.assertIn("Aucun lien", a.dce_message)
        a = recuperation.recuperer(self.a, "https://www.achatpublic.com/sdm/ent/gen/ent_detail.do?PCSLID=X")
        self.assertEqual((a.dce_statut, a.dce_lien), ("MANUEL", "https://www.achatpublic.com/sdm/ent/gen/ent_detail.do?PCSLID=X"))


class RecuperationVuesTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("admin", "a@example.com", "x"))
        Entreprise.objects.create(raison_sociale="FORMA'ST")
        self.a = avis(objet="Formations SST", acheteur="Ville", statut="A_QUALIFIER")
        self.a.save()

    def test_go_lance_la_recuperation_une_seule_fois(self):
        with mock.patch("veille.views.lancer") as lancer:
            self.client.post(f"/avis/{self.a.pk}/decider/", {"decision": "GO"})
            self.a.refresh_from_db()
            self.assertEqual(self.a.dce_statut, "EN_COURS")
            self.assertTrue(self.a.dce_en_cours)
            self.client.post(f"/avis/{self.a.pk}/decider/", {"decision": "GO"})
        lancer.assert_called_once()

    def test_bouton_recuperer_avec_lien_colle(self):
        with mock.patch("veille.views.lancer") as lancer:
            r = self.client.post(f"/avis/{self.a.pk}/reponse/",
                                 {"action": "recuperer", "url_dce": "www.ex.fr/consultation/1"})
        self.assertEqual(r.status_code, 302)
        self.a.refresh_from_db()
        self.assertEqual(self.a.url_dce, "https://www.ex.fr/consultation/1")
        self.assertEqual(lancer.call_args.args[2], "https://www.ex.fr/consultation/1")
        page = self.client.get(f"/avis/{self.a.pk}/reponse/")
        self.assertContains(page, "Récupération du dossier sur la plateforme")
        self.assertContains(page, 'http-equiv="refresh"')

    def test_echec_affiche_le_lien_de_la_plateforme(self):
        AvisMarche.objects.filter(pk=self.a.pk).update(
            dce_statut="MANUEL", dce_message="Retrait manuel : captcha.", dce_lien="https://www.marches-publics.info/x")
        page = self.client.get(f"/avis/{self.a.pk}/reponse/")
        self.assertContains(page, "Ouvrir la plateforme")
        self.assertContains(page, "Récupérer le DCE")
