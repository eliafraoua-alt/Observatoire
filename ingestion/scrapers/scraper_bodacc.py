"""
Scraper BODACC — Bulletin Officiel des Annonces Civiles et Commerciales
Récupère toutes les annonces pour le Val-d'Oise (95) et la Seine-et-Marne (77).

API : https://bodacc-datadila.opendatasoft.com (gratuite, sans clé)
Usage : python ingestion/scrapers/scraper_bodacc.py
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta

import duckdb
import requests

log = logging.getLogger(__name__)

BODACC_API = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
DEPARTEMENTS = ["95", "77"]
JOURS_HISTORIQUE = 30
PAUSE_ENTRE_REQUETES = 0.5

DDL_BODACC = """
CREATE TABLE IF NOT EXISTS bodacc_annonces (
    id                  VARCHAR,
    type_bodacc         VARCHAR,
    numero_parution     VARCHAR,
    date_parution       VARCHAR,
    denomination        VARCHAR,
    siret               VARCHAR,
    siren               VARCHAR,
    code_postal         VARCHAR,
    ville               VARCHAR,
    departement         VARCHAR,
    famille_activite    VARCHAR,
    type_annonce        VARCHAR,
    detail_json         VARCHAR,
    alerte              BOOLEAN,
    date_extraction     VARCHAR
)
"""


def _fetch_page(where_clause: str, offset: int = 0, limit: int = 100) -> dict:
    params = {
        "limit": limit,
        "offset": offset,
        "order_by": "dateparution DESC",
        "where": where_clause,
    }
    resp = requests.get(BODACC_API, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _parse_annonce(record: dict, departement: str) -> dict:
    type_annonce = (
        record.get("familleavis_lib", "")
        or record.get("typeavis_lib", "")
        or record.get("familleavis", "")
        or ""
    )
    mots_cles_alerte = ["liquidation", "redressement", "sauvegarde", "cessation", "faillite", "proc"]
    alerte = any(m in type_annonce.lower() for m in mots_cles_alerte)

    siret = siren = ""
    if isinstance(record.get("etablissement"), dict):
        siret = record["etablissement"].get("siret", "")
        siren = record["etablissement"].get("siren", "")

    denomination = ""
    pub = record.get("publicationavis_consommables") or record.get("denomination") or ""
    if isinstance(pub, str):
        try:
            pub_parsed = json.loads(pub)
            if isinstance(pub_parsed, list) and pub_parsed:
                denomination = pub_parsed[0].get("denomination", "")
        except Exception:
            denomination = pub
    elif isinstance(pub, list) and pub:
        denomination = pub[0].get("denomination", "") if isinstance(pub[0], dict) else str(pub[0])

    annonce_id = (
        record.get("id")
        or record.get("numerodannonce")
        or str(abs(hash(json.dumps(record, sort_keys=True))))
    )

    return {
        "id": str(annonce_id),
        "type_bodacc": record.get("typeavis", record.get("familleavis", "")),
        "numero_parution": str(record.get("numeroannonce", "")),
        "date_parution": str(record.get("dateparution", "")),
        "denomination": str(denomination)[:500],
        "siret": siret,
        "siren": siren,
        "code_postal": record.get("cp", record.get("code_postal", "")) or "",
        "ville": record.get("ville", "") or "",
        "departement": departement,
        "famille_activite": record.get("familleavis_lib", "") or "",
        "type_annonce": type_annonce,
        "detail_json": json.dumps(record, ensure_ascii=False)[:2000],
        "alerte": alerte,
        "date_extraction": date.today().isoformat(),
    }


def scrape_bodacc(
    db_path: str = "warehouse.duckdb",
    jours: int = JOURS_HISTORIQUE,
    departements: list = None,
) -> dict:
    if departements is None:
        departements = DEPARTEMENTS

    date_fin = date.today()
    date_debut = date_fin - timedelta(days=jours)

    con = duckdb.connect(db_path)
    con.execute(DDL_BODACC)

    stats = {"total": 0, "alertes": 0, "erreurs": 0, "departements": {}}

    for dept in departements:
        stats["departements"][dept] = 0
        offset = 0
        limit = 100

        where = (
            f"numerodepartement='{dept}' "
            f"AND dateparution>='{date_debut.isoformat()}' "
            f"AND dateparution<='{date_fin.isoformat()}'"
        )

        while True:
            try:
                data = _fetch_page(where, offset=offset, limit=limit)
            except requests.RequestException as e:
                log.error(f"Erreur API dept={dept}: {e}")
                stats["erreurs"] += 1
                break

            records = data.get("results", data.get("records", []))
            if not records:
                break

            for record in records:
                parsed = _parse_annonce(record, dept)
                try:
                    existing = con.execute(
                        "SELECT COUNT(*) FROM bodacc_annonces WHERE id=?", [parsed["id"]]
                    ).fetchone()[0]
                    if existing == 0:
                        con.execute(
                            "INSERT INTO bodacc_annonces VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            [
                                parsed["id"], parsed["type_bodacc"], parsed["numero_parution"],
                                parsed["date_parution"], parsed["denomination"], parsed["siret"],
                                parsed["siren"], parsed["code_postal"], parsed["ville"],
                                parsed["departement"], parsed["famille_activite"],
                                parsed["type_annonce"], parsed["detail_json"],
                                parsed["alerte"], parsed["date_extraction"],
                            ]
                        )
                        stats["total"] += 1
                        stats["departements"][dept] += 1
                        if parsed["alerte"]:
                            stats["alertes"] += 1
                except Exception as e:
                    log.warning(f"Erreur insertion: {e}")
                    stats["erreurs"] += 1

            total_count = data.get("total_count", data.get("nhits", 0))
            offset += limit
            if offset >= total_count:
                break

            time.sleep(PAUSE_ENTRE_REQUETES)

        log.info(f"Département {dept} : {stats['departements'][dept]} annonces")

    con.commit()
    con.close()
    log.info(f"BODACC : {stats['total']} annonces, {stats['alertes']} alertes")
    return stats


def sync_vers_alertes_bodacc(db_path: str = "warehouse.duckdb") -> int:
    con = duckdb.connect(db_path)
    con.execute("""
        CREATE TABLE IF NOT EXISTS alertes_bodacc (
            siret VARCHAR, denomination VARCHAR, commune VARCHAR,
            cp VARCHAR, type_avis VARCHAR, date_parution VARCHAR,
            alerte BOOLEAN, source VARCHAR, date_extraction VARCHAR
        )
    """)

    ids_existants = {
        r[0] for r in con.execute(
            "SELECT COALESCE(siret,'') || COALESCE(date_parution,'') FROM alertes_bodacc WHERE source='bodacc'"
        ).fetchall()
    }

    nouvelles = con.execute(
        "SELECT siret, denomination, ville, code_postal, type_annonce, date_parution, date_extraction "
        "FROM bodacc_annonces WHERE alerte=true"
    ).fetchall()

    n = 0
    for row in nouvelles:
        siret, denom, ville, cp, type_avis, date_par, date_ext = row
        cle = (siret or "") + (str(date_par) or "")
        if cle not in ids_existants:
            con.execute(
                "INSERT INTO alertes_bodacc VALUES (?,?,?,?,?,?,?,?,?)",
                [siret, denom, ville, cp, type_avis, str(date_par), True, "bodacc", str(date_ext)]
            )
            n += 1

    con.commit()
    con.close()
    return n


if __name__ == "__main__":
    import os
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db = os.environ.get("DUCKDB_PATH", "warehouse.duckdb")
    print(f"Connexion à {db}")
    print("Récupération des annonces BODACC (30 derniers jours)...")

    stats = scrape_bodacc(db_path=db, jours=30)
    print(f"Résultat : {stats}")

    print("Synchronisation vers alertes_bodacc...")
    n = sync_vers_alertes_bodacc(db_path=db)
    print(f"{n} nouvelles alertes synchronisées")
