@echo off
title Observatoire Dashboards
echo ===================================================
echo Demarrage des Dashboards Streamlit de l'Observatoire
echo ===================================================
cd /d "%~dp0"

if not exist .venv (
    echo Erreur : L'environnement virtuel .venv n'a pas ete trouve.
    pause
    exit /b
)

echo Activation de l'environnement virtuel...
call .venv\Scripts\activate.bat

echo Chargement des variables d'environnement depuis .env...
if exist .env (
    for /f "eol=# tokens=*" %%a in (.env) do set "%%a"
)

echo Demarrage du Dashboard General sur http://localhost:8501...
start "Dashboard General" streamlit run dashboard/app.py --server.port 8501

echo Demarrage du Dashboard Prevision sur http://localhost:8511...
start "Dashboard Prevision" streamlit run dashboard/prevision/app.py --server.port 8511

echo Demarrage du Dashboard Defaillance sur http://localhost:8512...
start "Dashboard Defaillance" streamlit run dashboard/defaillance/app.py --server.port 8512

echo Demarrage du Dashboard Devitalisation sur http://localhost:8513...
start "Dashboard Devitalisation" streamlit run dashboard/devitalisation/app.py --server.port 8513

echo Demarrage du Dashboard Presse NLP sur http://localhost:8514...
start "Dashboard Presse NLP" streamlit run dashboard/presse/app.py --server.port 8514

echo ===================================================
echo Tous les dashboards ont ete lances en arriere-plan.
echo Fermez cette fenetre pour arreter le script principal.
echo ===================================================
pause
