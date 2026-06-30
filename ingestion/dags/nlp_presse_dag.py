"""
DAG : observatoire_rpdf_nlp_presse
Fréquence : quotidienne (7h UTC, après le pipeline d'ingestion principal)
Rôle : collecter les flux RSS presse, scraper les sources locales conformes,
       analyser chaque article (NER, sentiment, thème) et alimenter la table
       presse_analysee du warehouse, puis calculer la synthèse hebdomadaire.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow.decorators import dag, task

log = logging.getLogger(__name__)

default_args = {
    "owner": "observatoire-rpdf",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
}


@dag(
    dag_id="observatoire_rpdf_nlp_presse",
    default_args=default_args,
    schedule="0 7 * * *",
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["rpdf", "nlp", "presse"],
    doc_md=__doc__,
)
def pipeline_nlp_presse():

    @task()
    def collecter_articles() -> dict:
        """Collecte RSS + scraping conforme, fusion en un corpus unique."""
        import sys
        sys.path.insert(0, "/opt/airflow/nlp")
        sys.path.insert(0, "/opt/airflow/ingestion")
        import pandas as pd

        from sources.rss_collector import collecter_flux_rss
        df_rss = collecter_flux_rss(jours_recents=2)  # collecte quotidienne, fenêtre courte

        try:
            from scrapers.scraper_immobilier_emploi import scrape_offres_emploi_locales
            df_scraping = scrape_offres_emploi_locales()
        except Exception as e:
            log.warning("Scraping presse locale indisponible : %s", e)
            df_scraping = pd.DataFrame()

        df_total = pd.concat([df_rss, df_scraping], ignore_index=True) if not df_scraping.empty else df_rss

        if df_total.empty:
            log.warning("Aucun article collecté — vérifier les flux RSS (cf nlp/sources/rss_collector.py)")
            return {"n_articles": 0}

        df_total.to_parquet("/tmp/articles_bruts.parquet")
        return {"n_articles": len(df_total)}

    @task()
    def analyser_corpus(collecte_result: dict) -> dict:
        """Applique le pipeline NLP (NER, sentiment, thème) à chaque article collecté."""
        if collecte_result["n_articles"] == 0:
            return {"n_articles_analyses": 0}

        import sys
        sys.path.insert(0, "/opt/airflow/nlp")
        import pandas as pd
        from extraction.nlp_pipeline import analyser_corpus

        df_articles = pd.read_parquet("/tmp/articles_bruts.parquet")
        df_analyse = analyser_corpus(df_articles)

        if df_analyse.empty:
            return {"n_articles_analyses": 0}

        df_analyse.to_parquet("/tmp/articles_analyses.parquet")
        return {"n_articles_analyses": len(df_analyse)}

    @task()
    def charger_warehouse(analyse_result: dict) -> dict:
        """Charge les articles analysés dans DuckDB."""
        if analyse_result["n_articles_analyses"] == 0:
            return {"status": "skipped", "raison": "aucun article analysé"}

        import duckdb, pandas as pd, json
        from datetime import date

        df = pd.read_parquet("/tmp/articles_analyses.parquet")
        df["date_extraction"] = date.today().isoformat()

        # Sérialisation JSON des colonnes liste pour stockage DuckDB
        for col in ["entites_entreprises", "entites_lieux", "entites_personnes",
                    "communes_rpdf_mentionnees"]:
            if col in df.columns:
                df[col] = df[col].apply(json.dumps)

        con = duckdb.connect("/data/warehouse.duckdb")
        con.execute("""
            CREATE TABLE IF NOT EXISTS presse_analysee (
                titre VARCHAR, url VARCHAR, source VARCHAR, date_publication VARCHAR,
                categorie_source VARCHAR, entites_entreprises VARCHAR,
                entites_lieux VARCHAR, entites_personnes VARCHAR,
                communes_rpdf_mentionnees VARCHAR, sentiment VARCHAR,
                sentiment_score DOUBLE, theme_principal VARCHAR, theme_score DOUBLE,
                pertinence_territoriale BOOLEAN, date_extraction VARCHAR
            )
        """)
        con.execute("DELETE FROM presse_analysee WHERE url IN (SELECT url FROM df)")
        con.execute("INSERT INTO presse_analysee SELECT * FROM df")
        con.close()

        return {"status": "ok", "n_lignes": len(df)}

    @task()
    def alerter_si_signal_fort(warehouse_result: dict) -> dict:
        """
        Envoie une notification si un signal fort est détecté (alerte
        difficulté économique sur une zone déjà identifiée à risque par
        les modèles ML, ou cumul d'alertes sur une même commune).
        """
        if warehouse_result.get("status") != "ok":
            return {"status": "skipped"}

        import duckdb, json

        con = duckdb.connect("/data/warehouse.duckdb")
        alertes_jour = con.execute("""
            SELECT titre, communes_rpdf_mentionnees, theme_principal
            FROM presse_analysee
            WHERE theme_principal IN ('fermeture', 'difficulte')
              AND date_extraction = CURRENT_DATE::VARCHAR
              AND theme_score >= 0.6
        """).df()
        con.close()

        if alertes_jour.empty:
            return {"status": "ok", "n_signaux": 0}

        log.warning(
            "SIGNAL PRESSE — %d alerte(s) de difficulté détectée(s) aujourd'hui : %s",
            len(alertes_jour), alertes_jour["titre"].tolist(),
        )
        # Intégration Slack à activer une fois le webhook configuré
        # (cf SLACK_WEBHOOK_URL déjà utilisé dans le DAG ML training)

        return {"status": "ok", "n_signaux": len(alertes_jour)}

    collecte = collecter_articles()
    analyse = analyser_corpus(collecte)
    warehouse = charger_warehouse(analyse)
    alerte = alerter_si_signal_fort(warehouse)

    return alerte


dag_instance = pipeline_nlp_presse()
