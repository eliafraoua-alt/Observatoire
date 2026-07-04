"""
Configuration pytest partagée.
- Chemins d'import identiques en local et CI.
- Base DuckDB partagée en mémoire (fichier temporaire) pour tous les tests.
- Monkey-patch de get_db() pour que chaque appel retourne la MÊME connexion.
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
# On utilise un fichier temporaire plutôt que :memory: car duckdb.connect(":memory:")
# crée une base DIFFÉRENTE à chaque appel — les tables seraient perdues entre requêtes.
_TMP_DB = tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False)
_TMP_DB_PATH = _TMP_DB.name
_TMP_DB.close()

os.environ["DUCKDB_PATH"] = _TMP_DB_PATH
os.environ["SEED_MOCK"] = "true"
os.environ.setdefault("API_KEY", "")

import duckdb

def _init_test_db():
    """Crée les tables et insère les données mock dans la base de test."""
    con = duckdb.connect(_TMP_DB_PATH, read_only=False)
    today = date.today().isoformat()

    con.execute("""
        CREATE TABLE IF NOT EXISTS emploi_zae (
            zone VARCHAR, commune VARCHAR,
            effectif_2021 INTEGER, effectif_2026 INTEGER,
            evolution_pct DOUBLE, etab_2021 INTEGER, etab_2026 INTEGER,
            source VARCHAR, date_extraction VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS alertes_bodacc (
            siret VARCHAR, denomination VARCHAR, commune VARCHAR,
            cp VARCHAR, type_avis VARCHAR, date_parution VARCHAR,
            alerte BOOLEAN, source VARCHAR, date_extraction VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS anomaly_scores (
            zone VARCHAR, commune VARCHAR,
            anomaly_score DOUBLE, is_anomaly BOOLEAN,
            evolution_pct DOUBLE, effectif_2026 INTEGER
        )
    """)

    # Données mock — 10 zones suffisent pour tous les tests
    if con.execute("SELECT COUNT(*) FROM emploi_zae").fetchone()[0] == 0:
        mock_data = [
            ("ZAE Mitry-Compans",    "Mitry-Mory",         5981, 6315,   5.6, 295, 335, "nikonoff_2026", today),
            ("Paris Nord 2",          "Gonesse",             9408, 8801,  -6.5, 300, 401, "nikonoff_2026", today),
            ("Plateforme CDG",        "Le Mesnil-Amelot",    9794, 5390, -45.0, 154, 157, "nikonoff_2026", today),
            ("Tissonvilliers 2",      "Sarcelles",           3705, 2565, -30.8, 426, 350, "nikonoff_2026", today),
            ("Butte aux Bergers",     "Louvres",               45,  636,1313.0,  21,  52, "nikonoff_2026", today),
            ("Parc Mail",             "Roissy-en-France",     819, 1166,  42.4,  21,  47, "nikonoff_2026", today),
            ("CC Sentiers",           "Claye-Souilly",       1767, 1409, -20.3, 160, 126, "nikonoff_2026", today),
            ("Parc CDG Goussainville","Goussainville",       1827, 1700,  -7.0, 239, 276, "nikonoff_2026", today),
            ("Portes de Vémars",      "Vémars",               484,  684,  41.3,  13,  17, "nikonoff_2026", today),
            ("ZA Barogne",            "Moussy-le-Neuf",       829, 1625,  96.0,  62,  75, "nikonoff_2026", today),
        ]
        for row in mock_data:
            con.execute("INSERT INTO emploi_zae VALUES (?,?,?,?,?,?,?,?,?)", list(row))

        con.execute(f"""
            INSERT INTO alertes_bodacc VALUES
            ('12345678901234','Transport Roissy SAS','Gonesse','95500',
             'LIQUIDATION','2026-06-28',true,'bodacc','{today}')
        """)

    con.close()


# Initialise la base une seule fois au démarrage des tests
_init_test_db()

# ── Monkey-patch de get_db ────────────────────────────────────────────────────
# On remplace get_db() par une fonction qui retourne une connexion au fichier
# de test. Chaque appel ouvre une connexion au MÊME fichier → tables partagées.
import main as _api_main

def _test_get_db():
    return duckdb.connect(_TMP_DB_PATH, read_only=False)

_api_main.get_db = _test_get_db
_api_main.DB_PATH = _TMP_DB_PATH

# ── Fixtures pytest ───────────────────────────────────────────────────────────
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client_sans_auth():
    """Client sans clé API (auth désactivée car API_KEY vide)."""
    _api_main.API_KEY = ""
    os.environ["API_KEY"] = ""
    return TestClient(_api_main.app, raise_server_exceptions=False)


@pytest.fixture(scope="session")
def client_avec_auth():
    """Client avec clé API valide."""
    _api_main.API_KEY = "cle-de-test-12345"
    os.environ["API_KEY"] = "cle-de-test-12345"
    client = TestClient(_api_main.app, raise_server_exceptions=False)
    # Réinitialise après usage pour ne pas polluer les autres tests
    yield client
    _api_main.API_KEY = ""
    os.environ["API_KEY"] = ""