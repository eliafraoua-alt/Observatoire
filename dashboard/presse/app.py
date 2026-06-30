"""
Dashboard 4/4 — Analyse NLP de la presse économique et locale
Port dédié : 8514
"""

import os
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

API_URL = os.environ.get("API_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "")
_HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

st.set_page_config(page_title="Veille presse — Observatoire RPDF", page_icon="📰", layout="wide")

st.title("📰 Veille presse économique et locale")
st.caption(
    "Analyse NLP (NER, sentiment, classification thématique) de la presse "
    "économique nationale filtrée sur le territoire, et de la presse locale. "
    "Modèles open-source exécutés localement — aucune donnée transmise à un tiers."
)


@st.cache_data(ttl=600)
def fetch_synthese():
    try:
        return requests.get(f"{API_URL}/nlp/synthese-presse", timeout=15, headers=_HEADERS).json()
    except Exception:
        return {}


@st.cache_data(ttl=600)
def fetch_projets():
    try:
        return pd.DataFrame(requests.get(f"{API_URL}/nlp/projets-detectes", timeout=15, headers=_HEADERS).json())
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def fetch_alertes():
    try:
        return pd.DataFrame(requests.get(f"{API_URL}/nlp/alertes-difficulte", timeout=15, headers=_HEADERS).json())
    except Exception:
        return pd.DataFrame()


synthese = fetch_synthese()

if not synthese or synthese.get("n_articles_analyses", 0) == 0:
    st.info(
        "Aucun article analysé pour le moment. Lancez le DAG "
        "`observatoire_rpdf_nlp_presse` après avoir validé les flux RSS "
        "(voir `nlp/sources/rss_collector.py` — exécuter en standalone pour "
        "vérifier quels flux fonctionnent réellement avant activation)."
    )
    st.stop()

# ── Indice de climat économique ────────────────────────────────────────────
indice = synthese.get("indice_climat", {})

col1, col2, col3, col4 = st.columns(4)
with col1:
    val = indice.get("indice")
    couleur_indice = "🟢" if (val or 0) > 0.15 else ("🔴" if (val or 0) < -0.15 else "🟡")
    st.metric("Indice de climat économique", f"{couleur_indice} {val if val is not None else 'N/A'}")
    st.caption(indice.get("interpretation", ""))
with col2:
    st.metric("Articles analysés (7j)", synthese.get("n_articles_analyses", 0))
with col3:
    st.metric("Projets détectés", len(synthese.get("projets_detectes", [])))
with col4:
    st.metric("Alertes difficulté", len(synthese.get("alertes_difficulte", [])))

st.caption(
    "⚠️ L'indice de climat économique reflète la **perception médiatique**, "
    "pas une mesure économique directe — un mois avec une seule fermeture "
    "très médiatisée peut faire chuter l'indice sans refléter l'ensemble du "
    "tissu économique. À croiser avec les données factuelles des autres dashboards."
)

st.divider()

tab1, tab2, tab3 = st.tabs(["🟢 Projets détectés", "🔴 Alertes difficulté", "🗺️ Communes les plus citées"])

with tab1:
    projets = synthese.get("projets_detectes", [])
    if not projets:
        st.info("Aucun projet d'implantation détecté sur la période.")
    else:
        for p in projets:
            with st.container():
                col_a, col_b = st.columns([4, 1])
                with col_a:
                    st.markdown(f"**[{p['titre']}]({p['url']})**")
                    entreprises = p.get("entites_entreprises", [])
                    communes = p.get("communes_rpdf_mentionnees", [])
                    meta = []
                    if entreprises:
                        meta.append(f"Entreprises citées : {', '.join(entreprises)}")
                    if communes:
                        meta.append(f"Communes : {', '.join(communes)}")
                    st.caption(" · ".join(meta) if meta else "")
                with col_b:
                    st.caption(f"{p['source']}")
                    st.caption(f"Confiance : {p['theme_score']*100:.0f}%")
                st.divider()

with tab2:
    alertes = synthese.get("alertes_difficulte", [])
    if not alertes:
        st.success("Aucune alerte de difficulté économique détectée sur la période.")
    else:
        for a in alertes:
            with st.container():
                col_a, col_b = st.columns([4, 1])
                with col_a:
                    badge = "🔴" if a["theme_principal"] == "fermeture" else "🟠"
                    st.markdown(f"{badge} **[{a['titre']}]({a['url']})**")
                    entreprises = a.get("entites_entreprises", [])
                    communes = a.get("communes_rpdf_mentionnees", [])
                    meta = []
                    if entreprises:
                        meta.append(f"Entreprises citées : {', '.join(entreprises)}")
                    if communes:
                        meta.append(f"Communes : {', '.join(communes)}")
                    st.caption(" · ".join(meta) if meta else "")
                with col_b:
                    st.caption(f"{a['source']}")
                    st.caption(f"Confiance : {a['theme_score']*100:.0f}%")
                st.divider()

with tab3:
    classement = synthese.get("classement_communes", [])
    if not classement:
        st.info("Aucune mention de commune RPDF détectée sur la période.")
    else:
        df_classement = pd.DataFrame(classement)
        fig = px.bar(
            df_classement.head(15), x="nb_mentions", y="commune", orientation="h",
            labels={"nb_mentions": "Nombre de mentions", "commune": ""},
            title="Communes les plus citées dans la presse (7 derniers jours)",
            height=450,
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(df_classement, use_container_width=True)

st.divider()

with st.expander("📋 Méthodologie, sources et limites — à lire avant tout usage"):
    st.markdown("""
    **Sources** : flux RSS de presse économique nationale (filtrés sur des
    mots-clés territoriaux RPDF) et de presse locale (Val-d'Oise,
    Seine-et-Marne), complétés par du scraping conforme robots.txt sur des
    sources locales sans flux RSS disponible.

    **⚠️ Statut de validation des flux RSS** : certaines URLs du registre
    n'ont pas encore été confirmées en production — voir
    `nlp/sources/README` ou exécuter `python nlp/sources/rss_collector.py`
    pour obtenir l'état réel de chaque flux avant de se fier pleinement aux
    résultats de ce dashboard.

    **Pipeline NLP** : reconnaissance d'entités nommées (spaCy, modèle
    français), analyse de sentiment (CamemBERT fine-tuné), classification
    thématique zero-shot (mDeBERTa). Tous les modèles sont open-source et
    exécutés localement sur l'infrastructure de l'observatoire — aucun texte
    d'article n'est envoyé à un service tiers.

    **Limites à connaître** :
    - La classification zero-shot n'a pas de jeu d'entraînement spécifique
      au territoire — elle peut se tromper sur des formulations ambiguës.
      Le score de confiance affiché doit toujours être pris en compte.
    - L'indice de climat économique est un indicateur de **perception**
      médiatique, pas une mesure factuelle. Il doit être croisé avec les
      données des dashboards Prévision, Défaillance et Dévitalisation.
    - La détection de communes repose sur une recherche de mots-clés simple
      — un article peut mentionner une commune sans qu'elle soit le sujet
      réel de l'article (faux positifs possibles).
    """)
