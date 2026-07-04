"""
Observatoire RPDF — API REST
FastAPI + DuckDB en lecture seule.
Tous les endpoints retournent du JSON structuré.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

import duckdb
from fastapi import FastAPI, HTTPException, Query, Security, Depends
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

DB_PATH = os.environ.get("DUCKDB_PATH", "/data/warehouse.duckdb")
API_KEY = os.environ.get("API_KEY", "")
CORS_ORIGINS = [
    o.strip() for o in os.environ.get(
        "API_CORS_ORIGINS",
        "http://localhost:8501,http://localhost:8511,http://localhost:8512,"
        "http://localhost:8513,http://localhost:8514"
    ).split(",") if o.strip()
]

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(provided_key: str = Security(_api_key_header)) -> None:
    """
    Vérifie la présence et la validité de la clé API sur les endpoints
    sensibles. Si API_KEY n'est pas configurée dans l'environnement,
    l'authentification est désactivée (utile en dev local) — un avertissement
    est journalisé une seule fois au démarrage pour ne pas masquer ce choix.
    """
    if not API_KEY:
        return  # auth désactivée — voir avertissement au démarrage (lifespan)
    if not provided_key or provided_key != API_KEY:
        raise HTTPException(
            401,
            "Clé API manquante ou invalide. Fournir l'en-tête X-API-Key. "
            "Voir .env.example pour la configuration.",
        )


def get_db() -> duckdb.DuckDBPyConnection:
    """
    Retourne une nouvelle connexion DuckDB en lecture seule par requête.
    Chaque requête HTTP obtient sa propre connexion — thread-safe.
    L'appelant est responsable de fermer la connexion (via try/finally).
    """
    return duckdb.connect(DB_PATH, read_only=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Init DuckDB au démarrage et injection des données mock si vides."""
    import logging
    logger = logging.getLogger("observatoire-api")

    if not API_KEY:
        logger.warning(
            "⚠️  API_KEY non configurée — l'authentification est DÉSACTIVÉE. "
            "Tous les endpoints sont accessibles sans clé. Ne jamais déployer "
            "en production sans définir API_KEY (voir .env.example)."
        )

    # Schéma et seeding nécessitent une connexion en écriture — uniquement au
    # démarrage, avant que l'API ne serve des requêtes.
    # Le seeding mock est conditionné à SEED_MOCK=true pour ne jamais injecter
    # des données de test en production par erreur.
    SEED_MOCK = os.environ.get("SEED_MOCK", "false").lower() == "true"
    with duckdb.connect(DB_PATH, read_only=False) as con_init:
        _ensure_schema(con_init)
        if SEED_MOCK:
            _seed_mock_if_empty(con_init)
    yield
    # Pas de singleton à fermer — chaque requête gère sa propre connexion.


app = FastAPI(
    title="Observatoire Économique RPDF",
    description=(
        "API de l'Observatoire des Zones d'Activités Économiques de Roissy Pays de France.\n"
        "Sources : INSEE Flores, France Travail, BODACC, Nikonoff Conseils 2026.\n\n"
        "**Authentification** : la plupart des endpoints nécessitent l'en-tête "
        "`X-API-Key`. Voir `/health` et `/` qui restent publics."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["X-API-Key", "Content-Type"],
)

# Tous les endpoints métier passent par ce router, protégé par require_api_key.
# / et /health restent directement sur `app` (publics, nécessaires aux health
# checks Docker/ECS qui n'ont pas connaissance de la clé API).
from fastapi import APIRouter
router = APIRouter(dependencies=[Depends(require_api_key)])


# ─── Schémas Pydantic ─────────────────────────────────────────────────────────

class KPIs(BaseModel):
    emplois_zae_total: int
    nb_zones: int
    evolution_moy_pct: float
    zones_en_croissance: int
    zones_en_alerte: int
    poids_zae_territoire_pct: float
    date_extraction: str


class ZAERecord(BaseModel):
    zone: str
    commune: str
    effectif_2021: int
    effectif_2026: int
    evolution_pct: float
    etab_2021: int
    etab_2026: int
    source: str


class AlerteBODACC(BaseModel):
    siret: Optional[str]
    denomination: Optional[str]
    commune: Optional[str]
    type_avis: Optional[str]
    date_parution: Optional[str]


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/", tags=["meta"])
def root():
    return {
        "nom": "Observatoire Économique RPDF",
        "version": "1.0.0",
        "territoire": "Communauté d'Agglomération Roissy Pays de France",
        "endpoints": ["/kpis", "/zae", "/zae/{zone}", "/alertes", "/signaux", "/export/csv"],
    }


@router.get("/kpis", response_model=KPIs, tags=["indicateurs"])
def get_kpis():
    """Retourne les 6 KPIs de synthèse du territoire."""
    con = get_db()
    try:
        row = con.execute("""
            SELECT
                COALESCE(SUM(effectif_2026), 0)                                     AS emplois_zae_total,
                COUNT(DISTINCT zone)                                                 AS nb_zones,
                ROUND(AVG(evolution_pct), 1)                                        AS evolution_moy_pct,
                SUM(CASE WHEN evolution_pct > 0 THEN 1 ELSE 0 END)                 AS zones_en_croissance,
                SUM(CASE WHEN evolution_pct < -20 THEN 1 ELSE 0 END)               AS zones_en_alerte,
                ROUND(SUM(effectif_2026) * 100.0 / 179000, 1)                      AS poids_zae_territoire_pct
            FROM emploi_zae
            WHERE source = 'nikonoff_2026'
        """).fetchone()
    except Exception as e:
        raise HTTPException(500, f"Erreur DuckDB : {e}")

    if not row or row[0] is None:
        raise HTTPException(404, "Aucune donnée ZAE disponible — lancez le pipeline Airflow")

    return KPIs(
        emplois_zae_total=int(row[0]),
        nb_zones=int(row[1]),
        evolution_moy_pct=float(row[2] or 0),
        zones_en_croissance=int(row[3]),
        zones_en_alerte=int(row[4]),
        poids_zae_territoire_pct=float(row[5] or 0),
        date_extraction=date.today().isoformat(),
    )


@router.get("/zae", response_model=list[ZAERecord], tags=["zones"])
def list_zae(
    commune: Optional[str] = Query(None, description="Filtre par commune"),
    evolution_min: Optional[float] = Query(None, description="Évolution minimum (%)"),
    evolution_max: Optional[float] = Query(None, description="Évolution maximum (%)"),
    tri: str = Query("effectif_2026", description="Colonne de tri"),
    ordre: str = Query("desc", description="asc ou desc"),
    limit: int = Query(50, le=200),
):
    """Liste toutes les ZAE avec leurs indicateurs d'emploi."""
    con = get_db()

    # Colonnes et ordre validés contre liste blanche — pas de paramètre lié
    # possible pour les identifiants SQL (ORDER BY, noms de colonnes).
    allowed_cols = {"effectif_2026", "effectif_2021", "evolution_pct", "zone", "commune", "etab_2026"}
    if tri not in allowed_cols:
        tri = "effectif_2026"
    ordre_sql = "DESC" if ordre.lower() == "desc" else "ASC"

    # Les valeurs de filtre utilisent des paramètres liés (?) — pas d'injection possible.
    where_clauses = ["source = 'nikonoff_2026'"]
    params: list = []

    if commune:
        where_clauses.append("LOWER(commune) LIKE LOWER(?)")
        params.append(f"%{commune}%")
    if evolution_min is not None:
        where_clauses.append("evolution_pct >= ?")
        params.append(evolution_min)
    if evolution_max is not None:
        where_clauses.append("evolution_pct <= ?")
        params.append(evolution_max)

    params.append(limit)

    sql = f"""
        SELECT zone, commune, effectif_2021, effectif_2026, evolution_pct,
               etab_2021, etab_2026, source
        FROM emploi_zae
        WHERE {' AND '.join(where_clauses)}
        ORDER BY {tri} {ordre_sql}
        LIMIT ?
    """
    try:
        rows = con.execute(sql, params).fetchall()
    except Exception as e:
        raise HTTPException(500, str(e))

    cols = ["zone", "commune", "effectif_2021", "effectif_2026", "evolution_pct",
            "etab_2021", "etab_2026", "source"]
    return [ZAERecord(**dict(zip(cols, r))) for r in rows]


@router.get("/zae/{zone_name}", response_model=ZAERecord, tags=["zones"])
def get_zone(zone_name: str):
    """Détail d'une ZAE spécifique."""
    con = get_db()
    row = con.execute("""
        SELECT zone, commune, effectif_2021, effectif_2026, evolution_pct,
               etab_2021, etab_2026, source
        FROM emploi_zae
        WHERE LOWER(zone) = LOWER(?)
        LIMIT 1
    """, [zone_name]).fetchone()

    if not row:
        raise HTTPException(404, f"Zone '{zone_name}' introuvable")

    cols = ["zone", "commune", "effectif_2021", "effectif_2026", "evolution_pct",
            "etab_2021", "etab_2026", "source"]
    return ZAERecord(**dict(zip(cols, row)))


@router.get("/alertes", response_model=list[AlerteBODACC], tags=["signaux"])
def get_alertes(limit: int = Query(20, le=100)):
    """Procédures collectives récentes (liquidations/redressements) sur RPDF."""
    con = get_db()
    try:
        rows = con.execute("""
            SELECT siret, denomination, commune, type_avis, date_parution
            FROM alertes_bodacc
            WHERE alerte = true
            ORDER BY date_parution DESC
            LIMIT ?
        """, [limit]).fetchall()
    except Exception:
        rows = []

    cols = ["siret", "denomination", "commune", "type_avis", "date_parution"]
    return [AlerteBODACC(**dict(zip(cols, r))) for r in rows]


@router.get("/signaux", tags=["signaux"])
def get_signaux():
    """
    Synthèse des signaux faibles détectés :
    anomalies d'évolution, zones en déclin, alertes BODACC.
    """
    con = get_db()

    # Zones anomalies (Isolation Forest)
    try:
        anomalies = con.execute("""
            SELECT zone, commune, evolution_pct, effectif_2026
            FROM anomaly_scores
            WHERE is_anomaly = true
            ORDER BY evolution_pct ASC
            LIMIT 10
        """).df().to_dict(orient="records")
    except Exception:
        # Table pas encore créée — on calcule à la volée
        anomalies = con.execute("""
            SELECT zone, commune, evolution_pct, effectif_2026
            FROM emploi_zae
            WHERE evolution_pct < -20 OR evolution_pct > 100
            ORDER BY evolution_pct ASC
            LIMIT 10
        """).df().to_dict(orient="records")

    # Nb alertes BODACC
    try:
        nb_bodacc = con.execute(
            "SELECT COUNT(*) FROM alertes_bodacc WHERE alerte = true"
        ).fetchone()[0]
    except Exception:
        nb_bodacc = 0

    # Top zones croissance
    top_croissance = con.execute("""
        SELECT zone, commune, evolution_pct, effectif_2026
        FROM emploi_zae
        WHERE evolution_pct > 20 AND source = 'nikonoff_2026'
          AND effectif_2026 > 100
        ORDER BY evolution_pct DESC
        LIMIT 5
    """).df().to_dict(orient="records")

    return {
        "date": date.today().isoformat(),
        "nb_anomalies": len(anomalies),
        "nb_alertes_bodacc": nb_bodacc,
        "zones_anomalies": anomalies,
        "top_croissance": top_croissance,
        "score_risque_global": _compute_risk_score(con),
    }


@router.get("/previsions/{zone_name}", tags=["previsions"])
def get_previsions(zone_name: str, horizon: int = Query(3, ge=1, le=10)):
    """
    Projection simplifiée de l'emploi pour une ZAE.
    Utilise une extrapolation linéaire (Prophet en production).
    """
    con = get_db()
    row = con.execute("""
        SELECT effectif_2021, effectif_2026, evolution_pct
        FROM emploi_zae
        WHERE LOWER(zone) = LOWER(?)
        LIMIT 1
    """, [zone_name]).fetchone()

    if not row:
        raise HTTPException(404, f"Zone '{zone_name}' introuvable")

    e2021, e2026, evol_pct = row
    # Croissance annuelle implicite sur 5 ans
    taux_annuel = (e2026 / max(e2021, 1)) ** (1 / 5) - 1

    projections = []
    e_courant = e2026
    for i in range(1, horizon + 1):
        e_courant = round(e_courant * (1 + taux_annuel))
        projections.append({"annee": 2026 + i, "emplois_projetes": e_courant})

    return {
        "zone": zone_name,
        "effectif_2026": e2026,
        "taux_annuel_moyen": round(taux_annuel * 100, 1),
        "methode": "extrapolation_lineaire",
        "avertissement": "Projection indicative — ne tient pas compte des chocs exogènes",
        "projections": projections,
    }


@router.get("/export/csv", tags=["export"])
def export_csv():
    """Export CSV de toutes les données ZAE pour Excel / PowerBI."""
    import io, csv
    con = get_db()
    rows = con.execute("""
        SELECT zone, commune, effectif_2021, effectif_2026, evolution_pct,
               etab_2021, etab_2026, source, date_extraction
        FROM emploi_zae
        WHERE source = 'nikonoff_2026'
        ORDER BY effectif_2026 DESC
    """).fetchall()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["zone", "commune", "effectif_2021", "effectif_2026",
                     "evolution_pct", "etab_2021", "etab_2026", "source", "date_extraction"])
    writer.writerows(rows)
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=zae_rpdf.csv"},
    )


@router.get("/ml/prevision/{zone_name}", tags=["machine-learning"])
def ml_prevision(zone_name: str, horizon: int = Query(3, ge=1, le=5)):
    """
    Prévision d'emploi par Machine Learning (LightGBM quantile),
    avec intervalle de confiance et facteurs explicatifs (SHAP).
    Remplace l'extrapolation linéaire de /previsions par un modèle entraîné
    sur l'ensemble des 67 zones.
    """
    import sys
    sys.path.insert(0, "/app/ml")
    try:
        import pandas as pd
        from features.feature_store import build_feature_table, get_feature_columns
        from models.prevision_emploi import predict_zone
        from explain.shap_explainer import explain_prediction, generate_explanation_card
        import joblib
        from pathlib import Path
    except ImportError as e:
        raise HTTPException(501, f"Modules ML non installés : {e}")

    con = get_db()
    df = build_feature_table(con)
    zone_row = df[df["zone"].str.lower() == zone_name.lower()]

    if zone_row.empty:
        raise HTTPException(404, f"Zone '{zone_name}' introuvable")

    model_path = Path("/app/ml/artifacts/prevision_emploi.joblib")
    if not model_path.exists():
        raise HTTPException(
            503,
            "Modèle non entraîné — lancez le DAG observatoire_rpdf_ml_training"
        )

    try:
        prediction = predict_zone(zone_row, horizon_years=horizon)

        artifact = joblib.load(model_path)
        explications = explain_prediction(
            artifact["models"]["q50"], zone_row, artifact["feature_cols"]
        )

        return {
            "zone": zone_name,
            "prediction": prediction,
            "explications": explications,
            "fiche_lisible": generate_explanation_card(zone_name, prediction, explications),
        }
    except Exception as e:
        raise HTTPException(500, f"Erreur de prédiction : {e}")


@router.get("/ml/risque-defaillance/{zone_name}", tags=["machine-learning"])
def ml_risque_defaillance(zone_name: str):
    """
    Score de risque de défaillance pour les entreprises d'une zone (XGBoost),
    avec facteurs explicatifs. À considérer comme indicateur d'attention —
    voir l'avertissement dans la réponse.
    """
    import sys
    sys.path.insert(0, "/app/ml")
    try:
        from features.feature_store import build_feature_table
        from models.scoring_defaillance import score_zone
        from explain.shap_explainer import explain_prediction, generate_explanation_card
        import joblib
        from pathlib import Path
    except ImportError as e:
        raise HTTPException(501, f"Modules ML non installés : {e}")

    con = get_db()
    df = build_feature_table(con)
    zone_row = df[df["zone"].str.lower() == zone_name.lower()]

    if zone_row.empty:
        raise HTTPException(404, f"Zone '{zone_name}' introuvable")

    model_path = Path("/app/ml/artifacts/scoring_defaillance.joblib")
    if not model_path.exists():
        raise HTTPException(503, "Modèle non entraîné")

    try:
        score = score_zone(zone_row)
        artifact = joblib.load(model_path)
        explications = explain_prediction(artifact["model"], zone_row, artifact["feature_cols"])

        return {
            "zone": zone_name,
            "score": score,
            "explications": explications,
            "fiche_lisible": generate_explanation_card(zone_name, score, explications),
            "avertissement": (
                "Modèle entraîné sur un proxy de cible — usage indicatif "
                "uniquement, ne pas utiliser comme verdict sur une entreprise"
            ),
        }
    except Exception as e:
        raise HTTPException(500, f"Erreur de scoring : {e}")


@router.get("/ml/devitalisation/{zone_name}", tags=["machine-learning"])
def ml_devitalisation(zone_name: str):
    """Risque de dévitalisation commerciale (zones à dominante commerce uniquement)."""
    import sys
    sys.path.insert(0, "/app/ml")
    try:
        from features.feature_store import build_feature_table
        from models.devitalisation import predict_devitalisation
        from explain.shap_explainer import explain_prediction, generate_explanation_card
        import joblib
        from pathlib import Path
    except ImportError as e:
        raise HTTPException(501, f"Modules ML non installés : {e}")

    con = get_db()
    df = build_feature_table(con)
    zone_row = df[df["zone"].str.lower() == zone_name.lower()]

    if zone_row.empty:
        raise HTTPException(404, f"Zone '{zone_name}' introuvable")
    if zone_row["secteur_dominant"].values[0] != "commerce":
        raise HTTPException(
            422,
            "Ce modèle ne s'applique qu'aux zones à dominante commerciale"
        )

    model_path = Path("/app/ml/artifacts/devitalisation.joblib")
    if not model_path.exists():
        raise HTTPException(503, "Modèle non entraîné")

    try:
        prediction = predict_devitalisation(zone_row)
        artifact = joblib.load(model_path)
        explications = explain_prediction(artifact["model"], zone_row, artifact["feature_cols"])

        return {
            "zone": zone_name,
            "prediction": prediction,
            "explications": explications,
            "fiche_lisible": generate_explanation_card(zone_name, prediction, explications),
        }
    except Exception as e:
        raise HTTPException(500, f"Erreur de prédiction : {e}")


@router.get("/ml/status", tags=["machine-learning"])
def ml_status():
    """État des modèles ML : dernier entraînement, métriques de validation."""
    from pathlib import Path
    import joblib

    artifacts_dir = Path("/app/ml/artifacts")
    status = {}

    for name, filename in [
        ("prevision_emploi", "prevision_emploi.joblib"),
        ("scoring_defaillance", "scoring_defaillance.joblib"),
        ("devitalisation", "devitalisation.joblib"),
    ]:
        path = artifacts_dir / filename
        if path.exists():
            try:
                artifact = joblib.load(path)
                status[name] = {
                    "entraine": True,
                    "mae_loo": artifact.get("mae_loo"),
                }
            except Exception:
                status[name] = {"entraine": True, "erreur_lecture": True}
        else:
            status[name] = {"entraine": False}

    return status


@router.get("/nlp/synthese-presse", tags=["nlp"])
def nlp_synthese_presse():
    """
    Synthèse de l'analyse de presse de la semaine en cours : indice de
    climat économique, projets détectés, alertes de difficulté, classement
    des communes par fréquence de mention.
    """
    con = get_db()
    try:
        df = con.execute("""
            SELECT * FROM presse_analysee
            WHERE date_extraction >= CURRENT_DATE - INTERVAL 7 DAY
        """).df()
    except Exception:
        raise HTTPException(
            503,
            "Table presse_analysee non disponible — lancez le DAG "
            "observatoire_rpdf_nlp_presse"
        )

    if df.empty:
        return {
            "n_articles_analyses": 0,
            "message": "Aucun article analysé sur les 7 derniers jours",
        }

    import sys
    sys.path.insert(0, "/app/nlp")
    from extraction.signal_detection import generer_synthese_hebdomadaire

    # Reconversion des colonnes JSON stockées en texte
    import json
    for col in ["entites_entreprises", "communes_rpdf_mentionnees"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: json.loads(x) if isinstance(x, str) else x)
    df["pertinence_territoriale"] = df["communes_rpdf_mentionnees"].apply(lambda x: len(x) > 0)

    return generer_synthese_hebdomadaire(df)


@router.get("/nlp/projets-detectes", tags=["nlp"])
def nlp_projets_detectes(limit: int = Query(20, le=100)):
    """Liste des projets d'implantation/investissement détectés dans la presse."""
    con = get_db()
    try:
        rows = con.execute("""
            SELECT titre, url, source, date_publication, entites_entreprises,
                   communes_rpdf_mentionnees, theme_score, sentiment
            FROM presse_analysee
            WHERE theme_principal = 'projet' AND theme_score >= 0.5
            ORDER BY date_publication DESC
            LIMIT ?
        """, [limit]).df()
        return rows.to_dict(orient="records")
    except Exception:
        raise HTTPException(503, "Table presse_analysee non disponible")


@router.get("/nlp/alertes-difficulte", tags=["nlp"])
def nlp_alertes_difficulte(limit: int = Query(20, le=100)):
    """Liste des alertes de difficulté économique (fermetures, plans sociaux) détectées dans la presse."""
    con = get_db()
    try:
        rows = con.execute("""
            SELECT titre, url, source, date_publication, entites_entreprises,
                   communes_rpdf_mentionnees, theme_principal, theme_score, sentiment
            FROM presse_analysee
            WHERE theme_principal IN ('fermeture', 'difficulte') AND theme_score >= 0.5
            ORDER BY date_publication DESC
            LIMIT ?
        """, [limit]).df()
        return rows.to_dict(orient="records")
    except Exception:
        raise HTTPException(503, "Table presse_analysee non disponible")


@app.get("/health", tags=["meta"])
def health():
    try:
        con = get_db()
        con.execute("SELECT 1")
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        raise HTTPException(503, f"DB non disponible : {e}")


# ─── Helpers internes ─────────────────────────────────────────────────────────

def _compute_risk_score(con: duckdb.DuckDBPyConnection) -> str:
    """Score de risque global du territoire (faible / modéré / élevé)."""
    try:
        nb_alerte = con.execute("""
            SELECT COUNT(*) FROM emploi_zae
            WHERE evolution_pct < -20 AND source = 'nikonoff_2026'
        """).fetchone()[0]
        if nb_alerte >= 5:
            return "élevé"
        elif nb_alerte >= 2:
            return "modéré"
        return "faible"
    except Exception:
        return "inconnu"


def _ensure_schema(con: duckdb.DuckDBPyConnection):
    con.execute("""
        CREATE TABLE IF NOT EXISTS emploi_zae (
            zone            VARCHAR,
            commune         VARCHAR,
            effectif_2021   INTEGER,
            effectif_2026   INTEGER,
            evolution_pct   DOUBLE,
            etab_2021       INTEGER,
            etab_2026       INTEGER,
            source          VARCHAR,
            date_extraction VARCHAR
        );
        CREATE TABLE IF NOT EXISTS alertes_bodacc (
            siret           VARCHAR,
            denomination    VARCHAR,
            commune         VARCHAR,
            cp              VARCHAR,
            type_avis       VARCHAR,
            date_parution   VARCHAR,
            alerte          BOOLEAN,
            source          VARCHAR,
            date_extraction VARCHAR
        );
    """)


def _seed_mock_if_empty(con: duckdb.DuckDBPyConnection):
    n = con.execute("SELECT COUNT(*) FROM emploi_zae").fetchone()[0]
    if n > 0:
        return

    today = date.today().isoformat()
    mock_data = [
        ("ZAE Mitry-Compans",  "Mitry-Mory",     5981, 6315,  5.6,  295, 335, "nikonoff_2026", today),
        ("Paris Nord 2",        "Roissy CDG",      9408, 8801, -6.5,  300, 401, "nikonoff_2026", today),
        ("Plateforme CDG",      "Le Mesnil-Amelot",9794, 5390,-45.0,  154, 157, "nikonoff_2026", today),
        ("Tissonvilliers 2",    "Sarcelles",       3705, 2565,-30.8,  426, 350, "nikonoff_2026", today),
        ("Butte aux Bergers",   "Louvres",           45,  636,1313.0,  21,  52, "nikonoff_2026", today),
        ("Parc Mail",           "Roissy-en-France",  819, 1166, 42.4,  21,  47, "nikonoff_2026", today),
        ("CC Sentiers",         "Claye-Souilly",    1767, 1409,-20.3, 160, 126, "nikonoff_2026", today),
        ("Parc CDG Goussainville","Goussainville", 1827, 1700, -7.0, 239, 276, "nikonoff_2026", today),
        ("Portes de Vémars",    "Vémars",            484,  684, 41.3,  13,  17, "nikonoff_2026", today),
        ("ZA Barogne",          "Moussy-le-Neuf",    829, 1625, 96.0,  62,  75, "nikonoff_2026", today),
        ("A Park Le Thillay",   "Le Thillay",        890,  884, -0.7,  24,  56, "nikonoff_2026", today),
        ("Grande Couture Ouest","Gonesse",           167,  610,265.3,  35, 180, "nikonoff_2026", today),
        ("Le Moulin",           "Roissy CDG",       1949, 2982, 53.0, 174, 170, "nikonoff_2026", today),
        ("ZA Sablons",          "Claye-Souilly",     345, 1066,209.0,  82, 112, "nikonoff_2026", today),
        ("Parc Brèche",         "Goussainville",    1480, 1568,  5.9, 102, 101, "nikonoff_2026", today),
    ]

    for row in mock_data:
        con.execute("INSERT INTO emploi_zae VALUES (?,?,?,?,?,?,?,?,?)", list(row))

    # Alerte BODACC mock
    con.execute("""
        INSERT INTO alertes_bodacc VALUES
        ('12345678901234','Transport Roissy SAS','Gonesse','95500',
         'LIQUIDATION','2026-06-28',true,'bodacc','{}')
    """.format(today))


# Montage du router protégé — doit être après la définition de tous les
# endpoints @router.get ci-dessus.
app.include_router(router)
