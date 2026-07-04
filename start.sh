#!/bin/bash

export DUCKDB_PATH="warehouse.duckdb"
export API_KEY="changez-moi-avant-toute-mise-en-production"

echo "==================================================="
echo "Démarrage des services de l'Observatoire RPDF"
echo "==================================================="

# 0. Initialisation des données mock si la base est vide
echo "Initialisation des données mock..."
python - <<'EOF'
import duckdb, os
from datetime import date

db = os.environ.get("DUCKDB_PATH", "warehouse.duckdb")
con = duckdb.connect(db)

for ddl in [
    """CREATE TABLE IF NOT EXISTS emploi_zae (
        zone VARCHAR, commune VARCHAR, effectif_2021 INTEGER, effectif_2026 INTEGER,
        evolution_pct DOUBLE, etab_2021 INTEGER, etab_2026 INTEGER,
        source VARCHAR, date_extraction VARCHAR)""",
    """CREATE TABLE IF NOT EXISTS alertes_bodacc (
        siret VARCHAR, denomination VARCHAR, commune VARCHAR, cp VARCHAR,
        type_avis VARCHAR, date_parution VARCHAR, alerte BOOLEAN,
        source VARCHAR, date_extraction VARCHAR)""",
    """CREATE TABLE IF NOT EXISTS anomaly_scores (
        zone VARCHAR, commune VARCHAR, anomaly_score DOUBLE, is_anomaly BOOLEAN,
        evolution_pct DOUBLE, effectif_2026 INTEGER)""",
    """CREATE TABLE IF NOT EXISTS bodacc_annonces (
        id VARCHAR, type_bodacc VARCHAR, numero_parution VARCHAR, date_parution VARCHAR,
        denomination VARCHAR, siret VARCHAR, siren VARCHAR, code_postal VARCHAR,
        ville VARCHAR, departement VARCHAR, famille_activite VARCHAR, type_annonce VARCHAR,
        detail_json VARCHAR, alerte BOOLEAN, date_extraction VARCHAR)""",
]:
    con.execute(ddl)

n = con.execute("SELECT COUNT(*) FROM emploi_zae").fetchone()[0]
if n == 0:
    today = date.today().isoformat()
    mock_data = [
        ("ZAE Mitry-Compans","Mitry-Mory",5981,6315,5.6,295,335,"nikonoff_2026",today),
        ("Paris Nord 2","Gonesse",9408,8801,-6.5,300,401,"nikonoff_2026",today),
        ("Plateforme CDG","Le Mesnil-Amelot",9794,5390,-45.0,154,157,"nikonoff_2026",today),
        ("Tissonvilliers 2","Sarcelles",3705,2565,-30.8,426,350,"nikonoff_2026",today),
        ("Butte aux Bergers","Louvres",45,636,1313.0,21,52,"nikonoff_2026",today),
        ("Parc Mail","Roissy-en-France",819,1166,42.4,21,47,"nikonoff_2026",today),
        ("CC Sentiers","Claye-Souilly",1767,1409,-20.3,160,126,"nikonoff_2026",today),
        ("Parc CDG Goussainville","Goussainville",1827,1700,-7.0,239,276,"nikonoff_2026",today),
        ("Portes de Vemars","Vemars",484,684,41.3,13,17,"nikonoff_2026",today),
        ("ZA Barogne","Moussy-le-Neuf",829,1625,96.0,62,75,"nikonoff_2026",today),
        ("A Park Le Thillay","Le Thillay",890,884,-0.7,24,56,"nikonoff_2026",today),
        ("Grande Couture Ouest","Gonesse",167,610,265.3,35,180,"nikonoff_2026",today),
        ("Le Moulin","Roissy CDG",1949,2982,53.0,174,170,"nikonoff_2026",today),
        ("ZA Sablons","Claye-Souilly",345,1066,209.0,82,112,"nikonoff_2026",today),
        ("Parc Breche","Goussainville",1480,1568,5.9,102,101,"nikonoff_2026",today),
    ]
    for row in mock_data:
        con.execute("INSERT INTO emploi_zae VALUES (?,?,?,?,?,?,?,?,?)", list(row))
    print(f"[OK] {len(mock_data)} zones mock insérées")
else:
    print(f"[OK] Base déjà alimentée ({n} zones)")

con.commit()
con.close()
EOF

# 1. Ingestion BODACC (vraies données Val-d'Oise + Seine-et-Marne)
echo "Ingestion des données BODACC (30 derniers jours)..."
python - <<'EOF'
import os, sys, logging
sys.path.insert(0, "/home/user/app")
logging.basicConfig(level=logging.WARNING)

db = os.environ.get("DUCKDB_PATH", "warehouse.duckdb")

try:
    from ingestion.scrapers.scraper_bodacc import scrape_bodacc, sync_vers_alertes_bodacc
    stats = scrape_bodacc(db_path=db, jours=30)
    n = sync_vers_alertes_bodacc(db_path=db)
    print(f"[OK] BODACC : {stats['total']} annonces ingérées, {stats['alertes']} alertes ({n} nouvelles)")
except Exception as e:
    print(f"[WARN] BODACC non disponible : {e}")
EOF

# 2. Démarrer l'API FastAPI en arrière-plan
echo "Démarrage du serveur API FastAPI (port 8000)..."
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --env-file .env &

# Laisser un court délai pour l'initialisation
sleep 5

# 3. Démarrer le Dashboard Streamlit au premier plan
echo "Démarrage du Dashboard Streamlit (port 7860)..."
python -m streamlit run dashboard/app.py --server.port 7860 --server.address 0.0.0.0
