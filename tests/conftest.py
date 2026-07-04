"""
Configuration pytest partagée.

Stratégie v8 : fichier DuckDB partagé + commit explicite + nouvelles connexions.
- DuckDB connections ne sont PAS thread-safe.
- FastAPI exécute les endpoints dans des threads (anyio.to_thread.run_sync).
- Solution : fichier partagé, commit explicite, get_db() crée une nouvelle
  connexion au même fichier à chaque appel (thread-safe).
"""
import sys
import os
from pathlib import Path
from datetime import date

# ── Chemins d'import ──────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
for sous_module in ["api", "ml", "nlp/extraction", "nlp/sources", "ingestion/scrapers"]:
    chemin = ROOT / sous_module
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

# ── Chemin de la base de test ─────────────────────────────────────────────────
_DB = "/tmp/obs_test.duckdb"
if os.path.exists(_DB):
    os.remove(_DB)
# Supprimer aussi le fichier WAL s'il existe
for ext in [".wal", ".tmp"]:
    if os.path.exists(_DB + ext):
        os.remove(_DB + ext)

# CRITIQUE : définir DUCKDB_PATH AVANT d'importer main
os.environ["DUCKDB_PATH"] = _DB
os.environ["SEED_MOCK"] = "false"
os.environ["API_KEY"] = ""

import duckdb


def _setup_db():
    """Crée les tables et insère les données, avec commit explicite."""
    con = duckdb.connect(_DB)
    today = date.today().isoformat()

    con.execute("""
        CREATE TABLE emploi_zae (
            zone VARCHAR, commune VARCHAR,
            effectif_2021 INTEGER, effectif_2026 INTEGER,
            evolution_pct DOUBLE, etab_2021 INTEGER, etab_2026 INTEGER,
            source VARCHAR, date_extraction VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE alertes_bodacc (
            siret VARCHAR, denomination VARCHAR, commune VARCHAR,
            cp VARCHAR, type_avis VARCHAR, date_parution VARCHAR,
            alerte BOOLEAN, source VARCHAR, date_extraction VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE anomaly_scores (
            zone VARCHAR, commune VARCHAR,
            anomaly_score DOUBLE, is_anomaly BOOLEAN,
            evolution_pct DOUBLE, effectif_2026 INTEGER
        )
    """)
    con.execute("""
        CREATE TABLE presse_analysee (
            titre VARCHAR, url VARCHAR, source VARCHAR,
            date_publication VARCHAR, date_extraction VARCHAR,
            theme_principal VARCHAR, theme_score DOUBLE,
            sentiment DOUBLE, entites_entreprises VARCHAR,
            communes_rpdf_mentionnees VARCHAR
        )
    """)

    mock_data = [
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
        ("A Park Le Thillay",      "Le Thillay",           890,  884,  -0.7,  24,  56, "nikonoff_2026", today),
        ("Grande Couture Ouest",   "Gonesse",              167,  610, 265.3,  35, 180, "nikonoff_2026", today),
        ("Le Moulin",              "Roissy CDG",          1949, 2982,  53.0, 174, 170, "nikonoff_2026", today),
        ("ZA Sablons",             "Claye-Souilly",        345, 1066, 209.0,  82, 112, "nikonoff_2026", today),
        ("Parc Breche",            "Goussainville",       1480, 1568,   5.9, 102, 101, "nikonoff_2026", today),
    ]
    for row in mock_data:
        con.execute("INSERT INTO emploi_zae VALUES (?,?,?,?,?,?,?,?,?)", list(row))

    con.execute(
        "INSERT INTO alertes_bodacc VALUES (?,?,?,?,?,?,?,?,?)",
        ["12345678901234", "Transport Roissy SAS", "Gonesse", "95500",
         "LIQUIDATION", "2026-06-28", True, "bodacc", today]
    )

    # Commit explicite pour s'assurer que les données sont persistées
    con.commit()
    con.close()


_setup_db()

# Vérification que le fichier est bien créé et contient des données
_check = duckdb.connect(_DB)
_n = _check.execute("SELECT COUNT(*) FROM emploi_zae").fetchone()[0]
assert _n == 15, f"Base mal initialisée : {_n} lignes au lieu de 15"
_check.close()

# ── Import de main APRÈS setup ────────────────────────────────────────────────
import main as _api_main

assert _api_main.DB_PATH == _DB, f"DB_PATH={_api_main.DB_PATH!r} != {_DB!r}"


def _test_get_db():
    """Nouvelle connexion thread-safe au fichier de test."""
    return duckdb.connect(_DB)


# Patch de get_db au niveau module
_api_main.get_db = _test_get_db

# ── Fixtures pytest ───────────────────────────────────────────────────────────
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client_sans_auth():
    _api_main.API_KEY = ""
    with TestClient(_api_main.app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture(scope="session")
def client_avec_auth():
    _api_main.API_KEY = "cle-de-test-12345"
    with TestClient(_api_main.app, raise_server_exceptions=False) as client:
        yield client
    _api_main.API_KEY = ""
