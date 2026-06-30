"""
Tests du connecteur de scraping conforme (robots.txt) et du module de
détection de signaux NLP.

Exécution : pytest tests/test_scraping_et_nlp.py -v
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "ingestion" / "scrapers"))
sys.path.insert(0, str(Path(__file__).parent.parent / "nlp" / "extraction"))


class TestRobotsComplianceGate:
    """
    Tests du garde-fou de conformité robots.txt — le principe non négociable
    du projet : aucun scraping sans vérification préalable.
    """

    def test_refuse_url_si_robots_txt_illisible(self, monkeypatch):
        from robots_gate import RobotsComplianceGate

        gate = RobotsComplianceGate()
        # URL sur un domaine qui n'existe pas — robots.txt illisible
        result = gate.check("https://ce-domaine-n-existe-vraiment-pas-12345.invalid/page")
        assert result.autorise is False
        assert "illisible" in result.raison or "refus" in result.raison.lower()

    def test_cache_robots_txt_par_domaine(self):
        """Le robots.txt d'un domaine ne doit être téléchargé qu'une fois (cache)."""
        from robots_gate import RobotsComplianceGate

        gate = RobotsComplianceGate()
        assert len(gate._cache) == 0
        gate.check("https://exemple-domaine-invalide.test/page1")
        nb_apres_premier_appel = len(gate._cache)
        gate.check("https://exemple-domaine-invalide.test/page2")
        # Le deuxième appel sur le même domaine ne doit pas re-télécharger
        assert len(gate._cache) == nb_apres_premier_appel

    def test_fetch_if_allowed_retourne_none_si_refuse(self, monkeypatch):
        """
        Test du comportement non négociable : un refus de conformité
        retourne None silencieusement, ne lève jamais d'exception, et
        ne contourne jamais le refus.
        """
        from robots_gate import fetch_if_allowed, _gate

        # On force le gate à refuser systématiquement pour ce test
        class FakeCheck:
            autorise = False
            raison = "test"
            crawl_delay = None

        monkeypatch.setattr(_gate, "check", lambda url: FakeCheck())
        result = fetch_if_allowed("https://exemple.fr/page")
        assert result is None

    def test_audit_source_compte_correctement_chemins_autorises(self, monkeypatch):
        from robots_gate import audit_source, RobotsComplianceGate

        class FakeCheckAutorise:
            autorise = True
            raison = "ok"
            crawl_delay = None

        gate = RobotsComplianceGate()
        monkeypatch.setattr(gate, "check", lambda url: FakeCheckAutorise())

        import robots_gate
        monkeypatch.setattr(robots_gate, "_gate", gate)

        result = audit_source("https://exemple.fr", ["/path1", "/path2"])
        assert result["chemins_autorises"] == 2
        assert result["verdict"] == "intégrable"


class TestSignalDetection:
    """
    Tests du module signal_detection.py — la couche qui transforme le corpus
    de presse analysé en signaux exploitables. Logique pure pandas, testable
    sans dépendre des modèles NLP lourds.
    """

    @pytest.fixture
    def corpus_test(self):
        return pd.DataFrame([
            {
                "titre": "Amazon annonce un nouvel entrepôt à Mitry-Mory",
                "url": "https://ex.fr/1", "source": "Test", "date_publication": "2026-06-25",
                "entites_entreprises": ["Amazon"], "communes_rpdf_mentionnees": ["mitry-mory"],
                "theme_principal": "projet", "theme_score": 0.85,
                "sentiment": "positif", "sentiment_score": 0.7, "pertinence_territoriale": True,
            },
            {
                "titre": "Geodis supprime 120 postes à Mitry-Mory",
                "url": "https://ex.fr/2", "source": "Test", "date_publication": "2026-06-27",
                "entites_entreprises": ["Geodis"], "communes_rpdf_mentionnees": ["mitry-mory"],
                "theme_principal": "fermeture", "theme_score": 0.9,
                "sentiment": "negatif", "sentiment_score": 0.8, "pertinence_territoriale": True,
            },
            {
                "titre": "Article sans rapport avec le territoire",
                "url": "https://ex.fr/3", "source": "Test", "date_publication": "2026-06-28",
                "entites_entreprises": [], "communes_rpdf_mentionnees": [],
                "theme_principal": "hors_sujet", "theme_score": 0.95,
                "sentiment": "neutre", "sentiment_score": 0.6, "pertinence_territoriale": False,
            },
        ])

    def test_detecter_projets_filtre_correctement(self, corpus_test):
        from signal_detection import detecter_projets
        projets = detecter_projets(corpus_test)
        assert len(projets) == 1
        assert projets.iloc[0]["titre"] == "Amazon annonce un nouvel entrepôt à Mitry-Mory"

    def test_detecter_alertes_filtre_correctement(self, corpus_test):
        from signal_detection import detecter_alertes_difficulte
        alertes = detecter_alertes_difficulte(corpus_test)
        assert len(alertes) == 1
        assert alertes.iloc[0]["titre"] == "Geodis supprime 120 postes à Mitry-Mory"

    def test_seuil_confiance_exclut_articles_peu_fiables(self, corpus_test):
        from signal_detection import detecter_projets
        # Seuil très élevé : même l'article projet à 0.85 ne doit pas passer
        projets = detecter_projets(corpus_test, seuil_confiance=0.99)
        assert len(projets) == 0

    def test_indice_climat_articles_vides_ne_plante_pas(self):
        from signal_detection import calculer_indice_climat_economique
        result = calculer_indice_climat_economique(pd.DataFrame())
        assert result["indice"] is None
        assert "avertissement" in result

    def test_indice_climat_calcule_dans_les_bornes(self, corpus_test):
        from signal_detection import calculer_indice_climat_economique
        result = calculer_indice_climat_economique(corpus_test)
        assert -1 <= result["indice"] <= 1

    def test_classement_communes_compte_mentions_multiples(self, corpus_test):
        from signal_detection import classement_communes_par_mentions
        classement = classement_communes_par_mentions(corpus_test)
        mitry = classement[classement["commune"] == "mitry-mory"]
        assert len(mitry) == 1
        assert mitry.iloc[0]["nb_mentions"] == 2  # mentionné dans 2 articles

    def test_synthese_hebdomadaire_structure_complete(self, corpus_test):
        from signal_detection import generer_synthese_hebdomadaire
        synthese = generer_synthese_hebdomadaire(corpus_test)
        for champ in ["date_synthese", "n_articles_analyses", "indice_climat",
                      "projets_detectes", "alertes_difficulte", "classement_communes"]:
            assert champ in synthese
        assert synthese["n_articles_analyses"] == 3


class TestDetectionCommunes:
    def test_detecte_commune_simple(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "nlp" / "extraction"))
        from nlp_pipeline import _detecter_communes
        result = _detecter_communes("Une entreprise s'installe à Gonesse")
        assert "gonesse" in result

    def test_detecte_plusieurs_communes(self):
        from nlp_pipeline import _detecter_communes
        result = _detecter_communes("Entre Mitry-Mory et Claye-Souilly, le secteur se développe")
        assert "mitry-mory" in result
        assert "claye-souilly" in result

    def test_aucune_commune_retourne_liste_vide(self):
        from nlp_pipeline import _detecter_communes
        result = _detecter_communes("Un article qui ne parle d'aucune commune du territoire")
        assert result == []
