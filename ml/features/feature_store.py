"""
Feature store — construction des variables prédictives pour les 3 modèles ML.

Principe : avec seulement 2 points temporels par zone (2021, 2026), on ne peut pas
faire de série temporelle classique. La stratégie est l'apprentissage transversal :
on utilise les 67 zones comme échantillon d'entraînement, et les caractéristiques
structurelles de chaque zone comme prédicteurs de sa dynamique.
"""

from __future__ import annotations

import duckdb
import pandas as pd
import numpy as np


SECTEUR_RISQUE = {
    # Pondération empirique du risque structurel par secteur dominant
    # (1 = très exposé à l'e-commerce/automatisation, 0 = peu exposé)
    "commerce": 0.75,
    "transport_logistique": 0.55,
    "hebergement_restauration": 0.45,
    "industrie": 0.35,
    "construction": 0.30,
    "services_admin": 0.25,
    "autre": 0.40,
}


def build_feature_table(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """
    Construit la table de features à partir des données brutes du warehouse.
    Une ligne = une ZAE, avec toutes les variables explicatives.
    """
    base = con.execute("""
        SELECT zone, commune, effectif_2021, effectif_2026, evolution_pct,
               etab_2021, etab_2026
        FROM emploi_zae
        WHERE source = 'nikonoff_2026'
    """).df()

    if base.empty:
        return base

    # ── Features dérivées de base ────────────────────────────────────────────
    base["effectif_moyen_2021"] = base["effectif_2021"] / base["etab_2021"].replace(0, 1)
    base["effectif_moyen_2026"] = base["effectif_2026"] / base["etab_2026"].replace(0, 1)
    base["delta_etab_pct"] = (
        (base["etab_2026"] - base["etab_2021"]) / base["etab_2021"].replace(0, 1) * 100
    )
    base["taille_log"] = np.log1p(base["effectif_2021"])
    base["fragmentation"] = base["effectif_moyen_2026"] - base["effectif_moyen_2021"]

    # ── Features géographiques (à enrichir avec un vrai référentiel SIG) ─────
    # En production : jointure avec une table zone_geo contenant
    # distance_gare_m, accessible_tc, distance_cdg_km, lat, lon
    base = _enrich_geo_mock(base)

    # ── Features sectorielles ─────────────────────────────────────────────────
    base = _enrich_secteur_mock(base)
    base["score_risque_sectoriel"] = base["secteur_dominant"].map(SECTEUR_RISQUE).fillna(0.4)

    # ── Features de signal faible (BODACC, offres) ────────────────────────────
    bodacc_counts = con.execute("""
        SELECT commune, COUNT(*) as nb_alertes_bodacc
        FROM alertes_bodacc
        WHERE alerte = true
        GROUP BY commune
    """).df()
    base = base.merge(bodacc_counts, on="commune", how="left")
    base["nb_alertes_bodacc"] = base["nb_alertes_bodacc"].fillna(0)

    # ── Variable cible additionnelle pour le modèle 3 (dévitalisation) ────────
    base["taux_vacance_proxy"] = np.clip(
        (base["score_risque_sectoriel"] * 0.4)
        + (np.maximum(-base["evolution_pct"], 0) / 100 * 0.4)
        + (base["nb_alertes_bodacc"] * 0.05),
        0, 1
    )

    return base


def _enrich_geo_mock(df: pd.DataFrame) -> pd.DataFrame:
    """
    MOCK — à remplacer par une vraie jointure géographique (PostGIS / SIG agglo).
    En attendant le référentiel SIG, on utilise une estimation déterministe
    basée sur le nom de la zone pour rester reproductible en dev.
    """
    np.random.seed(42)
    df["distance_gare_min"] = np.random.randint(5, 40, size=len(df))
    df["accessible_tc"] = (df["distance_gare_min"] <= 15).astype(int)
    df["distance_cdg_km"] = np.random.uniform(0.5, 25, size=len(df)).round(1)
    return df


def _enrich_secteur_mock(df: pd.DataFrame) -> pd.DataFrame:
    """
    MOCK — à remplacer par une jointure SIRENE (code NAF dominant par zone).
    Inférence grossière à partir du nom de zone en attendant l'intégration SIRENE.
    """
    def infer_secteur(zone_name: str) -> str:
        z = zone_name.lower()
        if any(k in z for k in ["mitry", "moulin", "sablons", "vémars", "barogne"]):
            return "transport_logistique"
        if any(k in z for k in ["cc ", "parc", "commercial", "brèche"]):
            return "commerce"
        if "tissonvilliers" in z:
            return "commerce"
        if "plateforme" in z or "cdg" in z.lower():
            return "transport_logistique"
        return "autre"

    df["secteur_dominant"] = df["zone"].apply(infer_secteur)
    return df


def get_feature_columns(model_name: str) -> list[str]:
    """Retourne la liste des features utilisées par chaque modèle, pour cohérence train/predict."""
    common = [
        "effectif_2021", "etab_2021", "effectif_moyen_2021",
        "taille_log", "distance_gare_min", "accessible_tc", "distance_cdg_km",
        "score_risque_sectoriel", "nb_alertes_bodacc",
    ]
    if model_name == "prevision_emploi":
        return common + ["delta_etab_pct"]
    elif model_name == "scoring_defaillance":
        return common + ["fragmentation"]
    elif model_name == "devitalisation":
        return common + ["delta_etab_pct", "fragmentation"]
    raise ValueError(f"Modèle inconnu : {model_name}")
