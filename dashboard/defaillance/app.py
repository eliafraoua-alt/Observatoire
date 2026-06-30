"""
Dashboard 2/3 — Risque de défaillance d'entreprise (XGBoost)
Port dédié : 8512
"""

import os
import requests
import pandas as pd
import streamlit as st
import plotly.express as px

API_URL = os.environ.get("API_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "")
_HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

st.set_page_config(page_title="Risque de défaillance — Observatoire RPDF", page_icon="🚨", layout="wide")

st.title("🚨 Risque de défaillance d'entreprise")
st.caption("Modèle XGBoost — score de risque par zone, à utiliser comme indicateur d'attention")

st.warning(
    "⚠️ **Ce modèle est entraîné sur un proxy de cible** (zones dégradées + alertes BODACC), "
    "pas sur des défaillances réellement observées dans le temps. C'est un indicateur "
    "d'attention pour orienter le suivi économique, pas un verdict sur une entreprise précise."
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


@st.cache_data(ttl=300)
def fetch_alertes_bodacc():
    try:
        return pd.DataFrame(requests.get(f"{API_URL}/alertes", timeout=10, headers=_HEADERS).json())
    except Exception:
        return pd.DataFrame()


status = fetch_ml_status()
scoring_status = status.get("scoring_defaillance", {})

if scoring_status.get("entraine"):
    st.success("✅ Modèle entraîné")
else:
    st.info("⏳ Modèle non entraîné — exécutez `python ml/train_initial.py`")

st.divider()

df_zae = fetch_zae()
df_bodacc = fetch_alertes_bodacc()

if df_zae.empty:
    st.info("Aucune donnée disponible.")
    st.stop()

col_kpi1, col_kpi2 = st.columns(2)
with col_kpi1:
    st.metric("Alertes BODACC actives sur le territoire", len(df_bodacc))
with col_kpi2:
    zones_fragiles = len(df_zae[df_zae["evolution_pct"] < -15])
    st.metric("Zones avec évolution < -15%", zones_fragiles)

st.divider()

col_select, col_action = st.columns([3, 1])
with col_select:
    zone = st.selectbox("Zone à analyser", df_zae["zone"].tolist())
with col_action:
    st.write("")
    st.write("")
    lancer = st.button("Calculer le score", type="primary")

if lancer:
    with st.spinner("Calcul en cours..."):
        try:
            resp = requests.get(f"{API_URL}/ml/risque-defaillance/{zone}", timeout=20, headers=_HEADERS)
            if resp.status_code != 200:
                st.error(resp.json().get("detail", "Erreur"))
                st.stop()
            data = resp.json()
        except Exception as e:
            st.error(f"Erreur : {e}")
            st.stop()

    score = data["score"]
    niveau = score["niveau_risque"]
    couleur = {"élevé": "#A8001C", "modéré": "#BA7517", "faible": "#1F6B35"}.get(niveau, "#595959")
    badge = {"élevé": "🔴", "modéré": "🟡", "faible": "🟢"}.get(niveau, "⚪")

    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown(f"""
        <div style="background:{couleur}22; border-left:4px solid {couleur}; border-radius:10px; padding:1.2rem;">
            <div style="font-size:0.9rem; color:#595959;">Niveau de risque</div>
            <div style="font-size:1.8rem; font-weight:700; color:{couleur};">{badge} {niveau.capitalize()}</div>
            <div style="font-size:0.85rem; color:#595959; margin-top:0.5rem;">
                Probabilité estimée : {score['probabilite_risque']*100:.0f}%
            </div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("#### Facteurs explicatifs")
        for i, exp in enumerate(data["explications"], 1):
            st.markdown(f"**{i}.** {exp['phrase']}")

    st.caption(f"ℹ️ {data.get('avertissement', '')}")

    with st.expander("Fiche complète"):
        st.code(data["fiche_lisible"], language=None)

st.divider()

# Cartographie des risques — toutes zones
st.markdown("#### Cartographie du risque sur le territoire")
st.caption("Approximation basée sur l'évolution observée et les alertes BODACC (pas le score ML complet)")

df_zae["risque_visuel"] = df_zae["evolution_pct"].apply(
    lambda x: "élevé" if x < -20 else ("modéré" if x < -5 else "faible")
)
fig = px.bar(
    df_zae.sort_values("evolution_pct").head(20),
    x="evolution_pct", y="zone", orientation="h",
    color="risque_visuel",
    color_discrete_map={"élevé": "#A8001C", "modéré": "#BA7517", "faible": "#1F6B35"},
    labels={"evolution_pct": "Évolution 2021-2026 (%)", "zone": ""},
    title="20 zones les plus exposées (tri par évolution observée)",
    height=500,
)
st.plotly_chart(fig, use_container_width=True)

if not df_bodacc.empty:
    st.markdown("#### Procédures collectives récentes (BODACC)")
    st.dataframe(df_bodacc, use_container_width=True)

with st.expander("📋 Méthodologie et limites — à lire avant tout usage"):
    st.markdown("""
    **Limite majeure et assumée** : faute d'historique de défaillances réelles
    sur 24 mois ou plus, la cible d'entraînement est un *proxy* (zones avec
    évolution d'emploi très négative combinées à des alertes BODACC dans la
    commune). Ce n'est pas une vraie variable supervisée — c'est un point de
    départ qui s'améliorera mécaniquement à mesure que l'historique BODACC
    s'accumule dans le data warehouse.

    **Usage recommandé** : ce score doit orienter le *suivi* économique
    (quelles zones visiter en priorité, quels établissements pivot
    contacter), jamais être communiqué comme un verdict sur une entreprise
    nommément désignée.

    **Amélioration prioritaire** : intégrer des ratios financiers réels
    (Ellisphère, Infogreffe, Diane) quand un accès sera négocié, pour
    remplacer le proxy actuel par une vraie variable de risque financier.
    """)
