"""
Dashboard 3/3 — Risque de dévitalisation commerciale (Gradient Boosting)
Port dédié : 8513
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

st.set_page_config(page_title="Dévitalisation commerciale — Observatoire RPDF", page_icon="🏚️", layout="wide")

st.title("🏚️ Risque de dévitalisation commerciale")
st.caption("Modèle Gradient Boosting — taux de vacance projeté pour les zones à dominante commerce")

st.warning(
    "⚠️ La cible d'entraînement est actuellement un **proxy calculé**, faute "
    "de mesure terrain réelle de la vacance commerciale. La fiabilisation de "
    "ce modèle passe par le lancement d'une enquête terrain annuelle "
    "(module 5 de l'observatoire) — voir méthodologie en bas de page."
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
devital_status = status.get("devitalisation", {})

if devital_status.get("entraine"):
    st.success("✅ Modèle entraîné")
elif devital_status == {}:
    st.info("⏳ Statut indisponible — vérifiez que l'API est démarrée")
else:
    st.warning(
        "⏳ Modèle non entraîné — probablement moins de 8 zones à dominante "
        "commerce dans l'échantillon actuel. Voir la note de garde-fou en bas de page."
    )

st.divider()

df_zae = fetch_zae()

if df_zae.empty:
    st.info("Aucune donnée disponible.")
    st.stop()

# Filtrer sur les zones identifiées commerce (heuristique affichage le temps
# que l'API expose le secteur dominant directement)
zones_a_risque_mots_cles = ["cc ", "parc", "commercial", "tissonvilliers", "brèche", "mail"]
df_commerce_like = df_zae[
    df_zae["zone"].str.lower().str.contains("|".join(zones_a_risque_mots_cles), regex=True)
]

col1, col2 = st.columns(2)
with col1:
    st.metric("Zones à dominante commerce identifiées", len(df_commerce_like))
with col2:
    en_recul = len(df_commerce_like[df_commerce_like["evolution_pct"] < 0])
    st.metric("Dont en recul d'emploi", en_recul)

st.divider()

if df_commerce_like.empty:
    st.info("Aucune zone commerciale clairement identifiée dans l'échantillon actuel.")
else:
    col_select, col_action = st.columns([3, 1])
    with col_select:
        zone = st.selectbox("Zone commerciale à analyser", df_commerce_like["zone"].tolist())
    with col_action:
        st.write("")
        st.write("")
        lancer = st.button("Calculer le risque", type="primary")

    if lancer:
        with st.spinner("Calcul en cours..."):
            try:
                resp = requests.get(f"{API_URL}/ml/devitalisation/{zone}", timeout=20, headers=_HEADERS)
                if resp.status_code == 422:
                    st.info("Ce modèle ne s'applique qu'aux zones classées à dominante commerciale par le modèle.")
                    st.stop()
                if resp.status_code != 200:
                    st.error(resp.json().get("detail", "Erreur"))
                    st.stop()
                data = resp.json()
            except Exception as e:
                st.error(f"Erreur : {e}")
                st.stop()

        pred = data["prediction"]
        taux = pred["taux_vacance_projete_pct"]

        # Jauge de risque
        fig_gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=taux,
            title={"text": "Taux de vacance projeté (%)"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#1B2A4A"},
                "steps": [
                    {"range": [0, 30], "color": "#D9EFE0"},
                    {"range": [30, 50], "color": "#FAEEDA"},
                    {"range": [50, 100], "color": "#FAD4DB"},
                ],
            },
        ))
        fig_gauge.update_layout(height=300)
        st.plotly_chart(fig_gauge, use_container_width=True)

        st.markdown(f"**Statut : {pred['statut']}**")

        st.markdown("#### Facteurs explicatifs")
        for i, exp in enumerate(data["explications"], 1):
            st.markdown(f"**{i}.** {exp['phrase']}")

        with st.expander("Fiche complète"):
            st.code(data["fiche_lisible"], language=None)

st.divider()

st.markdown("#### Zones commerciales — vue d'ensemble")
if not df_commerce_like.empty:
    fig = px.bar(
        df_commerce_like.sort_values("evolution_pct"),
        x="evolution_pct", y="zone", orientation="h",
        color="evolution_pct",
        color_continuous_scale=["#A8001C", "#EEEEEE", "#1F6B35"],
        color_continuous_midpoint=0,
        labels={"evolution_pct": "Évolution emploi 2021-2026 (%)", "zone": ""},
        title="Dynamique des zones commerciales identifiées",
        height=400,
    )
    st.plotly_chart(fig, use_container_width=True)

with st.expander("📋 Méthodologie et limites — à lire avant tout usage"):
    st.markdown("""
    **Garde-fou actif** : le modèle refuse de s'entraîner avec moins de 8
    zones à dominante commerciale dans l'échantillon. C'est volontaire — un
    modèle entraîné sur trop peu d'exemples produirait des prédictions non
    fiables sans que l'utilisateur s'en rende compte. Si le statut ci-dessus
    indique "non entraîné", c'est ce garde-fou qui s'est déclenché.

    **Cible proxy** : en l'absence d'enquête terrain réelle sur la vacance
    commerciale, la variable cible est calculée à partir de l'exposition
    sectorielle, de l'évolution d'emploi et des alertes BODACC locales. Ce
    n'est pas une mesure directe de vacance — c'est une approximation qui
    doit être validée et affinée par un comptage terrain réel.

    **Priorité d'amélioration n°1** : lancer le module 5 de l'observatoire
    (enquête panel entreprises annuelle, 150-200 entreprises représentatives)
    pour obtenir une vraie variable de vacance commerciale observée, et
    réentraîner ce modèle sur des données réelles plutôt que des proxies.

    **Usage recommandé** : ce modèle sert à prioriser les zones à visiter
    pour un diagnostic terrain approfondi, pas à décider seul d'une politique
    de requalification foncière.
    """)
