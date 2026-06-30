"""
Modèle 1 — Prévision d'emploi par zone (régression quantile LightGBM)

Approche : apprentissage transversal sur les 67 zones plutôt que série temporelle
par zone (impossible avec seulement 2 points). Le modèle apprend la relation
entre caractéristiques structurelles et taux de croissance observé 2021→2026,
puis projette cette relation pour estimer un intervalle de confiance à N+k.

Sortie : P10 / P50 / P90 — jamais un chiffre unique sans incertitude.
"""

from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from pathlib import Path

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

from sklearn.model_selection import LeaveOneOut
from sklearn.metrics import mean_absolute_error

MODEL_DIR = Path(__file__).parent.parent / "artifacts"
MODEL_DIR.mkdir(exist_ok=True)

QUANTILES = [0.1, 0.5, 0.9]


def train_quantile_models(df: pd.DataFrame, feature_cols: list[str]) -> dict:
    """
    Entraîne 3 modèles LightGBM (un par quantile) sur la croissance observée.

    Avec n=67 zones, on évite le surapprentissage en :
    - limitant la profondeur des arbres (max_depth=3)
    - imposant un nombre minimum d'échantillons par feuille (min_child_samples=5)
    - validant en Leave-One-Out plutôt qu'un simple train/test split
    """
    if lgb is None:
        raise ImportError("pip install lightgbm")

    X = df[feature_cols].fillna(0)
    y = df["evolution_pct"].values

    models = {}
    params_base = dict(
        max_depth=3,
        num_leaves=7,
        min_child_samples=5,
        learning_rate=0.05,
        n_estimators=150,
        reg_alpha=0.5,      # régularisation L1 forte : peu de données
        reg_lambda=0.5,     # régularisation L2 forte
        verbose=-1,
    )

    for q in QUANTILES:
        model = lgb.LGBMRegressor(objective="quantile", alpha=q, **params_base)
        model.fit(X, y)
        models[f"q{int(q*100)}"] = model

    # ── Validation Leave-One-Out (seule méthode honnête avec n=67) ────────────
    loo_errors = _validate_loo(X, y, params_base)

    # ── Sauvegarde ──────────────────────────────────────────────────────────
    joblib.dump(
        {"models": models, "feature_cols": feature_cols, "mae_loo": loo_errors},
        MODEL_DIR / "prevision_emploi.joblib",
    )

    return {
        "status": "trained",
        "n_samples": len(df),
        "mae_loo": loo_errors,
        "warning": (
            "MAE calculé en Leave-One-Out sur 67 échantillons — intervalle de "
            "confiance large attendu, ne pas sur-interpréter la précision"
        ),
    }


def _validate_loo(X: pd.DataFrame, y: np.ndarray, params: dict) -> float:
    """Validation Leave-One-Out : seule approche fiable avec un échantillon aussi petit."""
    loo = LeaveOneOut()
    preds, truths = [], []

    for train_idx, test_idx in loo.split(X):
        model = lgb.LGBMRegressor(objective="quantile", alpha=0.5, **params)
        model.fit(X.iloc[train_idx], y[train_idx])
        pred = model.predict(X.iloc[test_idx])[0]
        preds.append(pred)
        truths.append(y[test_idx][0])

    return round(float(mean_absolute_error(truths, preds)), 2)


def predict_zone(zone_features: pd.DataFrame, horizon_years: int = 3) -> dict:
    """
    Prédit l'évolution d'emploi pour une zone donnée, avec intervalle de confiance.
    horizon_years : projection au-delà de 2026 (extrapolation du taux annuel prédit)
    """
    artifact = joblib.load(MODEL_DIR / "prevision_emploi.joblib")
    models = artifact["models"]
    feature_cols = artifact["feature_cols"]

    X = zone_features[feature_cols].fillna(0)

    pred_q10 = models["q10"].predict(X)[0]
    pred_q50 = models["q50"].predict(X)[0]
    pred_q90 = models["q90"].predict(X)[0]

    effectif_actuel = zone_features["effectif_2021"].values[0] * (
        1 + zone_features.get("evolution_pct", pd.Series([0])).values[0] / 100
    )

    # Conversion taux 5 ans → projection à horizon
    taux_annuel_q50 = (1 + pred_q50 / 100) ** (1 / 5) - 1

    projections = []
    base_effectif = effectif_actuel
    for i in range(1, horizon_years + 1):
        base_effectif *= (1 + taux_annuel_q50)
        projections.append({
            "annee": 2026 + i,
            "p10": round(effectif_actuel * (1 + (1 + pred_q10/100)**(1/5) - 1) ** i),
            "p50": round(base_effectif),
            "p90": round(effectif_actuel * (1 + (1 + pred_q90/100)**(1/5) - 1) ** i),
        })

    return {
        "evolution_pct_p10": round(pred_q10, 1),
        "evolution_pct_p50": round(pred_q50, 1),
        "evolution_pct_p90": round(pred_q90, 1),
        "intervalle_confiance": f"[{round(pred_q10,1)}%, {round(pred_q90,1)}%]",
        "mae_loo_modele": artifact["mae_loo"],
        "projections": projections,
        "methode": "LightGBM quantile regression — apprentissage transversal 67 zones",
    }


if __name__ == "__main__":
    import duckdb
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from features.feature_store import build_feature_table, get_feature_columns

    con = duckdb.connect("/data/warehouse.duckdb")
    df = build_feature_table(con)
    cols = get_feature_columns("prevision_emploi")
    result = train_quantile_models(df, cols)
    print(result)
