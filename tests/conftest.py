"""
Configuration pytest partagée.
"""
import sys
import os
import tempfile
from pathlib import Path
from datetime import date

# ── Chemins d'import ──────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
for sous_module in ["api", "ml", "nlp/extraction", "nlp/sources", "ingestion/scrapers"]:
    chemin = ROOT / sous_module
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

# ── Base de données de test ───────────────────────────────────────────────────
_TMP_DB_PATH = os.path.join(tempfile.gettempdir(), "observatoire_test.duckdb")
if os.path.exists(_TMP_DB_PATH):
    os.remove(_TMP_DB_PATH)

# CRITIQUE : définir DUCKDB_PATH AVANT d'importer main
os.environ["DUCKDB_PATH"] = _TMP_DB_PATH
os.environ["SEED_MOCK"] = "true"
os.environ["API_KEY"] = ""

import duckdb


def _init_test_db():
    con = duckdb.connect(_TMP_DB_PATH, read_only=False)
    today = date.today().isoformat()
    con.executemany("", []) if False else None

    for ddl in [
        """CREATE TABLE IF NOT EXISTS emploi_zae (
            zone VARCHAR, commune VARCHAR,
            effectif_2021 INTEGER, effectif_2026 INTEGER,
            evolution_pct DOUBLE, etab_2021 INTEGER, etab_2026 INTEGER,
            source VARCHAR, date_extraction VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS alertes_bodacc (
            siret VARCHAR, denomination VARCHAR, commune VARCHAR,
            cp VARCHAR, type_avis VARCHAR, date_parution VARCHAR,
            alerte BOOLEAN, source VARCHAR, date_extraction VARCHAR)""",
        """CREATE TABLE IF NOT EXISTS anomaly_scores (
            zone VARCHAR, commune VARCHAR,
            anomaly_score DOUBLE, is_anomaly BOOLEAN,
            evolution_pct DOUBLE, effectif_2026 INTEGER)""",
        """CREATE TABLE IF NOT EXISTS presse_analysee (
            titre VARCHAR, url VARCHAR, source VARCHAR,
            date_publication VARCHAR, date_extraction VARCHAR,
            theme_principal VARCHAR, theme_score DOUBLE,
            sentiment DOUBLE, entites_entreprises VARCHAR,
            communes_rpdf_mentionnees VARCHAR)""",
    ]:
        con.execute(ddl)

    if con.execute("SELECT COUNT(*) FROM emploi_zae").fetchone()[0] == 0:
        rows = [
            ("ZAE Mitry-Compans",     "Mitry-Mory",         5981, 6315,   5.6, 295, 335, "nikonoff_2026", today),
            ("Paris Nord 2",           "Gonesse",             9408, 8801,  -6.5, 300, 401, "nikonoff_2026", today),
            ("Plateforme CDG",         "Le Mesnil-Amelot",    9794, 5390, -45.0, 154, 157, "nikonoff_2026", today),
            ("Tissonvilliers 2",       "Sarcelles",           3705, 2565, -30.8, 426, 350, "nikonoff_2026", today),
            ("Butte aux Bergers",      "Louvres",               45,  636,1313.0,  21,  52, "nikonoff_2026", today),
            ("Parc Mail",              "Roissy-en-France",     819, 1166,  42.4,  21,  47, "nikonoff_2026", today),
            ("CC Sentiers",            "Claye-Souilly",       1767, 1409, -20.3, 160, 126, "nikonoff_2026", today),
            ("Parc CDG Goussainville", "Goussainville",       1827, 1700,  -7.0, 239, 276, "nikonoff_2026", today),
            ("Portes de Vémars",       "Vémars",               484,  684,  41.3,  13,  17, "nikonoff_2026", today),
            ("ZA Barogne",             "Moussy-le-Neuf",       829, 1625,  96.0,  62,  75, "nikonoff_2026", today),
        ]
        for r in rows:
            con.execute("INSERT INTO emploi_zae VALUES (?,?,?,?,?,?,?,?,?)", list(r))
        con.execute(
            "INSERT INTO alertes_bodacc VALUES (?,?,?,?,?,?,?,?,?)",
            ["12345678901234", "Transport Roissy SAS", "Gonesse", "95500",
             "LIQUIDATION", "2026-06-28", True, "bodacc", today]
        )
    con.close()


_init_test_db()

# ── Import de l'app APRÈS avoir défini DUCKDB_PATH ───────────────────────────
# Le module main lit DB_PATH = os.environ.get("DUCKDB_PATH") au niveau module.
# Si on importe avant de définir la variable, il prendra /data/warehouse.duckdb.
import main as _api_main

# Vérification que DB_PATH pointe bien vers notre base de test
assert _api_main.DB_PATH == _TMP_DB_PATH, (
    f"DB_PATH mal configuré: {_api_main.DB_PATH} != {_TMP_DB_PATH}\n"
    "Vérifier que DUCKDB_PATH est défini avant l'import de main."
)

# ── Fixtures pytest ───────────────────────────────────────────────────────────
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client_sans_auth():
    _api_main.API_KEY = ""
    return TestClient(_api_main.app, raise_server_exceptions=False)


@pytest.fixture(scope="session")
def client_avec_auth():
    _api_main.API_KEY = "cle-de-test-12345"
    client = TestClient(_api_main.app, raise_server_exceptions=False)
    yield client
    _api_main.API_KEY = ""
