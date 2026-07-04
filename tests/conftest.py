"""
Configuration pytest partagée. S'assure que les chemins d'import fonctionnent
de manière identique en local et dans le CI GitHub Actions.
"""
import sys
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent
for sous_module in ["api", "ml", "nlp/extraction", "nlp/sources", "ingestion/scrapers"]:
    chemin = ROOT / sous_module
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

# Force la base en mémoire et le seed mock pour tous les tests
os.environ.setdefault("DUCKDB_PATH", ":memory:")
os.environ.setdefault("SEED_MOCK", "true")
os.environ.setdefault("API_KEY", "")

import pytest
import duckdb
from datetime import date
from fastapi.testclient import TestClient


def _create_test_db() -> duckdb.DuckDBPyConnection:
    """Crée une base DuckDB en mémoire avec les tables et données mock."""
    con = duckdb.connect(":memory:")
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
            zone VARCHAR, commune VARCHAR, anomaly_score DOUBLE,
            is_anomaly BOOLEAN, evolution_pct DOUBLE, effectif_2026 INTEGER
        )
    """)

    mock_data = [
        ("ZAE Mitry-Compans", "Mitry-Mory", 5981, 6315, 5.6, 295, 335, "nikonoff_2026", today),
        ("Paris Nord 2", "Roissy CDG", 9408, 8801, -6.5, 300, 401, "nikonoff_2026", today),
        ("Plateforme CDG", "Le Mesnil-Amelot", 9794, 5390, -45.0, 154, 157, "nikonoff_2026", today),
        ("Tissonvilliers 2", "Sarcelles", 3705, 2565, -30.8, 426, 350, "nikonoff_2026", today),
        ("Butte aux Bergers", "Louvres", 45, 636, 1313.0, 21, 52, "nikonoff_2026", today),
        ("Parc Mail", "Gonesse", 819, 1166, 42.4, 21, 47, "nikonoff_2026", today),
        ("CC Sentiers", "Claye-Souilly", 1767, 1409, -20.3, 160, 126, "nikonoff_2026", today),
        ("Parc CDG Goussainville", "Goussainville", 1827, 1700, -7.0, 239, 276, "nikonoff_2026", today),
        ("Portes de Vémars", "Vémars", 484, 684, 41.3, 13, 17, "nikonoff_2026", today),
        ("ZA Barogne", "Moussy-le-Neuf", 829, 1625, 96.0, 62, 75, "nikonoff_2026", today),
    ]
    for row in mock_data:
        con.execute("INSERT INTO emploi_zae VALUES (?,?,?,?,?,?,?,?,?)", list(row))

    con.execute("""
        INSERT INTO alertes_bodacc VALUES
        ('12345678901234','Transport Roissy SAS','Gonesse','95500',
         'LIQUIDATION','2026-06-28',true,'bodacc','{}')
    """.format(today))

    return con


@pytest.fixture(scope="session", autouse=True)
def patch_get_db(monkeypatch_session):
    """Remplace get_db() par une connexion en mémoire pour tous les tests."""
    import main as api_main
    _db = _create_test_db()
    monkeypatch_session.setattr(api_main, "get_db", lambda: _db)


@pytest.fixture(scope="session")
def monkeypatch_session():
    from pytest import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="session")
def client_sans_auth():
    import main as api_main
    _db = _create_test_db()
    api_main.get_db = lambda: _db
    return TestClient(api_main.app)


@pytest.fixture(scope="session")
def client_avec_auth():
    import main as api_main
    import os
    os.environ["API_KEY"] = "cle-de-test-12345"
    api_main.API_KEY = "cle-de-test-12345"
    _db = _create_test_db()
    api_main.get_db = lambda: _db
    return TestClient(api_main.app)