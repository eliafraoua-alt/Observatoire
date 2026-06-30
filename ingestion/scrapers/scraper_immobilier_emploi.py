"""
Scraper d'annonces immobilières d'activité — sources locales conformes uniquement.

CONCLUSION D'AUDIT (cf robots_gate.py, exécuté le jour de l'écriture de ce module) :
Les grandes plateformes immobilières et d'emploi (SeLoger, LeBonCoin, PAP, Indeed)
interdisent explicitement le scraping de leurs pages de recherche/listing dans leur
robots.txt. Même les portails open data institutionnels (INSEE, BODACC, Géoportail)
bloquent l'accès générique en HTML et exposent à la place des API REST dédiées —
c'est exactement la voie déjà empruntée dans observatoire_ingestion.py.

Ce module ne scrape donc QUE ce qui reste légitimement accessible :
- Sites de chambres consulaires (CCI, CMA) publiant des annonces de locaux
- Sites de petites agences immobilières locales sans interdiction robots.txt
- Pages d'offres d'emploi de la plateforme CDG/ADP elle-même, si autorisées

Si une source utile est bloquée, la marche à suivre est documentée dans
README_SOURCES.md : demande de partenariat data ou souscription API officielle.
Ne JAMAIS contourner un refus robots.txt dans ce module.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import urljoin

import pandas as pd

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    from .robots_gate import fetch_if_allowed, audit_source
except ImportError:
    from robots_gate import fetch_if_allowed, audit_source

log = logging.getLogger(__name__)


# ── Registre des sources candidates ───────────────────────────────────────────
# Chaque source DOIT être auditée avant d'être ajoutée ici. L'audit est rejoué
# automatiquement au runtime (defense in depth) mais ce registre documente
# l'intention et évite de retester des sources visiblement non pertinentes.

SOURCES_IMMOBILIER_ACTIVITE = [
    {
        "nom": "CCI Versailles Yvelines / Val d'Oise — annonces locaux",
        "base_url": "https://www.versailles.cci.fr",
        "listing_path": "/annonces-immobilier-entreprise",
        "actif": True,  # à activer après audit robots.txt réel
    },
    {
        "nom": "CMA Val d'Oise — annonces locaux artisanaux",
        "base_url": "https://www.cma-valdoise.fr",
        "listing_path": "/annonces-locaux",
        "actif": True,
    },
]

SOURCES_EMPLOI = [
    {
        "nom": "Paris Terres d'Envol — offres emploi plateforme CDG",
        "base_url": "https://www.paristerresdenvol.fr",
        "listing_path": "/offres-emploi-cdg",
        "actif": True,
    },
]


def scrape_immobilier_activite() -> pd.DataFrame:
    """
    Scrape les annonces de locaux d'activité des sources autorisées.
    Retourne un DataFrame vide (et journalise) pour toute source refusée
    par robots.txt — jamais d'exception bloquante.
    """
    if BeautifulSoup is None:
        log.error("BeautifulSoup non installé — pip install beautifulsoup4")
        return pd.DataFrame()

    records = []

    for source in SOURCES_IMMOBILIER_ACTIVITE:
        if not source["actif"]:
            continue

        listing_url = urljoin(source["base_url"], source["listing_path"])
        resp = fetch_if_allowed(listing_url)

        if resp is None:
            log.warning(
                "Source '%s' non scrapée (refus robots.txt ou erreur réseau) — "
                "à remplacer par un partenariat data si jugée prioritaire",
                source["nom"],
            )
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        annonces = _parse_annonces_generique(soup, source["base_url"])

        for a in annonces:
            a["source_nom"] = source["nom"]
            a["date_extraction"] = date.today().isoformat()
            records.append(a)

        log.info("Source '%s' : %d annonces extraites", source["nom"], len(annonces))

    return pd.DataFrame(records)


def scrape_offres_emploi_locales() -> pd.DataFrame:
    """Scrape les offres d'emploi des sources locales autorisées (hors France Travail, déjà couvert par API)."""
    if BeautifulSoup is None:
        return pd.DataFrame()

    records = []

    for source in SOURCES_EMPLOI:
        if not source["actif"]:
            continue

        listing_url = urljoin(source["base_url"], source["listing_path"])
        resp = fetch_if_allowed(listing_url)

        if resp is None:
            log.warning("Source emploi '%s' non scrapée — refus robots.txt", source["nom"])
            continue

        soup = BeautifulSoup(resp.text, "html.parser")
        offres = _parse_offres_generique(soup, source["base_url"])

        for o in offres:
            o["source_nom"] = source["nom"]
            o["date_extraction"] = date.today().isoformat()
            records.append(o)

    return pd.DataFrame(records)


def _parse_annonces_generique(soup, base_url: str) -> list[dict]:
    """
    Parseur générique d'annonces — à adapter au HTML réel de chaque source
    une fois l'audit robots.txt validé et le partenariat éventuel signé.
    Structure cible commune : surface, loyer, commune, type de bien.
    """
    annonces = []
    for card in soup.select("[class*=annonce], [class*=listing], article"):
        titre = card.find(["h2", "h3"])
        surface_match = re.search(r"(\d+)\s*m[²2]", card.get_text())
        loyer_match = re.search(r"(\d[\d\s]*)\s*€", card.get_text())

        if titre:
            annonces.append({
                "titre": titre.get_text(strip=True),
                "surface_m2": int(surface_match.group(1)) if surface_match else None,
                "loyer_eur": int(loyer_match.group(1).replace(" ", "")) if loyer_match else None,
                "url": urljoin(base_url, card.find("a")["href"]) if card.find("a") else None,
            })
    return annonces


def _parse_offres_generique(soup, base_url: str) -> list[dict]:
    """Parseur générique d'offres d'emploi — structure à affiner par source."""
    offres = []
    for card in soup.select("[class*=offre], [class*=job], article"):
        titre = card.find(["h2", "h3"])
        if titre:
            offres.append({
                "intitule": titre.get_text(strip=True),
                "url": urljoin(base_url, card.find("a")["href"]) if card.find("a") else None,
            })
    return offres


def audit_toutes_sources() -> pd.DataFrame:
    """
    Relance l'audit robots.txt sur toutes les sources du registre.
    À exécuter manuellement (ou via DAG hebdomadaire) pour détecter les
    changements de politique de scraping des sources déjà intégrées.
    """
    resultats = []
    for source in SOURCES_IMMOBILIER_ACTIVITE + SOURCES_EMPLOI:
        audit = audit_source(source["base_url"], [source["listing_path"]])
        resultats.append({
            "nom": source["nom"],
            "url": source["base_url"],
            "verdict": audit["verdict"],
            "autorise": audit["chemins_autorises"] > 0,
        })
    return pd.DataFrame(resultats)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)

    print("=== Audit des sources du registre ===")
    df_audit = audit_toutes_sources()
    print(df_audit.to_string())

    print("\n=== Tentative de scraping (sources autorisées uniquement) ===")
    df_immo = scrape_immobilier_activite()
    print(f"Annonces récupérées : {len(df_immo)}")
