FROM python:3.11-slim

# Installer les dépendances système nécessaires
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Configurer un utilisateur non-root pour Hugging Face Spaces (UID 1000)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Copier les fichiers requirements et installer les packages python
COPY --chown=user api/requirements.txt ./api-requirements.txt
COPY --chown=user ml/requirements.txt ./ml-requirements.txt

# Installer les dépendances dans le contexte utilisateur
RUN pip install --no-cache-dir --user -r api-requirements.txt -r ml-requirements.txt
RUN pip install --no-cache-dir --user streamlit plotly feedparser beautifulsoup4 spacy

# Télécharger le modèle français pour NLP spaCy
RUN python -m spacy download fr_core_news_sm

# Copier le reste du projet dans le conteneur
COPY --chown=user . .

# Préparer le fichier d'environnement et s'assurer que DuckDB écrit dans le répertoire local
RUN cp .env.example .env && \
    sed -i 's|DUCKDB_PATH=/data/warehouse.duckdb|DUCKDB_PATH=warehouse.duckdb|g' .env

# Rendre le script de démarrage exécutable
RUN chmod +x start.sh

# Exposer le port de l'application Streamlit pour Hugging Face Spaces
EXPOSE 7860

CMD ["./start.sh"]
