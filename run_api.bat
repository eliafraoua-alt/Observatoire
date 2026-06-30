@echo off
title Observatoire API
echo ===================================================
echo Demarrage de l'API de l'Observatoire RPDF
echo ===================================================
cd /d "%~dp0"

if not exist .venv (
    echo Erreur : L'environnement virtuel .venv n'a pas ete trouve.
    echo Veuillez le creer d'abord avec : python -m venv .venv
    pause
    exit /b
)

echo Activation de l'environnement virtuel...
call .venv\Scripts\activate.bat

echo Lancement de l'API FastAPI...
python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000 --env-file .env
pause
