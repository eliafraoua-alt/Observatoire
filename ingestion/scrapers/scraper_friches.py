"""
Scraper UC1 — Foncier et friches (Cartofriches / Cerema)
Telecharge le CSV national et filtre sur Val-d'Oise (95) et Seine-et-Marne (77).
Source : data.gouv.fr — Licence Ouverte 2.0
"""

from __future__ import annotations
import logging
import os
import tempfile
from datetime import date
import duckdb
import requests
import pandas as pd

log = logging.getLogger(__name__)

CARTOFRICHES_CSV_URL = (
    "https://www.data.gouv.fr/api/1/datasets/r/74feb3ed-5f9f-4ef8-8fab-b0128d569a99"
)
DEPARTEMENTS = ["95", "77"]

DDL_FRICHES = """
CREATE TABLE IF NOT EXISTS friches (
    site_id             VARCHAR,
    site_nom            VARCHAR,
    site_type           VARCHAR,
    site_adresse        VARCHAR,
    commune             VARCHAR,
    code_commune        VARCHAR,
    departement         VARCHAR,
    surface_ha          DOUBLE,
    statut              VARCHAR,
    type_projet         VARCHAR,
    occupation          VARCHAR,
    securite            VARCHAR,
    site_url            VARCHAR,
    latitude            DOUBLE,
    longitude           DOUBLE,
    date_identification VARCHAR,
    date_extraction     VARCHAR
)
"""


def scrape_friches(db_path="warehouse.duckdb", departements=None):
    if departements is None:
        departements = DEPARTEMENTS

    log.info("Telechargement Cartofriches (~25 Mo)...")
    try:
        resp = requests.get(CARTOFRICHES_CSV_URL, timeout=180)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error(f"Erreur : {e}")
        return {"total": 0, "erreurs": 1}

    tmp_path = os.path.join(tempfile.gettempdir(), "cartofriches_tmp.csv")
    with open(tmp_path, "wb") as f:
        f.write(resp.content)
    log.info(f"Taille : {os.path.getsize(tmp_path)} octets")

    try:
        df = pd.read_csv(
            tmp_path, sep=";", encoding="utf-8", quotechar='"',
            dtype=str, on_bad_lines="skip", low_memory=False,
        )
    except Exception as e:
        log.error(f"Erreur lecture CSV : {e}")
        return {"total": 0, "erreurs": 1}

    cols = [c.lower() for c in df.columns]
    df.columns = cols
    log.info(f"Colonnes ({len(cols)}) : {list(cols[:20])}")

    # Colonnes du schéma CNIG Cartofriches
    col_id       = "site_id"
    col_nom      = "site_nom" if "site_nom" in cols else None
    col_type     = "site_type" if "site_type" in cols else None
    col_adresse  = "site_adresse" if "site_adresse" in cols else None
    col_commune  = "comm_nom" if "comm_nom" in cols else None
    col_code_com = "comm_insee" if "comm_insee" in cols else None
    col_surface  = next((c for c in cols if "surface" in c), None)
    col_statut   = "site_statut" if "site_statut" in cols else None
    col_projet   = "site_reconv_type" if "site_reconv_type" in cols else None
    col_occ      = "site_occupation" if "site_occupation" in cols else None
    col_sec      = "site_securite" if "site_securite" in cols else None
    col_url      = "site_url" if "site_url" in cols else None
    col_lat      = next((c for c in cols if c in ["latitude", "lat", "y_wgs84"]), None)
    col_lon      = next((c for c in cols if c in ["longitude", "lon", "x_wgs84"]), None)
    col_date     = "site_identif_date" if "site_identif_date" in cols else None

    log.info(f"Mapping : id={col_id}, commune={col_commune}, code={col_code_com}, surface={col_surface}")

    # Filtrer par département via comm_insee
    if col_code_com:
        df["_dept"] = df[col_code_com].astype(str).str[:2]
        df_filtered = df[df["_dept"].isin(departements)].copy()
    else:
        log.warning("Colonne code commune non trouvee")
        df_filtered = pd.DataFrame()

    log.info(f"Lignes apres filtrage dept {departements} : {len(df_filtered)}")

    con = duckdb.connect(db_path)
    con.execute(DDL_FRICHES)
    existing_ids = {r[0] for r in con.execute("SELECT COALESCE(site_id,'') FROM friches").fetchall()}

    today = date.today().isoformat()
    inserted = 0

    for _, row in df_filtered.iterrows():
        def v(col):
            if not col:
                return None
            val = row.get(col)
            return None if pd.isna(val) or str(val) in ("NA", "nan", "None", "") else str(val)

        def vf(col):
            val = v(col)
            try:
                return float(val) if val else None
            except Exception:
                return None

        site_id = v(col_id)
        if site_id in existing_ids:
            continue

        dept = str(row.get("_dept", ""))[:2] if "_dept" in row.index else None

        con.execute("INSERT INTO friches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
            site_id, v(col_nom), v(col_type), v(col_adresse),
            v(col_commune), v(col_code_com), dept,
            vf(col_surface), v(col_statut), v(col_projet),
            v(col_occ), v(col_sec), v(col_url),
            vf(col_lat), vf(col_lon), v(col_date), today
        ])
        inserted += 1

    stats = {
        "total": con.execute("SELECT COUNT(*) FROM friches").fetchone()[0],
        "nouveaux": inserted,
        "par_departement": {},
        "erreurs": 0
    }
    for d in departements:
        n = con.execute(f"SELECT COUNT(*) FROM friches WHERE departement='{d}'").fetchone()[0]
        stats["par_departement"][d] = n

    con.commit()
    con.close()
    log.info(f"Friches : {stats}")
    return stats


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db = os.environ.get("DUCKDB_PATH", "warehouse.duckdb")
    print(f"Connexion a {db}")

    # Vider la table pour recharger proprement
    con = duckdb.connect(db)
    try:
        con.execute("DELETE FROM friches")
        con.commit()
        print("Table friches videe pour rechargement")
    except Exception:
        pass
    con.close()

    stats = scrape_friches(db_path=db)
    print(f"\nResultat : {stats}")

    if stats["total"] > 0:
        con = duckdb.connect(db)
        print("\nApercu :")
        rows = con.execute("""
            SELECT site_id, site_nom, commune, departement, surface_ha, statut
            FROM friches LIMIT 5
        """).fetchall()
        for r in rows:
            print(f"  {r}")
        con.close()
