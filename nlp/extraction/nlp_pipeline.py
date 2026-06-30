"""
Pipeline NLP — analyse de la presse économique et locale.

Trois traitements appliqués à chaque article :
1. NER (reconnaissance d'entités nommées) — extraction des entreprises, lieux,
   personnes mentionnées, via spaCy (modèle français fr_core_news_lg).
2. Analyse de sentiment — polarité (positif/négatif/neutre), via un modèle
   CamemBERT fine-tuné pour le français.
3. Classification thématique — rattachement à une catégorie d'intérêt pour
   l'observatoire (projet d'implantation, fermeture/licenciement, difficulté
   économique, infrastructure, recrutement) via classification zero-shot.

Choix assumé : modèles open-source exécutés localement (pas d'API LLM externe)
pour deux raisons — coût nul par article traité, et aucune donnée de presse
ne transite vers un tiers, ce qui évite toute question de confidentialité sur
du contenu potentiellement sensible (difficultés d'entreprises notamment).
STATUT DE VALIDATION — à lire avant mise en production :
La logique pure de ce module (détection de communes par mots-clés, structure
des catégories) a été testée et fonctionne. Les trois modèles ML (spaCy NER,
CamemBERT sentiment, classification zero-shot mDeBERTa) n'ont PAS pu être
exécutés dans l'environnement de développement utilisé pour écrire ce code
— les téléchargements de modèles ont échoué (espace disque insuffisant pour
PyTorch+transformers, puis blocage réseau sur le CDN de modèles spaCy). Avant
toute mise en production, exécuter ce fichier en standalone
(`python nlp_pipeline.py`) sur l'infra cible pour valider que les trois
modèles se chargent et produisent des résultats cohérents sur l'exemple
fourni en bas de fichier.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, asdict
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

# ── Chargement paresseux des modèles ──────────────────────────────────────────
# Les modèles sont volumineux (spaCy fr_core_news_lg ~545 Mo, CamemBERT
# sentiment ~440 Mo) — chargement à la demande, mis en cache au niveau module
# pour éviter de recharger à chaque appel dans un contexte Airflow/API.

_nlp_spacy = None
_sentiment_pipeline = None
_zeroshot_pipeline = None


def _load_spacy():
    global _nlp_spacy
    if _nlp_spacy is None:
        import spacy
        try:
            _nlp_spacy = spacy.load("fr_core_news_lg")
        except OSError:
            log.warning(
                "Modèle fr_core_news_lg non installé — exécuter "
                "`python -m spacy download fr_core_news_lg`. "
                "Repli sur fr_core_news_sm (moins précis)."
            )
            try:
                _nlp_spacy = spacy.load("fr_core_news_sm")
            except OSError:
                raise RuntimeError(
                    "Aucun modèle spaCy français installé. Exécuter : "
                    "python -m spacy download fr_core_news_sm"
                )
    return _nlp_spacy


def _load_sentiment():
    global _sentiment_pipeline
    if _sentiment_pipeline is None:
        from transformers import pipeline
        # Modèle CamemBERT fine-tuné pour l'analyse de sentiment en français
        _sentiment_pipeline = pipeline(
            "sentiment-analysis",
            model="cmarkea/distilcamembert-base-sentiment",
            tokenizer="cmarkea/distilcamembert-base-sentiment",
        )
    return _sentiment_pipeline


def _load_zeroshot():
    global _zeroshot_pipeline
    if _zeroshot_pipeline is None:
        from transformers import pipeline
        # Classification zero-shot — pas besoin de jeu d'entraînement labellisé,
        # crucial pour démarrer le module sans corpus annoté disponible
        _zeroshot_pipeline = pipeline(
            "zero-shot-classification",
            model="MoritzLaurer/mDeBERTa-v3-base-mnli-xnli",
        )
    return _zeroshot_pipeline


# ── Catégories thématiques pour l'observatoire ────────────────────────────────
CATEGORIES_OBSERVATOIRE = [
    "projet d'implantation ou d'investissement d'entreprise",
    "fermeture, licenciement ou plan social",
    "difficulté économique ou financière d'entreprise",
    "infrastructure ou aménagement du territoire",
    "recrutement ou création d'emploi",
    "actualité sans lien direct avec l'économie locale",
]

LABELS_CATEGORIES_COURTS = {
    "projet d'implantation ou d'investissement d'entreprise": "projet",
    "fermeture, licenciement ou plan social": "fermeture",
    "difficulté économique ou financière d'entreprise": "difficulte",
    "infrastructure ou aménagement du territoire": "infrastructure",
    "recrutement ou création d'emploi": "recrutement",
    "actualité sans lien direct avec l'économie locale": "hors_sujet",
}

# Communes du territoire RPDF — pour qualifier la pertinence géographique
COMMUNES_RPDF = {
    "gonesse", "goussainville", "sarcelles", "villiers-le-bel", "garges-lès-gonesse",
    "garges les gonesse", "mitry-mory", "mitry mory", "claye-souilly", "claye souilly",
    "villeparisis", "louvres", "moussy-le-neuf", "marly-la-ville", "le mesnil-amelot",
    "mesnil amelot", "vémars", "le thillay", "roissy-en-france", "roissy en france",
    "compans", "fosses", "saint-witz", "survilliers", "longperrier", "saint-mard",
}


@dataclass
class AnalyseArticle:
    titre: str
    url: str
    source: str
    date_publication: str
    categorie_source: str
    # Résultats NLP
    entites_entreprises: list
    entites_lieux: list
    entites_personnes: list
    communes_rpdf_mentionnees: list
    sentiment: str
    sentiment_score: float
    theme_principal: str
    theme_score: float
    pertinence_territoriale: bool


def analyser_article(titre: str, resume: str, url: str, source: str,
                      date_publication: str, categorie_source: str) -> AnalyseArticle:
    """Applique le pipeline NLP complet à un article (titre + résumé)."""
    texte = f"{titre}. {resume}"

    entites = _extraire_entites(texte)
    sentiment, sentiment_score = _analyser_sentiment(texte)
    theme, theme_score = _classifier_theme(texte)
    communes_mentionnees = _detecter_communes(texte)

    return AnalyseArticle(
        titre=titre,
        url=url,
        source=source,
        date_publication=date_publication,
        categorie_source=categorie_source,
        entites_entreprises=entites["entreprises"],
        entites_lieux=entites["lieux"],
        entites_personnes=entites["personnes"],
        communes_rpdf_mentionnees=communes_mentionnees,
        sentiment=sentiment,
        sentiment_score=sentiment_score,
        theme_principal=theme,
        theme_score=theme_score,
        pertinence_territoriale=len(communes_mentionnees) > 0,
    )


def analyser_corpus(df_articles: pd.DataFrame) -> pd.DataFrame:
    """
    Applique l'analyse NLP à un DataFrame d'articles (sortie de
    rss_collector.collecter_flux_rss ou du scraper conforme).
    """
    if df_articles.empty:
        return pd.DataFrame()

    resultats = []
    for _, row in df_articles.iterrows():
        try:
            analyse = analyser_article(
                titre=row.get("titre", ""),
                resume=row.get("resume", ""),
                url=row.get("url", ""),
                source=row.get("source", ""),
                date_publication=row.get("date_publication", ""),
                categorie_source=row.get("categorie", ""),
            )
            resultats.append(asdict(analyse))
        except Exception as e:
            log.error("Erreur d'analyse pour l'article '%s' : %s", row.get("titre", "?"), e)
            continue

    return pd.DataFrame(resultats)


def _extraire_entites(texte: str) -> dict:
    """NER via spaCy — extraction entreprises (ORG), lieux (LOC), personnes (PER)."""
    nlp = _load_spacy()
    doc = nlp(texte[:5000])  # limite raisonnable pour la performance

    entreprises, lieux, personnes = [], [], []
    for ent in doc.ents:
        if ent.label_ == "ORG":
            entreprises.append(ent.text)
        elif ent.label_ in ("LOC", "GPE"):
            lieux.append(ent.text)
        elif ent.label_ == "PER":
            personnes.append(ent.text)

    return {
        "entreprises": list(dict.fromkeys(entreprises))[:10],  # dédoublonnage en gardant l'ordre
        "lieux": list(dict.fromkeys(lieux))[:10],
        "personnes": list(dict.fromkeys(personnes))[:5],
    }


def _analyser_sentiment(texte: str) -> tuple[str, float]:
    """Analyse de sentiment via CamemBERT — retourne (label, score de confiance)."""
    pipe = _load_sentiment()
    try:
        result = pipe(texte[:512])[0]  # limite token du modèle
        label = result["label"].lower()
        # Normalisation des labels du modèle vers un vocabulaire stable
        if "positi" in label or "5 star" in label or label in ("4 stars", "5 stars"):
            sentiment = "positif"
        elif "negati" in label or label in ("1 star", "2 stars"):
            sentiment = "negatif"
        else:
            sentiment = "neutre"
        return sentiment, round(float(result["score"]), 3)
    except Exception as e:
        log.warning("Erreur analyse sentiment : %s", e)
        return "indetermine", 0.0


def _classifier_theme(texte: str) -> tuple[str, float]:
    """Classification zero-shot vers les catégories d'intérêt de l'observatoire."""
    pipe = _load_zeroshot()
    try:
        result = pipe(texte[:1000], candidate_labels=CATEGORIES_OBSERVATOIRE, multi_label=False)
        theme_long = result["labels"][0]
        score = round(float(result["scores"][0]), 3)
        return LABELS_CATEGORIES_COURTS.get(theme_long, theme_long), score
    except Exception as e:
        log.warning("Erreur classification thématique : %s", e)
        return "indetermine", 0.0


def _detecter_communes(texte: str) -> list[str]:
    """Détection rapide par mots-clés des communes RPDF mentionnées (complète le NER)."""
    texte_lower = texte.lower()
    return [c for c in COMMUNES_RPDF if c in texte_lower]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test sur un article synthétique pour valider la chaîne sans dépendre
    # de la disponibilité des flux RSS externes
    exemple = analyser_article(
        titre="Le transporteur Geodis annonce un plan social à Mitry-Mory",
        resume=(
            "L'entreprise de logistique Geodis a annoncé la suppression de 120 "
            "postes sur son site de Mitry-Mory, invoquant la baisse d'activité "
            "liée au ralentissement du e-commerce. Les syndicats dénoncent une "
            "décision brutale."
        ),
        url="https://exemple.fr/article-test",
        source="Test",
        date_publication="2026-06-30",
        categorie_source="locale",
    )
    print("=== Test du pipeline NLP ===")
    for k, v in asdict(exemple).items():
        print(f"  {k}: {v}")
