#!/usr/bin/env python3
"""
Entraînement initial des 3 modèles ML — à exécuter une première fois
après le premier pipeline d'ingestion, avant que le DAG mensuel ne prenne le relais.

Usage :
    docker compose exec api python ml/train_initial.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import duckdb
from features.feature_store import build_feature_table, get_feature_columns


def main():
    db_path = "/data/warehouse.duckdb"
    print(f"Connexion au warehouse : {db_path}")
    con = duckdb.connect(db_path)

    print("\n── Construction des features ──")
    df = build_feature_table(con)
    print(f"  {len(df)} zones disponibles")

    if len(df) < 10:
        print("⚠️  Moins de 10 zones disponibles — les modèles seront peu fiables.")
        print("   Lancez d'abord le DAG observatoire_rpdf_ingestion pour charger plus de données.")

    print("\n── Modèle 1 : Prévision d'emploi ──")
    try:
        from models.prevision_emploi import train_quantile_models
        cols = get_feature_columns("prevision_emploi")
        result = train_quantile_models(df, cols)
        print(f"  Statut : {result['status']}")
        print(f"  MAE (Leave-One-Out) : {result.get('mae_loo')}")
        print(f"  ⚠️  {result.get('warning', '')}")
    except Exception as e:
        print(f"  ❌ Erreur : {e}")

    print("\n── Modèle 2 : Scoring de défaillance ──")
    try:
        from models.scoring_defaillance import build_training_set, train_scoring_model
        df_train = build_training_set(con)
        cols = get_feature_columns("scoring_defaillance")
        df_train = df_train.merge(df[["zone"] + cols], on="zone", how="left", suffixes=("", "_f"))
        result = train_scoring_model(df_train, cols)
        print(f"  Statut : {result['status']}")
        if result["status"] == "trained":
            print(f"  AUC (validation croisée) : {result.get('auc_cv_moyen')}")
            print(f"  ⚠️  {result.get('avertissement_majeur', '')}")
        else:
            print(f"  ⚠️  {result.get('warning', '')}")
    except Exception as e:
        print(f"  ❌ Erreur : {e}")

    print("\n── Modèle 3 : Dévitalisation commerciale ──")
    try:
        from models.devitalisation import train_devitalisation_model
        cols = get_feature_columns("devitalisation")
        result = train_devitalisation_model(df, cols)
        print(f"  Statut : {result['status']}")
        if result["status"] == "trained":
            print(f"  MAE (Leave-One-Out) : {result.get('mae_loo')}")
        else:
            print(f"  ⚠️  {result.get('warning', '')}")
    except Exception as e:
        print(f"  ❌ Erreur : {e}")

    con.close()
    print("\n✅ Entraînement initial terminé. Les artefacts sont dans ml/artifacts/")
    print("   Le DAG observatoire_rpdf_ml_training prendra le relais le 1er du mois prochain.")


if __name__ == "__main__":
    main()
