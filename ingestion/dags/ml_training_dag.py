"""
DAG : observatoire_rpdf_ml_training
Fréquence : mensuelle (1er du mois, 3h UTC)
Rôle : réentraîner les 3 modèles ML, calculer les métriques de validation,
       détecter la dérive (data drift) par rapport au mois précédent,
       et alerter si un modèle se dégrade.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.providers.slack.notifications.slack import send_slack_notification

log = logging.getLogger(__name__)

default_args = {
    "owner": "observatoire-rpdf",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
}


@dag(
    dag_id="observatoire_rpdf_ml_training",
    default_args=default_args,
    schedule="0 3 1 * *",  # 1er du mois, 3h UTC
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["rpdf", "ml", "training"],
    doc_md=__doc__,
)
def pipeline_ml_training():

    @task()
    def load_features() -> dict:
        import duckdb, sys
        sys.path.insert(0, "/opt/airflow/ml")
        from features.feature_store import build_feature_table

        con = duckdb.connect("/data/warehouse.duckdb")
        df = build_feature_table(con)
        df.to_parquet("/tmp/features_snapshot.parquet")
        con.close()

        return {"n_zones": len(df), "status": "ok"}

    @task()
    def train_model_prevision(features_result: dict) -> dict:
        import pandas as pd, sys
        sys.path.insert(0, "/opt/airflow/ml")
        from models.prevision_emploi import train_quantile_models
        from features.feature_store import get_feature_columns

        df = pd.read_parquet("/tmp/features_snapshot.parquet")
        cols = get_feature_columns("prevision_emploi")
        result = train_quantile_models(df, cols)
        log.info("Modèle prévision entraîné : %s", result)
        return result

    @task()
    def train_model_scoring(features_result: dict) -> dict:
        import duckdb, pandas as pd, sys
        sys.path.insert(0, "/opt/airflow/ml")
        from models.scoring_defaillance import build_training_set, train_scoring_model
        from features.feature_store import get_feature_columns, build_feature_table

        con = duckdb.connect("/data/warehouse.duckdb")
        df = build_training_set(con)
        cols = get_feature_columns("scoring_defaillance")
        feat_df = build_feature_table(con)
        df = df.merge(feat_df[["zone"] + cols], on="zone", how="left", suffixes=("", "_f"))
        result = train_scoring_model(df, cols)
        con.close()
        log.info("Modèle scoring entraîné : %s", result)
        return result

    @task()
    def train_model_devitalisation(features_result: dict) -> dict:
        import pandas as pd, sys
        sys.path.insert(0, "/opt/airflow/ml")
        from models.devitalisation import train_devitalisation_model
        from features.feature_store import get_feature_columns

        df = pd.read_parquet("/tmp/features_snapshot.parquet")
        cols = get_feature_columns("devitalisation")
        result = train_devitalisation_model(df, cols)
        log.info("Modèle dévitalisation entraîné : %s", result)
        return result

    @task()
    def detect_drift(prev_result: dict, scoring_result: dict, devital_result: dict) -> dict:
        """
        Compare les métriques de ce mois à celles du mois précédent (stockées
        dans une table d'historique). Alerte si dégradation significative.
        """
        import duckdb, json
        from datetime import date

        con = duckdb.connect("/data/warehouse.duckdb")
        con.execute("""
            CREATE TABLE IF NOT EXISTS ml_training_history (
                date_entrainement DATE,
                modele VARCHAR,
                metrique VARCHAR,
                valeur DOUBLE
            )
        """)

        today = date.today().isoformat()
        alertes_drift = []

        # Enregistrement des métriques courantes
        if prev_result.get("mae_loo"):
            con.execute(
                "INSERT INTO ml_training_history VALUES (?, 'prevision_emploi', 'mae_loo', ?)",
                [today, prev_result["mae_loo"]],
            )
        if scoring_result.get("auc_cv_moyen"):
            con.execute(
                "INSERT INTO ml_training_history VALUES (?, 'scoring_defaillance', 'auc', ?)",
                [today, scoring_result["auc_cv_moyen"]],
            )

        # Comparaison avec le mois précédent
        hist = con.execute("""
            SELECT modele, metrique, valeur, date_entrainement
            FROM ml_training_history
            ORDER BY date_entrainement DESC
        """).df()

        for modele in hist["modele"].unique():
            sub = hist[hist["modele"] == modele].sort_values("date_entrainement", ascending=False)
            if len(sub) >= 2:
                actuel, precedent = sub.iloc[0]["valeur"], sub.iloc[1]["valeur"]
                variation_pct = abs(actuel - precedent) / max(abs(precedent), 0.01) * 100
                if variation_pct > 30:
                    alertes_drift.append({
                        "modele": modele,
                        "variation_pct": round(variation_pct, 1),
                        "message": f"Dérive détectée sur {modele} : variation de {variation_pct:.0f}%",
                    })

        con.close()
        return {"alertes_drift": alertes_drift, "nb_alertes": len(alertes_drift)}

    f = load_features()
    p1 = train_model_prevision(f)
    p2 = train_model_scoring(f)
    p3 = train_model_devitalisation(f)
    drift = detect_drift(p1, p2, p3)

    return drift


dag_instance = pipeline_ml_training()
