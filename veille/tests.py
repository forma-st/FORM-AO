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
