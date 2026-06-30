"""
Dashboard 1/3 — Prévision d'emploi (LightGBM quantile)
Port dédié : 8511
"""

import os
import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px

API_URL = os.environ.get("API_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "")
_HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

st.set_page_config(page_title="Prévision d'emploi — Observatoire RPDF", page_icon="🔮", layout="wide")

st.markdown("""
<style>
  .kpi-card { background: #E6F1FB; border-radius: 10px; padding: 1rem; border-left: 4px solid #185FA5; }
</style>
""", unsafe_allow_html=True)

st.title("🔮 Prévision d'emploi par zone")
st.caption(
    "Modèle LightGBM quantile — apprentissage transversal sur les 67 ZAE. "
    "Chaque prédiction est un intervalle [P10, P90], jamais un chiffre unique."
)


@st.cache_data(ttl=300)
def fetch_zae():
    try:
        return pd.DataFrame(requests.get(f"{API_URL}/zae", params={"limit": 100}, timeout=10, headers=_HEADERS).json())
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=120)
def fetch_ml_status():
    try:
        return requests.get(f"{API_URL}/ml/status", timeout=10, headers=_HEADERS).json()
    except Exception:
        return {}


status = fetch_ml_status()
prevision_status = status.get("prevision_emploi", {})

col_status, col_mae = st.columns(2)
with col_status:
    if prevision_status.get("entraine"):
        st.success("✅ Modèle entraîné et opérationnel")
    else:
        st.warning("⏳ Modèle non entraîné — exécutez `python ml/train_initial.py`")
with col_mae:
    if prevision_status.get("mae_loo"):
        st.metric("Erreur moyenne (validation Leave-One-Out)", f"± {prevision_status['mae_loo']} pts")
        st.caption("Plus ce chiffre est élevé, plus l'intervalle de confiance est large — normal avec 67 zones.")

st.divider()

df_zae = fetch_zae()

if df_zae.empty:
    st.info("Aucune donnée disponible. Lancez le pipeline d'ingestion Airflow.")
    st.stop()

col_select, col_horizon = st.columns([3, 1])
with col_select:
    zone = st.selectbox("Zone à projeter", df_zae["zone"].tolist())
with col_horizon:
    horizon = st.slider("Horizon (années)", 1, 5, 3)

if st.button("Lancer la prévision", type="primary"):
    with st.spinner("Calcul en cours..."):
        try:
            resp = requests.get(f"{API_URL}/ml/prevision/{zone}", params={"horizon": horizon}, timeout=20, headers=_HEADERS)
            if resp.status_code != 200:
                st.error(resp.json().get("detail", "Erreur"))
                st.stop()
            data = resp.json()
        except Exception as e:
            st.error(f"Erreur : {e}")
            st.stop()

    pred = data["prediction"]

    col1, col2, col3 = st.columns(3)
    col1.metric("Évolution projetée (P50)", f"{pred['evolution_pct_p50']:+.1f} %")
    col2.metric("Borne basse (P10)", f"{pred['evolution_pct_p10']:+.1f} %")
    col3.metric("Borne haute (P90)", f"{pred['evolution_pct_p90']:+.1f} %")

    # Graphique intervalle de confiance
    proj_df = pd.DataFrame(data["prediction"]["projections"])
    if not proj_df.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=proj_df["annee"], y=proj_df["p90"], mode="lines",
            line=dict(width=0), showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=proj_df["annee"], y=proj_df["p10"], mode="lines",
            fill="tonexty", fillcolor="rgba(24,95,165,0.15)",
            line=dict(width=0), name="Intervalle [P10-P90]",
        ))
        fig.add_trace(go.Scatter(
            x=proj_df["annee"], y=proj_df["p50"], mode="lines+markers",
            line=dict(color="#185FA5", width=3), name="Médiane (P50)",
        ))
        fig.update_layout(
            title=f"Projection d'emploi — {zone}",
            xaxis_title="Année", yaxis_title="Emplois estimés",
            height=400,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Pourquoi cette prédiction ?")
    st.caption("Facteurs explicatifs (SHAP) — classés par importance")
    for i, exp in enumerate(data["explications"], 1):
        sens_icon = "📈" if exp["sens"] == "augmente" else "📉"
        st.markdown(f"{sens_icon} **{i}.** {exp['phrase']}")

    with st.expander("Fiche complète (texte brut, copiable)"):
        st.code(data["fiche_lisible"], language=None)

st.divider()

# Vue d'ensemble — toutes les zones
st.markdown("#### Vue d'ensemble du territoire")
fig_overview = px.scatter(
    df_zae, x="evolution_pct", y="effectif_2026",
    size="effectif_2026", color="evolution_pct",
    color_continuous_scale=["#A8001C", "#EEEEEE", "#1F6B35"],
    color_continuous_midpoint=0,
    hover_data=["zone", "commune"],
    labels={"evolution_pct": "Évolution observée 2021-2026 (%)", "effectif_2026": "Emplois 2026"},
    title="Positionnement de toutes les zones (cliquer un point = sélectionner ci-dessus)",
)
st.plotly_chart(fig_overview, use_container_width=True)

with st.expander("📋 Méthodologie et limites"):
    st.markdown("""
    **Pourquoi pas une série temporelle classique ?** Avec seulement 2 points
    de mesure par zone (2021 et 2026), un modèle de série temporelle (ARIMA,
    Prophet, LSTM) n'a pas de sens statistique — il faudrait au minimum 8 à 12
    points. La stratégie retenue est l'apprentissage transversal : les 67 zones
    servent d'échantillon d'entraînement, et leurs caractéristiques structurelles
    (taille, secteur, accessibilité) prédisent leur dynamique.

    **Validation** : Leave-One-Out, seule méthode fiable avec un échantillon
    de cette taille. Le MAE affiché en haut de page est honnête — ne pas
    s'attendre à une précision élevée avec si peu de données historiques.

    **Amélioration prioritaire** : intégrer un vrai référentiel SIG (distance
    gare, distance CDG actuellement simulées) et une jointure SIRENE réelle
    pour le secteur dominant par zone.
    """)
