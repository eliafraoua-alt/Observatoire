"""
Modèle 2 — Scoring de risque de défaillance d'entreprise

Cible : probabilité qu'un établissement connaisse une procédure collective
(liquidation, redressement) dans les 12 prochains mois.

Limite honnête : sans accès aux ratios financiers (Ellisphère/Diane/Infogreffe),
le modèle s'appuie sur des proxies structurels (âge, secteur, taille, dynamique
de zone). C'est un modèle de second rang tant que les données financières ne
sont pas intégrées — à présenter comme un indicateur d'attention, pas un verdict.
"""

from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from pathlib import Path

try:
    import xgboost as xgb
except ImportError:
    xgb = None

from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score, precision_recall_curve

MODEL_DIR = Path(__file__).parent.parent / "artifacts"
MODEL_DIR.mkdir(exist_ok=True)


def build_training_set(con) -> pd.DataFrame:
    """
    Construit le jeu d'entraînement à l'échelle établissement.
    En l'absence d'historique BODACC suffisant, génère un jeu semi-supervisé
    où la cible est approximée par les signaux disponibles — à affiner
    avec un historique réel de 24+ mois de BODACC.
    """
    df = con.execute("""
        SELECT
            e.zone, e.commune, e.effectif_2021, e.effectif_2026,
            e.evolution_pct, e.etab_2026,
            COALESCE(b.nb_alertes, 0) AS nb_alertes_zone
        FROM emploi_zae e
        LEFT JOIN (
            SELECT commune, COUNT(*) as nb_alertes
            FROM alertes_bodacc WHERE alerte = true
            GROUP BY commune
        ) b ON e.commune = b.commune
        WHERE e.source = 'nikonoff_2026'
    """).df()

    # Proxy de cible : zone fortement dégradée + alertes BODACC = risque élevé
    # ATTENTION : c'est un proxy d'amorçage, pas une vraie cible supervisée.
    # À remplacer dès que 24 mois d'historique BODACC réel sont disponibles.
    df["risque_defaillance"] = (
        (df["evolution_pct"] < -15) | (df["nb_alertes_zone"] >= 2)
    ).astype(int)

    return df


def train_scoring_model(df: pd.DataFrame, feature_cols: list[str]) -> dict:
    if xgb is None:
        raise ImportError("pip install xgboost")

    X = df[feature_cols].fillna(0)
    y = df["risque_defaillance"].values

    if y.sum() < 3 or (len(y) - y.sum()) < 3:
        return {
            "status": "insufficient_data",
            "warning": (
                "Moins de 3 exemples positifs ou négatifs — le modèle ne peut "
                "pas être entraîné de façon fiable. Continuez à accumuler des "
                "données BODACC avant la mise en production de ce modèle."
            ),
        }

    model = xgb.XGBClassifier(
        max_depth=3,
        n_estimators=100,
        learning_rate=0.05,
        reg_alpha=0.5,
        reg_lambda=1.0,
        scale_pos_weight=(len(y) - y.sum()) / max(y.sum(), 1),  # gestion déséquilibre classes
        eval_metric="logloss",
    )
    model.fit(X, y)

    # Validation croisée stratifiée (5 folds si possible, sinon moins)
    n_folds = min(5, int(y.sum()), int(len(y) - y.sum()))
    auc_scores = []
    if n_folds >= 2:
        skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
        for train_idx, test_idx in skf.split(X, y):
            m = xgb.XGBClassifier(max_depth=3, n_estimators=100, learning_rate=0.05,
                                   eval_metric="logloss")
            m.fit(X.iloc[train_idx], y[train_idx])
            proba = m.predict_proba(X.iloc[test_idx])[:, 1]
            if len(set(y[test_idx])) > 1:
                auc_scores.append(roc_auc_score(y[test_idx], proba))

    joblib.dump({"model": model, "feature_cols": feature_cols}, MODEL_DIR / "scoring_defaillance.joblib")

    return {
        "status": "trained",
        "n_samples": len(df),
        "n_positifs": int(y.sum()),
        "auc_cv_moyen": round(float(np.mean(auc_scores)), 2) if auc_scores else None,
        "avertissement_majeur": (
            "Modèle entraîné sur un proxy de cible (évolution dégradée + alertes "
            "BODACC), pas sur des défaillances réellement observées dans le temps. "
            "À considérer comme un indicateur d'attention, pas un score prédictif "
            "validé. Réentraîner avec un historique BODACC de 24+ mois avant tout "
            "usage opérationnel auprès des entreprises."
        ),
    }


def score_zone(zone_features: pd.DataFrame) -> dict:
    artifact = joblib.load(MODEL_DIR / "scoring_defaillance.joblib")
    model = artifact["model"]
    feature_cols = artifact["feature_cols"]

    X = zone_features[feature_cols].fillna(0)
    proba = model.predict_proba(X)[0, 1]

    if proba >= 0.6:
        niveau = "élevé"
    elif proba >= 0.3:
        niveau = "modéré"
    else:
        niveau = "faible"

    return {
        "probabilite_risque": round(float(proba), 2),
        "niveau_risque": niveau,
        "fiabilite": "indicatif — proxy de cible, à valider avec données financières réelles",
    }


if __name__ == "__main__":
    import duckdb, sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from features.feature_store import build_feature_table, get_feature_columns

    con = duckdb.connect("/data/warehouse.duckdb")
    df = build_training_set(con)
    cols = get_feature_columns("scoring_defaillance")
    # Fusion avec features structurelles
    feat_df = build_feature_table(con)
    df = df.merge(feat_df[["zone"] + cols], on="zone", how="left", suffixes=("", "_feat"))
    result = train_scoring_model(df, cols)
    print(result)
