"""
Connecteur de scraping conforme — vérification robots.txt obligatoire.

Principe non négociable : AUCUNE requête de scraping n'est exécutée sans
vérification préalable du robots.txt de la source. Si le robots.txt interdit
l'accès au chemin ciblé pour notre user-agent (ou pour '*'), la source est
écartée silencieusement et journalisée — jamais contournée.

Ce module ne contient aucune logique de contournement (rotation de proxy pour
échapper à un blocage, falsification de user-agent, etc.). Si une source utile
interdit le scraping, la voie à suivre est la demande de partenariat ou
d'accès API, pas le contournement technique.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

log = logging.getLogger(__name__)

USER_AGENT = "ObservatoireRPDF-Bot/1.0 (+https://roissypaysdefrance.fr/observatoire; contact=observatoire@roissypaysdefrance.fr)"
REQUEST_DELAY_SECONDS = 2.0  # délai minimum entre deux requêtes vers une même source


@dataclass
class ComplianceCheck:
    url: str
    autorise: bool
    raison: str
    crawl_delay: float | None = None


class RobotsComplianceGate:
    """
    Porte de conformité : toute URL doit passer par check() avant d'être
    récupérée. Le résultat est mis en cache par domaine pour éviter de
    re-télécharger le robots.txt à chaque requête.
    """

    def __init__(self):
        self._cache: dict[str, RobotFileParser] = {}

    def check(self, url: str) -> ComplianceCheck:
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        if domain not in self._cache:
            rp = RobotFileParser()
            rp.set_url(f"{domain}/robots.txt")
            try:
                rp.read()
                self._cache[domain] = rp
            except Exception as e:
                log.warning("Impossible de lire robots.txt pour %s : %s — accès refusé par prudence", domain, e)
                return ComplianceCheck(
                    url=url, autorise=False,
                    raison=f"robots.txt illisible ({e}) — refus par défaut",
                )

        rp = self._cache[domain]
        autorise = rp.can_fetch(USER_AGENT, url)
        crawl_delay = rp.crawl_delay(USER_AGENT)

        if not autorise:
            log.info("Scraping refusé par robots.txt : %s", url)
            return ComplianceCheck(
                url=url, autorise=False,
                raison="robots.txt interdit ce chemin pour notre user-agent",
            )

        return ComplianceCheck(
            url=url, autorise=True, raison="autorisé par robots.txt",
            crawl_delay=crawl_delay,
        )


_gate = RobotsComplianceGate()


def fetch_if_allowed(url: str, **request_kwargs) -> requests.Response | None:
    """
    Récupère une URL UNIQUEMENT si le robots.txt l'autorise.
    Retourne None et journalise si refusé — ne lève jamais d'exception
    pour un refus de conformité, ce n'est pas une erreur technique.
    """
    check = _gate.check(url)

    if not check.autorise:
        log.warning("REFUS CONFORMITÉ : %s — %s", url, check.raison)
        return None

    delay = check.crawl_delay or REQUEST_DELAY_SECONDS
    time.sleep(delay)

    headers = request_kwargs.pop("headers", {})
    headers["User-Agent"] = USER_AGENT

    try:
        resp = requests.get(url, headers=headers, timeout=20, **request_kwargs)
        resp.raise_for_status()
        return resp
    except requests.RequestException as e:
        log.error("Erreur de récupération %s : %s", url, e)
        return None


def audit_source(base_url: str, paths_souhaites: list[str]) -> dict:
    """
    Audite une source candidate avant intégration au pipeline : pour chaque
    chemin souhaité, indique s'il est autorisé. À utiliser manuellement avant
    d'ajouter un nouveau connecteur de scraping au DAG.
    """
    resultats = []
    for path in paths_souhaites:
        url = base_url.rstrip("/") + "/" + path.lstrip("/")
        check = _gate.check(url)
        resultats.append({
            "chemin": path,
            "autorise": check.autorise,
            "raison": check.raison,
            "crawl_delay": check.crawl_delay,
        })

    nb_autorises = sum(1 for r in resultats if r["autorise"])
    return {
        "source": base_url,
        "date_audit": datetime.now().isoformat(),
        "chemins_testes": len(paths_souhaites),
        "chemins_autorises": nb_autorises,
        "verdict": "intégrable" if nb_autorises == len(paths_souhaites) else "intégration partielle ou refusée",
        "detail": resultats,
    }


if __name__ == "__main__":
    # Exemple d'audit — à exécuter manuellement avant d'activer une nouvelle source
    import json
    logging.basicConfig(level=logging.INFO)

    sources_a_auditer = {
        "https://www.seloger.com": ["/immobilier-entreprise/", "/recherche.html"],
        "https://www.leboncoin.fr": ["/locaux_commerciaux/offres", "/recherche"],
        "https://www.pap.fr": ["/annonce/locations-bureaux-commerces"],
        "https://www.indeed.fr": ["/jobs", "/emplois"],
        "https://www.francetravail.fr": ["/candidat/recherche", "/accueil"],
        "https://www.data.gouv.fr": ["/fr/datasets/"],
    }

    for base_url, paths in sources_a_auditer.items():
        result = audit_source(base_url, paths)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print("---")
