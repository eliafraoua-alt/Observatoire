"""
Modèle 3 — Risque de dévitalisation commerciale

Cible : taux de vacance projeté à N+2 dans les zones à dominante commerciale.
Utilise un proxy de vacance (cf feature_store.taux_vacance_proxy) en l'absence
de données de terrain réelles — l'amélioration prioritaire de ce modèle est
l'intégration d'enquêtes de terrain annuelles (module 5 de l'observatoire).
"""

from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from pathlib import Path

try:
    from sklearn.ensemble import GradientBoostingRegressor
except ImportError:
    GradientBoostingRegressor = None

from sklearn.model_selection import LeaveOneOut
from sklearn.metrics import mean_absolute_error

MODEL_DIR = Path(__file__).parent.parent / "artifacts"
MODEL_DIR.mkdir(exist_ok=True)


def train_devitalisation_model(df: pd.DataFrame, feature_cols: list[str]) -> dict:
    if GradientBoostingRegressor is None:
        raise ImportError("pip install scikit-learn")

    # On se concentre sur les zones à dominante commerciale — le risque de
    # dévitalisation n'a de sens que pour ce sous-ensemble
    df_commerce = df[df["secteur_dominant"] == "commerce"].copy()

    if len(df_commerce) < 8:
        return {
            "status": "insufficient_data",
            "n_zones_commerce": len(df_commerce),
            "warning": (
                "Moins de 8 zones à dominante commerciale identifiées — "
                "échantillon trop faible pour un modèle robuste. "
                "Utiliser le score de risque sectoriel brut en attendant."
            ),
        }

    X = df_commerce[feature_cols].fillna(0)
    y = df_commerce["taux_vacance_proxy"].values

    model = GradientBoostingRegressor(
        max_depth=2,
        n_estimators=80,
        learning_rate=0.05,
        subsample=0.8,
        random_state=42,
    )
    model.fit(X, y)

    loo = LeaveOneOut()
    preds, truths = [], []
    for train_idx, test_idx in loo.split(X):
        m = GradientBoostingRegressor(max_depth=2, n_estimators=80, learning_rate=0.05, random_state=42)
        m.fit(X.iloc[train_idx], y[train_idx])
        preds.append(m.predict(X.iloc[test_idx])[0])
        truths.append(y[test_idx][0])

    mae = round(float(mean_absolute_error(truths, preds)), 3)

    joblib.dump(
        {"model": model, "feature_cols": feature_cols, "mae_loo": mae},
        MODEL_DIR / "devitalisation.joblib",
    )

    return {
        "status": "trained",
        "n_zones_commerce": len(df_commerce),
        "mae_loo": mae,
        "avertissement": (
            "Cible = proxy calculé (pas de mesure terrain de vacance réelle). "
            "Priorité absolue : lancer une enquête terrain annuelle (module 5 "
            "de l'observatoire) pour obtenir une vraie variable de vacance "
            "et réentraîner ce modèle sur des données observées."
        ),
    }


def predict_devitalisation(zone_features: pd.DataFrame) -> dict:
    artifact = joblib.load(MODEL_DIR / "devitalisation.joblib")
    model = artifact["model"]
    feature_cols = artifact["feature_cols"]

    X = zone_features[feature_cols].fillna(0)
    taux_vacance_pred = model.predict(X)[0]
    taux_vacance_pred = float(np.clip(taux_vacance_pred, 0, 1))

    if taux_vacance_pred >= 0.5:
        statut = "alerte — requalification à anticiper"
    elif taux_vacance_pred >= 0.3:
        statut = "vigilance — suivi renforcé recommandé"
    else:
        statut = "stable"

    return {
        "taux_vacance_projete_pct": round(taux_vacance_pred * 100, 1),
        "statut": statut,
        "mae_loo_modele": artifact["mae_loo"],
    }
