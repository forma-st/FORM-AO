"""Récupération automatique du dossier de consultation (DCE) sur la plateforme de l'acheteur.

Fonctionne pour toute consultation, publique ou privée, dès qu'on a un lien :
1. on cherche le lien du DCE : saisi à la main, dans l'avis (eForms, BOAMP, TED),
   ou dans le texte collé (mail d'une consultation privée) ;
2. selon la plateforme :
   - plateformes Atexo (PLACE marches-publics.gouv.fr, Maximilien, Mégalis, demat-ampa,
     et la plupart des plateformes régionales) : retrait anonyme du DCE complet ;
   - lien direct vers un fichier (ZIP, PDF, Word…), Dropbox, page listant des fichiers :
     téléchargement direct ;
   - plateformes qui imposent un captcha ou un compte (AWS, achatpublic…) : on ne force
     pas l'accès ; on donne le bon lien pour un retrait manuel en deux clics.
3. les fichiers sont ajoutés aux documents du DCE (les ZIP sont décompressés).

Le retrait est anonyme : l'acheteur ne nous préviendra pas des modifications du DCE.
Penser à « Récupérer à nouveau » avant le dépôt.
"""

from __future__ import annotations

import html
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from django.utils import timezone

from ..models import AvisMarche
from . import dce as dce_service

log = logging.getLogger("veille.recuperation")

TAILLE_MAX = 300 * 1024 * 1024
EXTENSIONS_FICHIER = (".zip", ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".xlsm", ".odt", ".ods", ".txt", ".csv")
TYPES_FICHIER = ("application/zip", "application/x-zip", "application/pdf", "application/octet-stream",
                 "application/msword", "application/vnd.")

# Hôtes qui ne portent jamais le DCE (avis, recours, sites institutionnels).
HOTES_IGNORES = ("boamp.fr", "ted.europa.eu", "europa.eu", "tribunal-administratif.fr", "telerecours.fr",
                 "legifrance.gouv.fr", "tribunaladministratif.fr", "justice.fr", "economie.gouv.fr", "juradm.fr", "service-public.fr")

# Plateformes dont le retrait impose un captcha, un compte ou une identification de l'entreprise.
PLATEFORMES_MANUELLES = {
    "marches-publics.info": "AWS demande de recopier un code (captcha) avant le retrait",
    "awsolutions.fr": "AWS demande de recopier un code (captcha) avant le retrait",
    "achatpublic.com": "achatpublic demande d'identifier l'entreprise avant le retrait",
    "marches-securises.fr": "marches-securises.fr demande un compte entreprise",
    "e-marchespublics.com": "e-marchespublics demande un compte entreprise",
    "klekoon.com": "Klekoon demande un compte entreprise",
    "centraledesmarches.com": "la Centrale des marchés demande un compte",
    "francemarches.com": "France Marchés demande un compte",
    "wetransfer.com": "WeTransfer ne permet pas le téléchargement automatique",
    "we.tl": "WeTransfer ne permet pas le téléchargement automatique",
}

CHEMINS_DCE = (
    "CallForTendersDocumentReference/cac:Attachment/cac:ExternalReference/cbc:URI",
    "communication/urlDocConsul",
)
CHEMINS_PROFIL = (
    "cac:ContractingParty/cbc:BuyerProfileURI",
    "communication/urlProfilAch",
)


class RecuperationImpossible(Exception):
    def __init__(self, message: str, lien: str = ""):
        super().__init__(message)
        self.lien = lien


@dataclass
class Fichier:
    nom: str
    contenu: bytes


# ---------------------------------------------------------------------------
# Trouver le lien
# ---------------------------------------------------------------------------


def _parcourir(o, chemin=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _parcourir(v, f"{chemin}/{k}")
    elif isinstance(o, list):
        for v in o:
            yield from _parcourir(v, chemin)
    else:
        yield chemin, o


def _normaliser(u: str) -> str:
    u = html.unescape(u.strip()).rstrip(".,;)»>\"'")
    if u.startswith("www."):
        u = "https://" + u
    return u


def _hote(u: str) -> str:
    return (urlparse(u).hostname or "").lower().removeprefix("www.")


def _est_profond(u: str) -> bool:
    p = urlparse(u)
    return bool(p.query) or len(p.path.strip("/")) > 1


def _utile(u: str) -> bool:
    h = _hote(u)
    return bool(h) and urlparse(u).scheme in ("http", "https") and not any(
        h == x or h.endswith("." + x) for x in HOTES_IGNORES
    )


def liens_dans_texte(texte: str) -> list[str]:
    return [_normaliser(u) for u in re.findall(r"(?:https?://|www\.)[^\s<>\"']+", texte or "")]


def _liens_ted(avis: AvisMarche) -> list[str]:
    """Le lien du DCE n'est pas dans les champs de recherche TED : on lit l'avis XML."""
    from .http import _requete

    xml = ((avis.brut or {}).get("links") or {}).get("xml", {}).get("MUL") or (
        f"https://ted.europa.eu/en/notice/{avis.source_id}/xml"
    )
    try:
        r = _requete("GET", xml)
    except httpx.HTTPError as e:
        log.warning("Avis TED %s illisible : %s", xml, e)
        return []
    bloc = re.findall(r"<cac:CallForTendersDocumentReference>.*?</cac:CallForTendersDocumentReference>", r.text, re.S)
    liens = [_normaliser(u) for b in bloc for u in re.findall(r"<cbc:URI>([^<]+)</cbc:URI>", b)]
    return liens + [_normaliser(u) for u in re.findall(r"<cbc:BuyerProfileURI>([^<]+)</cbc:BuyerProfileURI>", r.text)]


def _liens_boamp(avis: AvisMarche) -> list[str]:
    """Avis BOAMP dont le contenu brut n'a pas été gardé : on le relit dans l'open data."""
    from .boamp import URL
    from .http import get_json

    try:
        data = get_json(URL, params={"where": f'idweb = "{avis.source_id}"', "select": "donnees", "limit": 1})
    except Exception as e:  # noqa: BLE001 - la recherche continue avec les autres sources
        log.warning("BOAMP %s illisible : %s", avis.source_id, e)
        return []
    res = data.get("results") or []
    return liens_dans_texte(res[0].get("donnees") or "") if res else []


def liens_candidats(avis: AvisMarche, distant: bool = True) -> list[str]:
    """Liens où chercher le DCE, du plus sûr au moins sûr."""
    dce, profil, autres = [], [], []
    if avis.url_dce:
        dce.append(avis.url_dce)
    for chemin, v in _parcourir(avis.brut or {}):
        if not isinstance(v, str):
            continue
        if chemin.endswith(CHEMINS_DCE):
            dce.append(_normaliser(v))
        elif chemin.endswith(CHEMINS_PROFIL):
            profil.append(_normaliser(v))
    autres += liens_dans_texte(avis.texte) + liens_dans_texte(avis.notes)
    if distant and not [u for u in dce if _utile(u) and _est_profond(u)]:
        if avis.source == "TED":
            dce += _liens_ted(avis)
        elif avis.source == "BOAMP" and not (avis.brut or {}).get("donnees"):
            autres += _liens_boamp(avis)
    vus, sortie = set(), []
    # liens profonds d'abord (page de la consultation), pages d'accueil des plateformes en dernier
    tous = dce + autres + profil
    for u in [u for u in tous if _est_profond(u)] + [u for u in tous if not _est_profond(u)]:
        if _utile(u) and u not in vus:
            vus.add(u)
            sortie.append(u)
    return sortie


# ---------------------------------------------------------------------------
# Téléchargement
# ---------------------------------------------------------------------------


def _client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(120.0, connect=20.0),
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) FORM-AO/1.0", "Accept-Language": "fr-FR,fr"},
    )


def _verifier_hote(u: str) -> None:
    """Refuse les adresses du réseau local : un lien piégé ne doit pas viser le Mac lui-même."""
    h = urlparse(u).hostname or ""
    try:
        for info in socket.getaddrinfo(h, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise RecuperationImpossible(f"Adresse non autorisée : {h}.")
    except socket.gaierror:
        raise RecuperationImpossible(f"Site introuvable : {h}.", u) from None


def _nom_fichier(r: httpx.Response, defaut: str) -> str:
    cd = r.headers.get("content-disposition", "")
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd, re.I)
    nom = unquote(m.group(1).strip()) if m else unquote(urlparse(str(r.url)).path.rsplit("/", 1)[-1])
    nom = re.sub(r"[/\\:]", "_", nom).strip() or defaut
    return nom if "." in nom else defaut


def _est_fichier(r: httpx.Response) -> bool:
    ct = r.headers.get("content-type", "").lower()
    return "attachment" in r.headers.get("content-disposition", "").lower() or (
        "html" not in ct and any(ct.startswith(t) for t in TYPES_FICHIER)
    )


def _telecharger(c: httpx.Client, methode: str, url: str, **kw) -> httpx.Response:
    _verifier_hote(url)
    with c.stream(methode, url, **kw) as r:
        taille = int(r.headers.get("content-length") or 0)
        if taille > TAILLE_MAX:
            raise RecuperationImpossible("Dossier trop volumineux pour un téléchargement automatique.", url)
        morceaux, total = [], 0
        for m in r.iter_bytes():
            total += len(m)
            if total > TAILLE_MAX:
                raise RecuperationImpossible("Dossier trop volumineux pour un téléchargement automatique.", url)
            morceaux.append(m)
        r._content = b"".join(morceaux)
    return r


def _champs_formulaire(page: str, form_id: str) -> dict:
    m = re.search(rf'<form[^>]*id="{form_id}".*?</form>', page, re.S)
    if not m:
        raise RecuperationImpossible("Formulaire de retrait introuvable sur la plateforme.")
    champs = {}
    for i in re.findall(r"<input[^>]*>", m.group(0)):
        nom = re.search(r'name="([^"]+)"', i)
        typ = re.search(r'type="([^"]+)"', i)
        if not nom or (typ and typ.group(1).lower() in ("radio", "checkbox", "submit", "button")):
            continue
        val = re.search(r'value="([^"]*)"', i)
        champs[html.unescape(nom.group(1))] = html.unescape(val.group(1)) if val else ""
    return champs


ATEXO_ID = re.compile(r"/entreprise/consultation/(\d+)|[?&]id=(\d+)")


def _atexo(url: str, page: str | None = None) -> tuple[str, str, str] | None:
    """(base, id, organisme) si le lien est une consultation sur une plateforme Atexo."""
    q = parse_qs(urlparse(html.unescape(url)).query)
    org = (q.get("orgAcronyme") or q.get("orgAcronym") or [""])[0]
    m = ATEXO_ID.search(url)
    if page and not (org and m):
        lien = re.search(r"EntrepriseDemandeTelechargementDce&(?:amp;)?id=(\d+)&(?:amp;)?orgAcronyme=([\w-]+)", page)
        if lien:
            p = urlparse(url)
            return f"{p.scheme}://{p.netloc}", lien.group(1), lien.group(2)
    if org and m:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}", m.group(1) or m.group(2), org
    return None


def retrait_atexo(c: httpx.Client, base: str, ident: str, org: str) -> list[Fichier]:
    """Retrait anonyme du DCE complet (formulaire « Je souhaite télécharger anonymement »)."""
    url = f"{base}/index.php?page=Entreprise.EntrepriseDemandeTelechargementDce&id={ident}&orgAcronyme={org}"
    _verifier_hote(url)
    page = c.get(url).text
    if "choixAnonyme" not in page:
        raise RecuperationImpossible(
            "La plateforme n'autorise pas le retrait anonyme pour cette consultation (compte ou code d'accès demandé).",
            url,
        )
    p = "ctl0$CONTENU_PAGE$EntrepriseFormulaireDemande$"
    champs = _champs_formulaire(page, "ctl0_ctl1")
    champs.update({
        p + "RadioGroup": p + "choixAnonyme",
        p + "accepterConditions": "on",
        "ctl0$CONTENU_PAGE$validateButton": "Valider",
        "PRADO_POSTBACK_TARGET": "ctl0$CONTENU_PAGE$validateButton",
    })
    page = c.post(url, data=champs).text
    cible = "ctl0$CONTENU_PAGE$EntrepriseDownloadDce$completeDownload"
    if cible not in page:
        raise RecuperationImpossible(
            "La plateforme n'a pas proposé le téléchargement (consultation close ou accès restreint).", url
        )
    champs = _champs_formulaire(page, "ctl0_ctl1")
    champs.update({"PRADO_POSTBACK_TARGET": cible, "PRADO_POSTBACK_PARAMETER": ""})
    r = _telecharger(c, "POST", url, data=champs)
    if not _est_fichier(r):
        raise RecuperationImpossible("La plateforme n'a pas renvoyé de fichier.", url)
    return [Fichier(_nom_fichier(r, f"DCE_{ident}.zip"), r.content)]


def _lien_direct(u: str) -> str:
    h = _hote(u)
    if h.endswith("dropbox.com"):
        return re.sub(r"([?&])dl=0", r"\1dl=1", u) if "dl=0" in u else u + ("&" if "?" in u else "?") + "dl=1"
    return u


def _liens_fichiers(page: str, base: str) -> list[str]:
    liens = []
    for href in re.findall(r'href="([^"#]+)"', page, re.I):
        u = urljoin(base, html.unescape(href))
        chemin = urlparse(u).path.lower()
        if chemin.endswith(EXTENSIONS_FICHIER) and u not in liens:
            liens.append(u)
    return liens[:20]


def telecharger_depuis(url: str) -> list[Fichier]:
    """Récupère les fichiers du DCE à partir d'un lien (page de consultation ou fichier)."""
    h = _hote(url)
    for domaine, raison in PLATEFORMES_MANUELLES.items():
        if h == domaine or h.endswith("." + domaine):
            raise RecuperationImpossible(f"Retrait manuel : {raison}.", url)
    if not _est_profond(url):
        raise RecuperationImpossible(
            f"Le lien de l'avis mène à l'accueil de {h}, pas à la consultation. Cherchez la consultation "
            "sur la plateforme (référence de l'avis), puis collez son lien ici.",
            url,
        )
    with _client() as c:
        if a := _atexo(url):
            return retrait_atexo(c, *a)
        r = _telecharger(c, "GET", _lien_direct(url))
        if _est_fichier(r):
            return [Fichier(_nom_fichier(r, "DCE.zip"), r.content)]
        page = r.text
        if a := _atexo(str(r.url), page):
            return retrait_atexo(c, *a)
        fichiers = []
        for lien in _liens_fichiers(page, str(r.url)):
            try:
                rf = _telecharger(c, "GET", lien)
            except (httpx.HTTPError, RecuperationImpossible) as e:
                log.warning("%s : %s", lien, e)
                continue
            if _est_fichier(rf):
                fichiers.append(Fichier(_nom_fichier(rf, "document"), rf.content))
        if fichiers:
            return fichiers
        if re.search(r"captcha", page, re.I):
            raise RecuperationImpossible("Retrait manuel : la plateforme demande de recopier un code (captcha).", url)
        if re.search(r'type="password"', page, re.I):
            raise RecuperationImpossible("Retrait manuel : la plateforme demande de se connecter.", url)
        raise RecuperationImpossible("Aucun fichier trouvé à cette adresse.", url)


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------


def recuperer(avis: AvisMarche, url: str | None = None) -> AvisMarche:
    """Cherche et ajoute le DCE de l'avis. Ne lève pas d'exception : l'issue est notée sur l'avis."""
    avis.refresh_from_db()
    candidats = [url] if url else liens_candidats(avis)
    deja = set(avis.documents.values_list("nom", flat=True))
    statut, message, lien = "MANUEL", "", ""
    if not candidats:
        message = ("Aucun lien vers le dossier de consultation dans l'avis. Collez le lien de la plateforme "
                   "(ou celui reçu par mail) puis relancez, ou déposez les fichiers.")
    for u in candidats:
        try:
            fichiers = telecharger_depuis(u)
        except RecuperationImpossible as e:
            message, lien = message or str(e), lien or e.lien or u
            log.info("DCE %s : %s", u, e)
            continue
        except httpx.HTTPError as e:
            message, lien = message or f"La plateforme ne répond pas ({e.__class__.__name__}).", lien or u
            log.warning("DCE %s : %s", u, e)
            continue
        except Exception as e:  # noqa: BLE001 - toujours rendre la main à l'utilisateur
            log.exception("DCE %s", u)
            statut, message, lien = "ERREUR", f"Erreur inattendue : {e}", u
            continue
        ajoutes = []
        for f in fichiers:
            ajoutes += dce_service.ajouter_contenu(avis, f.nom, f.contenu, ignorer=deja)
        n = len(ajoutes)
        statut, lien = "OK", u
        message = (f"{n} document(s) récupéré(s) sur {_hote(u)}." if n
                   else f"Dossier récupéré sur {_hote(u)} : aucun document nouveau.")
        break
    AvisMarche.objects.filter(pk=avis.pk).update(
        dce_statut=statut, dce_message=message[:1000], dce_lien=lien[:500], dce_recupere_le=timezone.now()
    )
    avis.refresh_from_db()
    return avis


def recuperer_puis_analyser(avis: AvisMarche, url: str | None = None, forcer_budget: bool = False) -> None:
    avis = recuperer(avis, url)
    if avis.dce_statut == "OK" and avis.documents.exists():
        from ..models import AnalyseDCE

        AnalyseDCE.objects.update_or_create(avis=avis, defaults={"statut": "EN_COURS", "erreur": ""})
        dce_service.analyser(avis, forcer_budget=forcer_budget)
