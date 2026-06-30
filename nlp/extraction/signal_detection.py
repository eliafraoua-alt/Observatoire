"""
Détection de signaux territoriaux à partir du corpus de presse analysé.

Transforme une collection d'articles annotés (NER + sentiment + thème) en
signaux exploitables pour l'observatoire : projets d'implantation détectés,
alertes de difficulté économique, fréquence de mention par commune dans le
temps. C'est la couche qui rend le NLP utile pour la décision, pas juste
pour la curiosité.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

log = logging.getLogger(__name__)


def detecter_projets(df_analyse: pd.DataFrame, seuil_confiance: float = 0.5) -> pd.DataFrame:
    """Extrait les articles classés comme projet d'implantation/investissement, triés par pertinence."""
    if df_analyse.empty:
        return pd.DataFrame()

    projets = df_analyse[
        (df_analyse["theme_principal"] == "projet")
        & (df_analyse["theme_score"] >= seuil_confiance)
    ].copy()

    projets = projets.sort_values(["pertinence_territoriale", "theme_score"], ascending=False)
    return projets[["titre", "url", "source", "date_publication", "entites_entreprises",
                     "communes_rpdf_mentionnees", "theme_score", "sentiment"]]


def detecter_alertes_difficulte(df_analyse: pd.DataFrame, seuil_confiance: float = 0.5) -> pd.DataFrame:
    """Extrait les articles signalant fermeture, plan social ou difficulté financière."""
    if df_analyse.empty:
        return pd.DataFrame()

    alertes = df_analyse[
        (df_analyse["theme_principal"].isin(["fermeture", "difficulte"]))
        & (df_analyse["theme_score"] >= seuil_confiance)
    ].copy()

    alertes = alertes.sort_values(["pertinence_territoriale", "theme_score"], ascending=False)
    return alertes[["titre", "url", "source", "date_publication", "entites_entreprises",
                     "communes_rpdf_mentionnees", "theme_principal", "theme_score", "sentiment"]]


def calculer_indice_climat_economique(df_analyse: pd.DataFrame) -> dict:
    """
    Calcule un indice synthétique du climat économique perçu dans la presse,
    sur la base du sentiment moyen pondéré par la pertinence territoriale.
    Indice entre -1 (très négatif) et +1 (très positif).

    À interpréter avec prudence : c'est un indicateur de perception médiatique,
    pas une mesure économique directe — un mois avec beaucoup d'articles sur
    une seule fermeture peut faire chuter l'indice sans refléter l'ensemble
    du tissu économique.
    """
    if df_analyse.empty:
        return {"indice": None, "n_articles": 0, "avertissement": "Aucun article analysé"}

    df_pertinent = df_analyse[df_analyse["pertinence_territoriale"]]
    if df_pertinent.empty:
        df_pertinent = df_analyse  # repli sur le corpus complet si rien n'est géolocalisé

    poids_sentiment = {"positif": 1, "neutre": 0, "negatif": -1, "indetermine": 0}
    df_pertinent = df_pertinent.copy()
    df_pertinent["score_numerique"] = df_pertinent["sentiment"].map(poids_sentiment) * df_pertinent["sentiment_score"]

    indice = round(float(df_pertinent["score_numerique"].mean()), 2)

    return {
        "indice": indice,
        "interpretation": _interpreter_indice(indice),
        "n_articles": len(df_pertinent),
        "n_positifs": int((df_pertinent["sentiment"] == "positif").sum()),
        "n_negatifs": int((df_pertinent["sentiment"] == "negatif").sum()),
        "n_neutres": int((df_pertinent["sentiment"] == "neutre").sum()),
    }


def _interpreter_indice(indice: float) -> str:
    if indice is None:
        return "indéterminé"
    if indice >= 0.3:
        return "climat médiatique favorable"
    elif indice <= -0.3:
        return "climat médiatique dégradé"
    return "climat médiatique neutre/mixte"


def classement_communes_par_mentions(df_analyse: pd.DataFrame) -> pd.DataFrame:
    """
    Classe les communes RPDF par fréquence de mention dans la presse,
    avec ventilation par thème. Une commune qui apparaît soudainement
    beaucoup plus que d'habitude est un signal à investiguer.
    """
    if df_analyse.empty:
        return pd.DataFrame()

    lignes = []
    for _, row in df_analyse.iterrows():
        for commune in row.get("communes_rpdf_mentionnees", []) or []:
            lignes.append({
                "commune": commune,
                "theme": row["theme_principal"],
                "sentiment": row["sentiment"],
            })

    if not lignes:
        return pd.DataFrame()

    df_mentions = pd.DataFrame(lignes)
    classement = (
        df_mentions.groupby("commune")
        .agg(nb_mentions=("theme", "count"))
        .reset_index()
        .sort_values("nb_mentions", ascending=False)
    )

    # Ventilation thématique par commune
    pivot = pd.crosstab(df_mentions["commune"], df_mentions["theme"])
    classement = classement.merge(pivot, left_on="commune", right_index=True, how="left").fillna(0)

    return classement


def generer_synthese_hebdomadaire(df_analyse: pd.DataFrame) -> dict:
    """
    Génère la synthèse hebdomadaire complète — format prêt pour digest
    email ou affichage dashboard. Rassemble tous les indicateurs du module.
    """
    return {
        "date_synthese": datetime.now().isoformat(),
        "n_articles_analyses": len(df_analyse),
        "indice_climat": calculer_indice_climat_economique(df_analyse),
        "projets_detectes": detecter_projets(df_analyse).to_dict(orient="records"),
        "alertes_difficulte": detecter_alertes_difficulte(df_analyse).to_dict(orient="records"),
        "classement_communes": classement_communes_par_mentions(df_analyse).to_dict(orient="records"),
    }


if __name__ == "__main__":
    # Test avec un corpus synthétique pour valider la logique d'agrégation
    # sans dépendre des modèles ML lourds (cf nlp_pipeline.py)
    import pandas as pd

    corpus_test = pd.DataFrame([
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
            "titre": "Un nouveau commerce ouvre à Gonesse",
            "url": "https://ex.fr/3", "source": "Test", "date_publication": "2026-06-28",
            "entites_entreprises": [], "communes_rpdf_mentionnees": ["gonesse"],
            "theme_principal": "recrutement", "theme_score": 0.6,
            "sentiment": "positif", "sentiment_score": 0.5, "pertinence_territoriale": True,
        },
    ])

    print("=== Test du module de détection de signaux ===")
    synthese = generer_synthese_hebdomadaire(corpus_test)
    import json
    print(json.dumps(synthese, indent=2, ensure_ascii=False))
