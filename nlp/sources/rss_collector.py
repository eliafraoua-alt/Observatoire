"""
Collecteur RSS — presse économique nationale et locale (Val-d'Oise / Seine-et-Marne).

Les flux RSS sont la source la plus stable et la plus simple à exploiter :
pas de problème de robots.txt (un flux RSS est publié précisément pour être
consommé par des agrégateurs), pas de rendu JavaScript à gérer, structure
prévisible. C'est la voie privilégiée pour ce module.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

import feedparser
import pandas as pd

log = logging.getLogger(__name__)


@dataclass
class ArticlePresse:
    titre: str
    resume: str
    url: str
    source: str
    date_publication: str
    categorie: str  # "nationale_eco" | "locale" | "institutionnelle"


# ── Registre des flux RSS ──────────────────────────────────────────────────────
# IMPORTANT — Statut de validation des URLs ci-dessous :
# Les URLs Le Parisien proviennent d'un annuaire de flux RSS tiers
# (atlasflux.saynete.com, consulté le 30/06/2026) et n'ont PAS pu être testées
# depuis cet environnement de développement (le domaine feeds.leparisien.fr
# est hors de l'allowlist réseau de la sandbox). À valider depuis l'infra de
# production avant activation — exécuter nlp/sources/rss_collector.py en
# standalone et vérifier le nombre d'entrées retournées par flux.
#
# Les autres URLs (Les Echos, La Tribune, etc.) sont des suppositions
# raisonnables non vérifiées — à auditer/corriger avant mise en production,
# au même titre que les sources du module scraper_immobilier_emploi.py.

FLUX_RSS = [
    # Presse économique nationale — filtrage par mots-clés appliqué ensuite
    # ⚠️ URLs non vérifiées — à confirmer avant activation
    {"nom": "Les Echos - Industrie",        "url": "https://www.lesechos.fr/industrie-services/rss.xml",        "categorie": "nationale_eco", "verifie": False},
    {"nom": "La Tribune - Entreprises",      "url": "https://www.latribune.fr/rss/rubriques/entreprises-finance.html", "categorie": "nationale_eco", "verifie": False},

    # Presse locale / régionale — URLs réelles trouvées via annuaire de flux
    # (atlasflux.saynete.com) mais non testées depuis cette sandbox — à
    # confirmer en production avant activation du DAG
    {"nom": "Le Parisien - Val d'Oise",      "url": "https://feeds.leparisien.fr/leparisien/rss/val-d-oise-95",  "categorie": "locale", "verifie": False},
    {"nom": "Le Parisien - Seine-et-Marne",  "url": "https://feeds.leparisien.fr/leparisien/rss/seine-et-marne-77", "categorie": "locale", "verifie": False},
    {"nom": "Le Parisien - Économie/Entreprises", "url": "https://feeds.leparisien.fr/arc/outboundfeeds/leparisien/rss/economie/business/?outputType=xml", "categorie": "nationale_eco", "verifie": False},
    {"nom": "Le Parisien - Économie/Emploi", "url": "https://feeds.leparisien.fr/arc/outboundfeeds/leparisien/rss/economie/emploi/?outputType=xml", "categorie": "nationale_eco", "verifie": False},
    {"nom": "Le Parisien - Transports IDF",  "url": "https://feeds.leparisien.fr/arc/outboundfeeds/leparisien/rss/info-paris-ile-de-france-oise/transports/?outputType=xml", "categorie": "locale", "verifie": False},
    {"nom": "Actu.fr - Val d'Oise",          "url": "https://actu.fr/val-doise/rss",                              "categorie": "locale", "verifie": False},

    # Sources institutionnelles — communiqués officiels
    # ⚠️ URLs non vérifiées — à confirmer avant activation
    {"nom": "ADP - Communiqués",             "url": "https://www.parisaeroport.fr/rss/communiques-presse.xml",   "categorie": "institutionnelle", "verifie": False},
]

# Mots-clés de filtrage géographique pour la presse nationale (qui ne parle
# pas systématiquement de RPDF — il faut filtrer après coup)
MOTS_CLES_TERRITOIRE = [
    "roissy", "cdg", "charles-de-gaulle", "charles de gaulle",
    "gonesse", "goussainville", "sarcelles", "villiers-le-bel",
    "garges", "mitry-mory", "mitry mory", "claye-souilly", "claye souilly",
    "villeparisis", "louvres", "moussy-le-neuf", "marly-la-ville",
    "le mesnil-amelot", "mesnil amelot", "vémars", "thillay",
    "val-d'oise", "val d'oise", "95 ", "paris nord 2",
    "aéroport paris", "groupe adp", "air france cargo",
]


def valider_registre_flux() -> pd.DataFrame:
    """
    Teste chaque flux du registre et retourne son statut réel (nombre
    d'entrées, erreur éventuelle). À exécuter depuis l'infra de production
    avant d'activer un flux marqué 'verifie: False' dans le registre, et à
    rejouer périodiquement (un flux RSS peut disparaître ou changer d'URL).
    """
    resultats = []
    for flux in FLUX_RSS:
        try:
            parsed = feedparser.parse(flux["url"])
            statut = "OK" if parsed.entries else "VIDE_OU_INVALIDE"
            nb_entrees = len(parsed.entries)
            erreur = str(parsed.get("bozo_exception", "")) if parsed.bozo else None
        except Exception as e:
            statut = "ERREUR"
            nb_entrees = 0
            erreur = str(e)

        resultats.append({
            "nom": flux["nom"],
            "url": flux["url"],
            "categorie": flux["categorie"],
            "statut": statut,
            "nb_entrees": nb_entrees,
            "erreur": erreur,
        })

    return pd.DataFrame(resultats)



    """
    Parcourt tous les flux RSS du registre, filtre sur les mots-clés
    territoriaux pour la presse nationale (la presse locale est gardée
    intégralement — elle est déjà géographiquement pertinente par nature),
    et retourne un DataFrame d'articles structurés.
    """
    articles = []
    date_limite = datetime.now() - timedelta(days=jours_recents)

    for flux in FLUX_RSS:
        try:
            parsed = feedparser.parse(flux["url"])
        except Exception as e:
            log.warning("Flux illisible '%s' : %s", flux["nom"], e)
            continue

        if parsed.bozo and not parsed.entries:
            log.warning("Flux vide ou malformé : %s", flux["nom"])
            continue

        for entry in parsed.entries:
            titre = entry.get("title", "")
            resume = _nettoyer_html(entry.get("summary", entry.get("description", "")))
            url = entry.get("link", "")
            date_pub = _parser_date(entry)

            if date_pub and date_pub < date_limite:
                continue

            # Filtrage territorial pour la presse nationale uniquement
            if flux["categorie"] == "nationale_eco":
                texte_complet = (titre + " " + resume).lower()
                if not any(mc in texte_complet for mc in MOTS_CLES_TERRITOIRE):
                    continue

            articles.append(ArticlePresse(
                titre=titre,
                resume=resume[:500],
                url=url,
                source=flux["nom"],
                date_publication=date_pub.isoformat() if date_pub else datetime.now().isoformat(),
                categorie=flux["categorie"],
            ))

        log.info("Flux '%s' : %d articles retenus", flux["nom"], len(parsed.entries))

    df = pd.DataFrame([asdict(a) for a in articles])
    if not df.empty:
        df = df.drop_duplicates(subset=["url"])
    return df


def _nettoyer_html(texte: str) -> str:
    """Retire les balises HTML résiduelles des résumés RSS."""
    return re.sub(r"<[^>]+>", " ", texte).strip()


def _parser_date(entry) -> datetime | None:
    """Parse la date de publication d'une entrée RSS, plusieurs formats possibles."""
    for champ in ["published_parsed", "updated_parsed"]:
        if hasattr(entry, champ) and getattr(entry, champ):
            import time
            return datetime.fromtimestamp(time.mktime(getattr(entry, champ)))
    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== Validation du registre de flux RSS ===")
    df_validation = valider_registre_flux()
    print(df_validation.to_string())
    print(f"\nFlux fonctionnels : {(df_validation['statut']=='OK').sum()} / {len(df_validation)}")

    print("\n=== Collecte (flux fonctionnels uniquement) ===")
    df = collecter_flux_rss(jours_recents=14)
    print(f"{len(df)} articles collectés")
    if not df.empty:
        print(df[["titre", "source", "categorie"]].to_string())
