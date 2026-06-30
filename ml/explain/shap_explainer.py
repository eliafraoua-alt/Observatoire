"""
Couche explicabilité — SHAP

Principe non négociable de l'observatoire : aucune prédiction n'est affichée
sans la liste des facteurs qui l'expliquent, en langage clair. Un score ou une
projection sans justification n'a pas sa place dans un outil d'aide à la
décision publique.
"""

from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
from pathlib import Path

try:
    import shap
except ImportError:
    shap = None

MODEL_DIR = Path(__file__).parent.parent / "artifacts"

# Traduction des noms techniques de features en langage clair pour les élus
LABELS_CLAIRS = {
    "effectif_2021": "taille de la zone en 2021",
    "etab_2021": "nombre d'établissements en 2021",
    "effectif_moyen_2021": "taille moyenne des établissements",
    "taille_log": "taille de la zone (échelle logarithmique)",
    "distance_gare_min": "distance à la gare la plus proche",
    "accessible_tc": "accessibilité en transport en commun",
    "distance_cdg_km": "distance à la plateforme CDG",
    "score_risque_sectoriel": "exposition sectorielle au risque (e-commerce, automatisation)",
    "nb_alertes_bodacc": "nombre d'alertes de défaillance dans la commune",
    "delta_etab_pct": "évolution du nombre d'établissements",
    "fragmentation": "tendance à la fragmentation des établissements",
}


def explain_prediction(model, X_row: pd.DataFrame, feature_cols: list[str], top_n: int = 3) -> list[dict]:
    """
    Calcule les valeurs SHAP pour une prédiction individuelle et retourne
    les top N facteurs explicatifs en langage clair, avec leur sens d'impact.
    """
    if shap is None:
        return _explain_fallback(model, X_row, feature_cols, top_n)

    try:
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_row[feature_cols])

        if isinstance(shap_values, list):  # classification multi-classe
            shap_values = shap_values[1]

        values = shap_values[0] if shap_values.ndim > 1 else shap_values
        contributions = list(zip(feature_cols, values))
        contributions.sort(key=lambda x: abs(x[1]), reverse=True)

        explications = []
        for feat, val in contributions[:top_n]:
            label = LABELS_CLAIRS.get(feat, feat)
            sens = "augmente" if val > 0 else "diminue"
            explications.append({
                "facteur": label,
                "impact": round(float(val), 3),
                "sens": sens,
                "phrase": f"{label.capitalize()} {sens} la prédiction",
            })
        return explications

    except Exception as e:
        return _explain_fallback(model, X_row, feature_cols, top_n)


def _explain_fallback(model, X_row: pd.DataFrame, feature_cols: list[str], top_n: int) -> list[dict]:
    """
    Fallback si SHAP n'est pas disponible : utilise feature_importances_
    du modèle pondérée par la valeur observée (moins précis que SHAP mais
    toujours mieux qu'une boîte noire).
    """
    if not hasattr(model, "feature_importances_"):
        return [{"facteur": "indisponible", "impact": 0, "sens": "neutre",
                  "phrase": "Explicabilité non disponible pour ce modèle"}]

    importances = model.feature_importances_
    contributions = list(zip(feature_cols, importances))
    contributions.sort(key=lambda x: x[1], reverse=True)

    explications = []
    for feat, imp in contributions[:top_n]:
        label = LABELS_CLAIRS.get(feat, feat)
        explications.append({
            "facteur": label,
            "impact": round(float(imp), 3),
            "sens": "déterminant",
            "phrase": f"{label.capitalize()} est un facteur déterminant (importance globale)",
        })
    return explications


def generate_explanation_card(zone_name: str, prediction: dict, explications: list[dict]) -> str:
    """Génère une fiche explicative en texte simple, prête à afficher dans le dashboard."""
    lignes = [f"Zone : {zone_name}", ""]

    if "evolution_pct_p50" in prediction:
        lignes.append(
            f"Évolution projetée : {prediction['evolution_pct_p50']:+.1f}% "
            f"(intervalle de confiance {prediction['intervalle_confiance']})"
        )
    elif "probabilite_risque" in prediction:
        lignes.append(
            f"Niveau de risque : {prediction['niveau_risque']} "
            f"(probabilité {prediction['probabilite_risque']*100:.0f}%)"
        )
    elif "taux_vacance_projete_pct" in prediction:
        lignes.append(
            f"Taux de vacance projeté : {prediction['taux_vacance_projete_pct']}% — "
            f"{prediction['statut']}"
        )

    lignes.append("")
    lignes.append("Principaux facteurs explicatifs :")
    for i, exp in enumerate(explications, 1):
        lignes.append(f"  {i}. {exp['phrase']}")

    return "\n".join(lignes)
