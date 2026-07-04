"""
Scraper UC5 — Eau potable et assainissement (Hub'Eau / SISPEA)
Endpoint : https://hubeau.eaufrance.fr/api/v0/indicateurs_services/communes
Source   : SISPEA — Licence Ouverte 2.0
Usage    : python ingestion/scrapers/scraper_eau.py
"""

from __future__ import annotations
import logging
import os
import time
from datetime import date
import duckdb
import requests

log = logging.getLogger(__name__)

HUBEAU_BASE = "https://hubeau.eaufrance.fr/api/v0/indicateurs_services/communes"
DEPARTEMENTS = ["95", "77"]
ANNEES = [2017, 2018, 2019]  # Dernières données disponibles dans Hub'Eau SISPEA
PAUSE = 0.3

DDL_EAU = """
CREATE TABLE IF NOT EXISTS eau_indicateurs (
    service_id          VARCHAR,
    nom_service         VARCHAR,
    type_service        VARCHAR,
    commune             VARCHAR,
    code_commune        VARCHAR,
    departement         VARCHAR,
    annee               INTEGER,
    nb_habitants        DOUBLE,
    prix_eau_m3         DOUBLE,
    rendement_reseau    DOUBLE,
    indice_pertes       DOUBLE,
    taux_conformite     DOUBLE,
    taux_desserte       DOUBLE,
    conformite_eru      DOUBLE,
    source              VARCHAR,
    date_extraction     VARCHAR
)
"""


def _fetch_page(departement: str, annee: int, offset: int = 0, size: int = 200) -> dict:
    params = {
        "code_departement": departement,
        "annee": annee,
        "size": size,
        "offset": offset,
    }
    try:
        resp = requests.get(HUBEAU_BASE, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log.error(f"Erreur Hub'Eau dept={departement} annee={annee}: {e}")
        return {"data": [], "count": 0}


def _parse(record: dict, departement: str) -> list[dict]:
    """Un enregistrement peut contenir plusieurs services — on retourne une liste."""
    indics = record.get("indicateurs", {}) or {}
    code_commune = str(record.get("code_commune_insee", "") or "")
    commune = str(record.get("nom_commune", "") or "")
    annee = int(record.get("annee", 0) or 0)

    codes_service = record.get("codes_service", [])
    noms_service = record.get("noms_service", [])

    def sf(key):
        val = indics.get(key)
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    # Détecter le type de service depuis les noms
    noms_str = " ".join(str(n) for n in noms_service).lower()
    if "assainissement" in noms_str:
        type_service = "AC"
    else:
        type_service = "AEP"

    service_id = str(codes_service[0]) if codes_service else ""
    nom_service = str(noms_service[0]) if noms_service else ""

    return [{
        "service_id":       service_id,
        "nom_service":      nom_service,
        "type_service":     type_service,
        "commune":          commune,
        "code_commune":     code_commune,
        "departement":      departement,
        "annee":            annee,
        # Eau potable
        "nb_habitants":     sf("D101.0"),
        "prix_eau_m3":      sf("D102.0"),
        "rendement_reseau": sf("P101.1"),
        "indice_pertes":    sf("P102.1"),
        "taux_conformite":  sf("P108.3"),
        # Assainissement
        "taux_desserte":    sf("P201.1"),
        "conformite_eru":   sf("P203.3"),
        "source":           "hubeau_sispea",
        "date_extraction":  date.today().isoformat(),
    }]


def scrape_eau(db_path="warehouse.duckdb", departements=None, annees=None):
    if departements is None:
        departements = DEPARTEMENTS
    if annees is None:
        annees = ANNEES

    con = duckdb.connect(db_path)
    con.execute(DDL_EAU)

    stats = {"total": 0, "par_departement": {}, "erreurs": 0}

    for dept in departements:
        stats["par_departement"][dept] = 0

        for annee in annees:
            offset = 0
            size = 200

            while True:
                data = _fetch_page(dept, annee, offset=offset, size=size)
                records = data.get("data", [])
                total_count = data.get("count", 0)

                if not records:
                    break

                log.info(f"dept={dept} annee={annee} offset={offset}: {len(records)} enregistrements (total={total_count})")

                for record in records:
                    parsed_list = _parse(record, dept)
                    for parsed in parsed_list:
                        existing = con.execute(
                            "SELECT COUNT(*) FROM eau_indicateurs WHERE service_id=? AND annee=? AND code_commune=?",
                            [parsed["service_id"], parsed["annee"], parsed["code_commune"]]
                        ).fetchone()[0]
                        if existing == 0:
                            con.execute(
                                "INSERT INTO eau_indicateurs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                list(parsed.values())
                            )
                            stats["total"] += 1
                            stats["par_departement"][dept] += 1

                offset += size
                if offset >= total_count:
                    break
                time.sleep(PAUSE)

    if stats["total"] > 0:
        r = con.execute("""
            SELECT ROUND(AVG(rendement_reseau),1), ROUND(AVG(prix_eau_m3),2)
            FROM eau_indicateurs
            WHERE rendement_reseau IS NOT NULL
        """).fetchone()
        stats["rendement_moyen_pct"] = r[0]
        stats["prix_moyen_m3"] = r[1]

    con.commit()
    con.close()
    log.info(f"Eau : {stats}")
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db = os.environ.get("DUCKDB_PATH", "warehouse.duckdb")
    print(f"Connexion à {db}")
    print(f"Récupération Hub'Eau depts={DEPARTEMENTS} années={ANNEES}...")
    stats = scrape_eau(db_path=db)
    print(f"\nRésultat : {stats}")

    if stats["total"] > 0:
        con = duckdb.connect(db)
        print("\nAperçu :")
        rows = con.execute("""
            SELECT commune, departement, annee, type_service,
                   ROUND(rendement_reseau,1) as rendement_pct,
                   ROUND(prix_eau_m3,2) as prix_m3,
                   ROUND(taux_desserte,1) as desserte_pct
            FROM eau_indicateurs
            ORDER BY departement, commune, annee
            LIMIT 10
        """).fetchall()
        for r in rows:
            print(f"  {r}")
        con.close()
