# Observatoire Économique RPDF — MVP

Pipeline de données et tableau de bord pour l'observatoire des Zones d'Activités
Économiques de la Communauté d'Agglomération Roissy Pays de France.

## Architecture

```
Sources open data
(INSEE, France Travail, BODACC, SITADEL, DVF+)
         │
         ▼
Airflow DAGs  ──► MinIO (Data Lake Parquet)
         │
         ▼
     DuckDB (Warehouse)
         │
    ┌────┴────┐
    ▼         ▼
FastAPI    dbt + ML
(REST)   (KPIs, anomalies)
    │
    ├── Streamlit Dashboard (élus)
    ├── Alertes Slack/Email
    └── Export CSV/Excel
```

## Démarrage rapide (dev)

```bash
# Cloner et démarrer la stack complète
git clone https://github.com/rpdf/observatoire.git
cd observatoire-mvp

# Copier et renseigner les secrets
cp .env.example .env
# Éditer .env avec vos tokens INSEE et France Travail

# Lancer tous les services
docker compose up -d

# Vérifier que tout est up
docker compose ps

# Accès
# Airflow              : http://localhost:8080  (admin / admin)
# API                  : http://localhost:8000/docs
# Dashboard général    : http://localhost:8501
# Dashboard Prévision  : http://localhost:8511
# Dashboard Défaillance: http://localhost:8512
# Dashboard Dévitalis. : http://localhost:8513
# Dashboard Presse NLP : http://localhost:8514
# MinIO                : http://localhost:9001  (minioadmin / minioadmin)
# Grafana              : http://localhost:3000  (admin / admin)
```

## Premier pipeline

```bash
# Déclencher manuellement le DAG d'ingestion depuis l'UI Airflow
# ou via CLI :
docker compose exec airflow-scheduler \
  airflow dags trigger observatoire_rpdf_ingestion

# Surveiller l'exécution
docker compose logs -f airflow-scheduler
```

## Déposer les données Nikonoff

Le fichier CSV des effectifs ZAE doit être déposé dans MinIO :
```bash
# Via la console MinIO : http://localhost:9001
# Bucket : rpdf-observatoire
# Chemin : uploads/zae_nikonoff.csv

# Ou via mc (MinIO Client) :
mc alias set myminio http://localhost:9000 minioadmin minioadmin
mc cp ./data/zae_nikonoff_2026.csv myminio/rpdf-observatoire/uploads/zae_nikonoff.csv
```

Format attendu du CSV :
```
zone,commune,effectif_2021,effectif_2026,evolution_pct,etab_2021,etab_2026
ZAE Mitry-Compans,Mitry-Mory,5981,6315,5.6,295,335
...
```

## Machine Learning — prédictions explicables

Au-delà de l'extrapolation linéaire de base (`/previsions/{zone}`), l'observatoire
embarque 3 modèles de Machine Learning entraînés sur l'ensemble des 67 zones.

### Pourquoi pas une série temporelle classique ?

Avec seulement 2 points de mesure par zone (2021 et 2026), un LSTM ou un ARIMA
n'a pas de sens statistique. La stratégie retenue est l'**apprentissage
transversal** : les 67 zones servent d'échantillon d'entraînement, et leurs
caractéristiques structurelles (taille, secteur, accessibilité, dynamique
locale) servent de prédicteurs. Le modèle apprend "ce qui fait qu'une zone
croît ou décline" plutôt que "la tendance de cette zone isolée".

### Les 3 modèles

| Modèle | Algorithme | Cible | Limite principale |
|--------|-----------|-------|---------------------|
| Prévision d'emploi | LightGBM quantile | Évolution % à horizon N | Intervalle large (P10–P90), n=67 |
| Risque de défaillance | XGBoost classifier | Probabilité défaillance 12 mois | Cible = proxy (pas de défaillances réelles observées) |
| Dévitalisation commerciale | Gradient Boosting | Taux de vacance N+2 | Cible = proxy, sous-échantillon (zones commerce) |

### Explicabilité — non négociable

Chaque prédiction est accompagnée des facteurs SHAP qui l'expliquent, traduits
en langage clair. Aucun score n'est exposé sans sa justification.

```bash
curl http://localhost:8000/ml/prevision/Paris%20Nord%202
```
```json
{
  "zone": "Paris Nord 2",
  "prediction": {
    "evolution_pct_p50": -3.2,
    "intervalle_confiance": "[-12.1%, 5.8%]"
  },
  "explications": [
    {"phrase": "Exposition sectorielle au risque augmente la prédiction"},
    {"phrase": "Distance à la gare la plus proche diminue la prédiction"}
  ]
}
```

### Entraînement initial

```bash
docker compose exec api python ml/train_initial.py
```

Le DAG `observatoire_rpdf_ml_training` réentraîne ensuite automatiquement les
3 modèles le 1er de chaque mois, avec détection de dérive (alerte si une
métrique de validation varie de plus de 30% d'un mois sur l'autre).

## Élargissement des sources — scraping conforme et limites réelles

Un connecteur de scraping a été ajouté (`ingestion/scrapers/`) pour élargir
la collecte au-delà des API officielles, sous une règle stricte et non
négociable : **aucune requête n'est exécutée sans vérification préalable du
robots.txt de la source**. Toute source qui interdit l'accès est écartée
silencieusement et journalisée — jamais contournée par rotation de proxy,
falsification de user-agent, ou autre moyen technique.

### Résultat de l'audit réel (à date du 30/06/2026)

L'audit a été exécuté pour de vrai sur les sources candidates les plus
évidentes (annonces immobilières, offres d'emploi) :

| Source | Verdict |
|--------|---------|
| SeLoger, LeBonCoin, PAP, Indeed | ❌ Scraping interdit par robots.txt |
| data.gouv.fr, BODACC, INSEE (sites web) | ❌ Scraping interdit — **mais API officielle déjà intégrée** |

**Conclusion honnête** : le scraping HTML générique des grandes plateformes
n'est, dans les faits, presque jamais une option viable — c'est la politique
standard du secteur, qui pousse vers les API officielles plutôt que vers le
scraping. La quasi-totalité des données utiles de l'observatoire transitent
donc déjà par API structurée (`observatoire_ingestion.py`), ce qui est en
réalité préférable : plus stable dans le temps qu'un scraper HTML qui casse
à chaque refonte de site.

Le module de scraping reste utile pour des sources plus modestes (CCI, CMA,
mairies, agences locales) qui n'ont pas d'API mais peuvent autoriser le
crawl — chaque source candidate doit être auditée individuellement avant
intégration (voir `ingestion/scrapers/README_SOURCES.md` pour la procédure
et le détail des audits déjà réalisés).

```bash
# Auditer une nouvelle source avant de l'ajouter au pipeline
docker compose exec api python -c "
from ingestion.scrapers.robots_gate import audit_source
import json
print(json.dumps(audit_source('https://exemple.fr', ['/annonces']), indent=2))
"
```

## Module NLP — veille presse économique et locale

Un 4ème dashboard (`dashboard-presse`, port 8514) analyse la presse économique
nationale et locale pour détecter les projets d'implantation, les difficultés
d'entreprises, et mesurer le climat médiatique perçu — des signaux qui
apparaissent souvent dans la presse plusieurs mois avant qu'ils ne soient
visibles dans les statistiques INSEE.

### Architecture

1. **Collecte** (`nlp/sources/rss_collector.py`) — flux RSS de presse
   économique nationale filtrés par mots-clés territoriaux, et de presse
   locale (Val-d'Oise, Seine-et-Marne) gardée intégralement.
2. **Scraping conforme** (`ingestion/scrapers/`) — réutilise le connecteur
   robots.txt déjà construit pour les sources locales sans flux RSS.
3. **Pipeline NLP** (`nlp/extraction/nlp_pipeline.py`) — trois traitements
   par article : NER (spaCy), sentiment (CamemBERT), classification
   thématique zero-shot (mDeBERTa) vers 6 catégories : projet
   d'implantation, fermeture/plan social, difficulté économique,
   infrastructure, recrutement, hors-sujet.
4. **Détection de signaux** (`nlp/extraction/signal_detection.py`) — agrège
   le corpus analysé en indicateurs exploitables : indice de climat
   économique, projets détectés, alertes de difficulté, classement des
   communes par fréquence de mention.

### Choix technique — modèles locaux, pas d'API LLM externe

Conformément au choix retenu, tous les modèles sont open-source et exécutés
localement sur l'infrastructure de l'observatoire (pas d'appel à une API LLM
externe type Claude/GPT). Deux raisons : coût nul par article traité (le
volume de presse à analyser quotidiennement serait coûteux en API payante),
et aucune donnée d'article — potentiellement sensible s'il s'agit de
difficultés d'entreprises nommées — ne transite vers un tiers.

### ⚠️ Statut de validation — à lire avant mise en production

Ce module a été construit et sa logique testée par étapes, mais avec des
limites de validation honnêtes à connaître :

- **Logique d'agrégation et de détection de signaux** (`signal_detection.py`) :
  ✅ testée par exécution réelle sur un corpus synthétique — fonctionne
  correctement (séparation projets/alertes, calcul d'indice, classement
  communes).
- **Détection de communes par mots-clés** (`nlp_pipeline.py`) : ✅ testée et
  fonctionnelle.
- **Modèles ML (NER spaCy, sentiment CamemBERT, classification zero-shot)** :
  ❌ n'ont **pas** pu être exécutés dans l'environnement de développement
  utilisé pour écrire ce code (espace disque insuffisant pour
  PyTorch+transformers, puis blocage réseau sur le CDN des modèles spaCy).
  **Avant toute mise en production**, exécuter
  `python nlp/extraction/nlp_pipeline.py` sur l'infra cible pour confirmer
  que les trois modèles se chargent et produisent des résultats cohérents.
- **Flux RSS du registre** (`nlp/sources/rss_collector.py`) : les URLs Le
  Parisien proviennent d'un annuaire de flux tiers et n'ont pas pu être
  testées depuis cette sandbox (domaine hors allowlist réseau) ; les autres
  URLs (Les Echos, La Tribune) sont des suppositions non vérifiées. Chaque
  flux est marqué `verifie: False` dans le registre — exécuter
  `python nlp/sources/rss_collector.py` (qui appelle automatiquement
  `valider_registre_flux()`) pour obtenir le statut réel de chaque flux
  avant d'activer le DAG `observatoire_rpdf_nlp_presse` en production.

### Installation des modèles NLP

```bash
docker compose exec api pip install -r nlp/requirements.txt
docker compose exec api python -m spacy download fr_core_news_lg

# Validation avant activation
docker compose exec api python nlp/sources/rss_collector.py    # statut des flux
docker compose exec api python nlp/extraction/nlp_pipeline.py  # test des modèles ML
```

## Les 4 dashboards Machine Learning et NLP

Plutôt qu'un dashboard unique, l'observatoire expose 3 applications Streamlit
indépendantes — une par modèle — pour permettre une navigation et un usage
ciblés selon le besoin du moment.

| Dashboard | Port | Usage |
|-----------|------|-------|
| Prévision d'emploi | 8511 | Projection à horizon 1-5 ans avec intervalle de confiance |
| Risque de défaillance | 8512 | Score d'attention par zone + alertes BODACC |
| Dévitalisation commerciale | 8513 | Taux de vacance projeté, zones commerce uniquement |
| Veille presse NLP | 8514 | Projets, alertes et climat médiatique détectés dans la presse |

Chacun affiche systématiquement : le statut d'entraînement du modèle, les
métriques de validation honnêtes (MAE, AUC), les facteurs explicatifs SHAP
en langage clair, et un encart méthodologie qui rappelle les limites du
modèle — jamais un score affiché sans son contexte de fiabilité.

Le dashboard général (port 8501) reste disponible pour une vue d'ensemble
opérationnelle (ZAE, signaux faibles, alertes BODACC, export).

### Limites assumées — à lire avant toute utilisation opérationnelle

- Les modèles 2 et 3 utilisent des **cibles proxy**, pas des données observées
  dans le temps. Ce sont des indicateurs d'attention, pas des verdicts.
- Les features géographiques (distance gare, distance CDG) sont actuellement
  **mockées** — un vrai référentiel SIG doit remplacer `_enrich_geo_mock()`
  dans `ml/features/feature_store.py` avant mise en production.
- Le secteur dominant par zone est actuellement **inféré du nom de la zone** —
  une jointure SIRENE réelle doit remplacer `_enrich_secteur_mock()`.
- Avec n=67, tout modèle reste fragile aux valeurs extrêmes (ex. +1313% sur
  Butte aux Bergers) — la régularisation forte (L1/L2) limite mais n'élimine
  pas ce risque.

## Endpoints API — Endpoints principaux

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| GET | `/kpis` | 6 KPIs de synthèse |
| GET | `/zae` | Liste toutes les ZAE (filtrable) |
| GET | `/zae/{zone}` | Détail d'une zone |
| GET | `/signaux` | Anomalies + alertes synthétiques |
| GET | `/alertes` | Procédures collectives BODACC |
| GET | `/previsions/{zone}` | Projection emploi N+1 à N+10 |
| GET | `/export/csv` | Export CSV complet |
| GET | `/ml/prevision/{zone}` | Prévision ML avec intervalle de confiance + explications |
| GET | `/ml/risque-defaillance/{zone}` | Score de risque de défaillance + explications |
| GET | `/ml/devitalisation/{zone}` | Risque de dévitalisation commerciale + explications |
| GET | `/ml/status` | État d'entraînement des modèles |

Documentation interactive : http://localhost:8000/docs

## Déploiement production (AWS)

### Prérequis

- Compte AWS avec droits ECS, ECR, S3, EFS, Secrets Manager
- Terraform >= 1.8
- GitHub Actions secrets configurés :
  - `AWS_ACCOUNT_ID`
  - `SLACK_WEBHOOK_URL`

### Déploiement

```bash
# 1. Créer le bucket Terraform state
aws s3 mb s3://rpdf-terraform-state --region eu-west-3

# 2. Renseigner les secrets dans AWS Secrets Manager
aws secretsmanager create-secret --name rpdf/insee-token --secret-string "VOTRE_TOKEN"
aws secretsmanager create-secret --name rpdf/ft-client-id --secret-string "VOTRE_CLIENT_ID"
aws secretsmanager create-secret --name rpdf/ft-secret --secret-string "VOTRE_SECRET"

# 3. Initialiser et appliquer Terraform
cd infra/terraform
terraform init
terraform plan -var="aws_account_id=123456789012"
terraform apply

# 4. Le CI/CD GitHub Actions prend ensuite le relais sur chaque push main
```

## Secrets et tokens nécessaires

| Secret | Source | Obtention |
|--------|--------|-----------|
| `INSEE_TOKEN` | api.insee.fr | Inscription sur https://api.insee.fr |
| `FRANCE_TRAVAIL_CLIENT_ID` | entreprise.francetravail.fr | https://francetravail.io/data/api |
| `FRANCE_TRAVAIL_SECRET` | idem | idem |

Note : BODACC et SITADEL sont accessibles sans authentification via data.gouv.fr.

## Structure du projet

```
observatoire-mvp/
├── docker-compose.yml          # Stack dev complète
├── .env.example                # Variables d'environnement
├── ingestion/
│   └── dags/
│       └── observatoire_ingestion.py   # DAG Airflow principal
├── api/
│   ├── main.py                 # FastAPI
│   ├── requirements.txt
│   └── Dockerfile
├── dashboard/
│   ├── app.py                  # Streamlit
│   └── Dockerfile
├── processing/                 # dbt models + ML (à compléter)
├── infra/
│   ├── terraform/
│   │   └── main.tf            # Infrastructure AWS
│   └── prometheus.yml
├── tests/                      # Tests unitaires
└── .github/
    └── workflows/
        └── ci-cd.yml          # GitHub Actions
```

## KPIs suivis (tableau de bord)

1. Emplois totaux en ZAE (estimé)
2. Nombre de zones analysées
3. Évolution moyenne 2021–2026 (%)
4. Zones en croissance (évol > 0)
5. Zones en alerte (évol < -20 %)
6. Poids ZAE / emploi territorial total

## Modèles dbt — couche de transformation versionnée et testée

Le dossier `warehouse/` contient un projet dbt complet, construit et validé
par exécution réelle (`dbt run` + `dbt test`, 4 modèles, 16 tests, tous
passants) :

- **Staging** (`stg_emploi_zae`, `stg_alertes_bodacc`) — nettoyage et typage
  des tables brutes, isolé dans une couche dédiée pour que toute correction
  de qualité de données se fasse à un seul endroit.
- **Marts** (`mart_kpis_territoire`, `mart_dynamique_zae`) — agrégats métier
  testés (not_null, unique, accepted_values), incluant la catégorisation des
  ZAE par taille (pôle majeur/intermédiaire/petit/micro) et par tendance
  (croissance forte/modérée, recul modéré/marqué) reprise du rapport
  d'analyse territoriale.

Le DAG `observatoire_rpdf_ingestion` exécute `dbt run` puis `dbt test` après
le chargement des tables brutes — un échec de test dbt génère un
avertissement journalisé sans bloquer le pipeline (à durcir une fois le
projet mûr et la volumétrie de données suffisante pour juger des seuils
d'alerte pertinents).

**⚠️ État d'intégration actuel** : l'API (`/kpis`, `/zae`) interroge encore
directement la vue SQL brute `v_kpis_territoire` définie dans
`observatoire_ingestion.py`, pas les marts dbt. Faire basculer l'API vers
`mart_kpis_territoire` et `mart_dynamique_zae` est la prochaine étape
logique — cela demande de changer les requêtes SQL dans `api/main.py` pour
pointer vers le schéma `main_marts` généré par dbt, ce qui n'a pas encore
été fait pour ne pas casser les tests de l'API existants sans une bascule
complète et testée.

```bash
# Exécuter dbt manuellement
docker compose exec airflow-scheduler bash -c \
  "cd /opt/airflow/warehouse && dbt run --profiles-dir . && dbt test --profiles-dir ."

# Générer la documentation dbt (catalogue de données navigable)
docker compose exec airflow-scheduler bash -c \
  "cd /opt/airflow/warehouse && dbt docs generate --profiles-dir . && dbt docs serve --profiles-dir ."
```

## Tests automatisés

Le projet dispose d'une suite de 46 tests pytest, exécutée et validée :

```bash
pip install -r api/requirements.txt -r ml/requirements.txt
pip install feedparser beautifulsoup4 pytest

DUCKDB_PATH=":memory:" pytest tests/ -v
# 46 passed
```

Couverture par module :
- `test_api.py` (21 tests) — authentification (clé API, endpoints publics
  vs protégés), endpoints KPIs/ZAE/signaux/prévisions, cas limites (modèle
  ML absent doit retourner 503, jamais un crash 500)
- `test_ml.py` (12 tests) — feature engineering (pas de division par zéro),
  entraînement des 3 modèles, garde-fous (refus d'entraînement si données
  insuffisantes), explicabilité SHAP (facteurs en langage clair, jamais de
  nom de variable technique brut)
- `test_scraping_et_nlp.py` (13 tests) — conformité robots.txt (cache,
  refus silencieux, jamais de contournement), détection de signaux presse
  (séparation projets/alertes, indice de climat dans les bornes [-1, 1])

Le CI GitHub Actions (`.github/workflows/ci-cd.yml`) exécute cette suite à
chaque push, avec couverture de code (`pytest-cov`) sur `api/` et `ml/`.

## Sécurité de l'API — authentification par clé

Tous les endpoints métier (`/kpis`, `/zae`, `/ml/*`, `/nlp/*`, `/export/csv`)
nécessitent l'en-tête `X-API-Key`, vérifié via une dépendance FastAPI
(`require_api_key`) appliquée globalement par un `APIRouter`. Seuls `/` et
`/health` restent publics — nécessaires aux health checks Docker/ECS qui
n'ont pas connaissance de la clé.

```bash
# Sans clé — refusé (401)
curl http://localhost:8000/kpis

# Avec clé — autorisé (200)
curl -H "X-API-Key: votre-cle" http://localhost:8000/kpis
```

**Comportement en dev local** : si `API_KEY` n'est pas définie dans
l'environnement, l'authentification est désactivée automatiquement (un
avertissement est journalisé au démarrage de l'API). Cela évite de bloquer
le développement local tout en rendant explicite — dans les logs — que ce
choix existe et doit être changé avant toute mise en production. Les 5
dashboards Streamlit lisent `API_KEY` depuis leur propre environnement et
l'envoient automatiquement dans l'en-tête `X-API-Key` de chaque requête.

Le CORS est restreint aux origines des dashboards (configurable via
`API_CORS_ORIGINS`), remplaçant le `allow_origins=["*"]` initial qui
acceptait n'importe quel domaine.

**Limite assumée** : cette clé API est partagée entre tous les dashboards
(authentification simple, pas d'autorisation différenciée par utilisateur).
Pour une mise en production avec plusieurs profils d'accès (élus, techniciens,
entreprises), une vraie gestion d'identité (OAuth2, SSO de la collectivité)
serait nécessaire — hors périmètre de ce MVP.

## Roadmap MVP → V2

**Fait depuis la dernière itération** (audit de qualité, 4 points critiques corrigés) :
- [x] Authentification API par clé (X-API-Key), CORS restreint
- [x] Suite de tests automatisés (46 tests pytest, exécutés et validés)
- [x] `.env.example` documentant toutes les variables nécessaires
- [x] Projet dbt fonctionnel (4 modèles, 16 tests, validés par exécution réelle)

**Reste à faire** :
- [ ] Basculer l'API des vues SQL brutes vers les marts dbt (`mart_kpis_territoire`)
- [ ] Intégration DVF+ (valeurs foncières — données foncières.data.gouv.fr)
- [ ] Cartographie Kepler.gl avec géolocalisation des ZAE
- [ ] Modèle Prophet pour prévisions long terme
- [ ] Digest email hebdomadaire automatique (AWS SES)
- [ ] Connecteur France Travail offres d'emploi géolocalisées
- [ ] Module enquête panel entreprises (formulaire Tally/Typeform)
- [ ] Validation en production des flux RSS et modèles NLP (voir limites
      documentées dans la section Module NLP)
- [ ] Gestion d'identité différenciée par profil utilisateur (au-delà de la
      clé API unique actuelle)

## Contact

Agence de développement économique — CA Roissy Pays de France
observatoire@roissypaysdefrance.fr
