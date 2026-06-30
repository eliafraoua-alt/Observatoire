#!/bin/bash

# Activer le chargement d'environnement
export DUCKDB_PATH="warehouse.duckdb"
export API_KEY="changez-moi-avant-toute-mise-en-production"

echo "==================================================="
echo "Démarrage des services de l'Observatoire RPDF"
echo "==================================================="

# 1. Démarrer l'API FastAPI en arrière-plan
echo "Démarrage du serveur API FastAPI (port 8000)..."
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --env-file .env &

# Laisser un court délai pour l'initialisation de l'API et de la base de données
sleep 3

# 2. Démarrer le Dashboard Streamlit au premier plan
# Hugging Face Spaces s'attend à ce que l'application écoute sur le port 7860
echo "Démarrage du Dashboard Streamlit (port 7860)..."
python -m streamlit run dashboard/app.py --server.port 7860 --server.address 0.0.0.0
