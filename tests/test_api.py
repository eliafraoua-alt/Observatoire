"""
Tests de l'API FastAPI — authentification, endpoints principaux, cas limites.

Exécution : pytest tests/test_api.py -v
Ces tests utilisent une base DuckDB en mémoire (DUCKDB_PATH=:memory:), donc
aucune dépendance externe (MinIO, Airflow) n'est nécessaire pour les lancer.
"""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Ajoute api/ au path pour importer main.py comme dans le conteneur Docker
sys.path.insert(0, str(Path(__file__).parent.parent / "api"))


@pytest.fixture
def client_sans_auth(monkeypatch):
    """Client de test avec authentification désactivée (API_KEY vide)."""
    monkeypatch.setenv("DUCKDB_PATH", ":memory:")
    monkeypatch.setenv("API_KEY", "")
    monkeypatch.setenv("SEED_MOCK", "true")
    # Recharge le module pour que les variables d'environnement soient relues
    if "main" in sys.modules:
        del sys.modules["main"]
    import main
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def client_avec_auth(monkeypatch):
    """Client de test avec authentification activée, clé connue."""
    monkeypatch.setenv("DUCKDB_PATH", ":memory:")
    monkeypatch.setenv("API_KEY", "cle-de-test-12345")
    monkeypatch.setenv("SEED_MOCK", "true")
    if "main" in sys.modules:
        del sys.modules["main"]
    import main
    with TestClient(main.app) as c:
        yield c


# ── Tests d'authentification ───────────────────────────────────────────────────

class TestAuthentification:
    def test_endpoint_public_racine_accessible_sans_cle(self, client_avec_auth):
        resp = client_avec_auth.get("/")
        assert resp.status_code == 200

    def test_endpoint_public_health_accessible_sans_cle(self, client_avec_auth):
        resp = client_avec_auth.get("/health")
        assert resp.status_code == 200

    def test_endpoint_protege_refuse_sans_cle(self, client_avec_auth):
        resp = client_avec_auth.get("/kpis")
        assert resp.status_code == 401

    def test_endpoint_protege_refuse_mauvaise_cle(self, client_avec_auth):
        resp = client_avec_auth.get("/kpis", headers={"X-API-Key": "mauvaise-cle"})
        assert resp.status_code == 401

    def test_endpoint_protege_accepte_bonne_cle(self, client_avec_auth):
        resp = client_avec_auth.get("/kpis", headers={"X-API-Key": "cle-de-test-12345"})
        assert resp.status_code == 200

    def test_endpoint_protege_accessible_sans_cle_si_auth_desactivee(self, client_sans_auth):
        """Si API_KEY n'est pas configurée (dev local), l'auth est désactivée."""
        resp = client_sans_auth.get("/kpis")
        assert resp.status_code == 200

    def test_ml_endpoint_est_bien_protege(self, client_avec_auth):
        """Les endpoints ML, plus coûteux en calcul, doivent aussi être protégés."""
        resp = client_avec_auth.get("/ml/prevision/ZAE%20Test")
        assert resp.status_code == 401

    def test_export_csv_est_protege(self, client_avec_auth):
        resp = client_avec_auth.get("/export/csv")
        assert resp.status_code == 401


# ── Tests fonctionnels des endpoints (auth désactivée pour isoler la logique métier) ──

class TestEndpointsKPIs:
    def test_kpis_retourne_structure_attendue(self, client_sans_auth):
        resp = client_sans_auth.get("/kpis")
        assert resp.status_code == 200
        data = resp.json()
        for champ in ["emplois_zae_total", "nb_zones", "evolution_moy_pct",
                      "zones_en_croissance", "zones_en_alerte", "poids_zae_territoire_pct"]:
            assert champ in data

    def test_kpis_emplois_total_positif(self, client_sans_auth):
        resp = client_sans_auth.get("/kpis")
        assert resp.json()["emplois_zae_total"] > 0


class TestEndpointsZAE:
    def test_liste_zae_non_vide_avec_donnees_mock(self, client_sans_auth):
        resp = client_sans_auth.get("/zae")
        assert resp.status_code == 200
        assert len(resp.json()) > 0

    def test_liste_zae_respecte_limit(self, client_sans_auth):
        resp = client_sans_auth.get("/zae", params={"limit": 3})
        assert resp.status_code == 200
        assert len(resp.json()) <= 3

    def test_filtre_commune_fonctionne(self, client_sans_auth):
        resp = client_sans_auth.get("/zae", params={"commune": "Gonesse"})
        assert resp.status_code == 200
        for zone in resp.json():
            assert "gonesse" in zone["commune"].lower()

    def test_zone_inexistante_retourne_404(self, client_sans_auth):
        resp = client_sans_auth.get("/zae/Cette Zone N'Existe Pas Du Tout")
        assert resp.status_code == 404

    def test_zone_existante_retourne_detail_complet(self, client_sans_auth):
        # On récupère d'abord une zone réelle du jeu de données mock
        zones = client_sans_auth.get("/zae").json()
        assert len(zones) > 0
        premiere_zone = zones[0]["zone"]

        resp = client_sans_auth.get(f"/zae/{premiere_zone}")
        assert resp.status_code == 200
        assert resp.json()["zone"] == premiere_zone


class TestEndpointSignaux:
    def test_signaux_retourne_score_risque(self, client_sans_auth):
        resp = client_sans_auth.get("/signaux")
        assert resp.status_code == 200
        assert "score_risque_global" in resp.json()
        assert resp.json()["score_risque_global"] in ["faible", "modéré", "élevé", "inconnu"]


class TestEndpointPrevisions:
    def test_prevision_lineaire_zone_existante(self, client_sans_auth):
        zones = client_sans_auth.get("/zae").json()
        premiere_zone = zones[0]["zone"]

        resp = client_sans_auth.get(f"/previsions/{premiere_zone}", params={"horizon": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["projections"]) == 3
        assert "avertissement" in data  # rappel obligatoire des limites de la méthode

    def test_prevision_horizon_hors_bornes_rejetee(self, client_sans_auth):
        zones = client_sans_auth.get("/zae").json()
        premiere_zone = zones[0]["zone"]
        resp = client_sans_auth.get(f"/previsions/{premiere_zone}", params={"horizon": 50})
        assert resp.status_code == 422  # validation Pydantic, horizon max = 10


class TestExportCSV:
    def test_export_csv_retourne_contenu_csv(self, client_sans_auth):
        resp = client_sans_auth.get("/export/csv")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "zone;commune" in resp.text


# ── Tests des cas limites et erreurs ──────────────────────────────────────────

class TestCasLimites:
    def test_ml_status_repond_meme_sans_modeles_entraines(self, client_sans_auth):
        """L'endpoint ne doit jamais planter, même si aucun modèle ML n'est entraîné."""
        resp = client_sans_auth.get("/ml/status")
        assert resp.status_code == 200
        for modele in ["prevision_emploi", "scoring_defaillance", "devitalisation"]:
            assert modele in resp.json()
            assert "entraine" in resp.json()[modele]

    def test_ml_prevision_sans_modele_retourne_503_pas_500(self, client_sans_auth):
        """
        Si le modèle ML n'est pas entraîné, l'API doit retourner une erreur
        explicite (503 Service Unavailable), jamais un crash 500 silencieux.
        """
        zones = client_sans_auth.get("/zae").json()
        premiere_zone = zones[0]["zone"]
        resp = client_sans_auth.get(f"/ml/prevision/{premiere_zone}")
        # Le modèle n'est pas entraîné dans ce test (pas d'artefact joblib) :
        # soit 503 (modèle absent), soit 501 (modules ML non installés)
        assert resp.status_code in (503, 501)
