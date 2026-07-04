"""
Observatoire RPDF — Dashboard Streamlit
Tableau de bord destiné aux élus et techniciens de l'agglomération.
"""

import os
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

API_URL = os.environ.get("API_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "")
_HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}

st.set_page_config(
    page_title="Observatoire ZAE — Roissy Pays de France",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .kpi-card {
    background: #f0f4ff;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    border-left: 4px solid #2E5597;
    margin-bottom: 0.5rem;
  }
  .kpi-value { font-size: 2rem; font-weight: 700; color: #1B2A4A; }
  .kpi-label { font-size: 0.85rem; color: #595959; }
  .alerte-badge {
    background: #FAD4DB; color: #A8001C;
    border-radius: 6px; padding: 2px 10px; font-size: 0.8rem;
  }
  .ok-badge {
    background: #D9EFE0; color: #1F6B35;
    border-radius: 6px; padding: 2px 10px; font-size: 0.8rem;
  }
  .bodacc-card {
    background: #fff8f8;
    border-left: 4px solid #A8001C;
    border-radius: 8px;
    padding: 0.8rem 1rem;
    margin-bottom: 0.5rem;
  }
  .bodacc-denomination { font-weight: 600; color: #1B2A4A; }
  .bodacc-meta { font-size: 0.8rem; color: #595959; }
</style>
""", unsafe_allow_html=True)


# ── Fonctions d'appel API ─────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def fetch_kpis():
    try:
        return requests.get(f"{API_URL}/kpis", timeout=10, headers=_HEADERS).json()
    except Exception:
        return None


@st.cache_data(ttl=300)
def fetch_zae(commune=None, evol_min=None, evol_max=None):
    params = {"limit": 100}
    if commune:
        params["commune"] = commune
    if evol_min is not None:
        params["evolution_min"] = evol_min
    if evol_max is not None:
        params["evolution_max"] = evol_max
    try:
        resp = requests.get(f"{API_URL}/zae", params=params, timeout=10, headers=_HEADERS)
        return pd.DataFrame(resp.json())
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_signaux():
    try:
        return requests.get(f"{API_URL}/signaux", timeout=10, headers=_HEADERS).json()
    except Exception:
        return {}


@st.cache_data(ttl=60)
def fetch_alertes(limit=100):
    try:
        resp = requests.get(
            f"{API_URL}/alertes",
            params={"limit": limit},
            timeout=10,
            headers=_HEADERS
        )
        return pd.DataFrame(resp.json())
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_bodacc_stats():
    """Récupère les statistiques BODACC directement via l'API /signaux."""
    try:
        return requests.get(f"{API_URL}/signaux", timeout=10, headers=_HEADERS).json()
    except Exception:
        return {}


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🗺 Filtres")
    commune_filtre = st.text_input("Commune", placeholder="Ex : Gonesse")
    evol_min = st.slider("Évolution min (%)", -100, 0, -100)
    evol_max = st.slider("Évolution max (%)", 0, 1500, 1500)

    st.markdown("---")
    st.markdown("""
    **Sources**
    - INSEE Flores 2023
    - Nikonoff Conseils avr. 2026
    - BODACC (quotidien)
    - France Travail StatLocal

    **Périmètre** : 26 communes,
    67 ZAE, CA-RPDF
    """)

    if st.button("🔄 Actualiser"):
        st.cache_data.clear()
        st.rerun()

    st.markdown(f"*Données au {datetime.today().strftime('%d/%m/%Y')}*")


# ── En-tête ───────────────────────────────────────────────────────────────────
st.title("📊 Observatoire Économique")
st.markdown("**Communauté d'Agglomération Roissy Pays de France** — Zones d'Activités Économiques")
st.divider()

# ── KPIs ──────────────────────────────────────────────────────────────────────
kpis = fetch_kpis()
signaux = fetch_signaux()

if kpis:
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Emplois en ZAE", f"{kpis['emplois_zae_total']:,}".replace(",", " "),
                  help="Effectif estimé 2026 — Source Nikonoff Conseils")
    with col2:
        st.metric("Zones analysées", kpis["nb_zones"])
    with col3:
        delta_color = "normal" if kpis["evolution_moy_pct"] >= 0 else "inverse"
        st.metric("Évol. moy.", f"{kpis['evolution_moy_pct']:+.1f} %",
                  delta="vs 2021 (COVID)", delta_color=delta_color)
    with col4:
        st.metric("Zones en croissance", kpis["zones_en_croissance"],
                  delta=f"sur {kpis['nb_zones']} zones")
    with col5:
        st.metric("Zones en alerte", kpis["zones_en_alerte"],
                  delta="< -20 %", delta_color="inverse")
    with col6:
        st.metric("Poids ZAE / territoire", f"{kpis['poids_zae_territoire_pct']} %",
                  help="Part des emplois en ZAE dans l'emploi total du territoire (179 000 emplois)")
else:
    st.warning("⚠️ API non disponible — vérifiez que le service FastAPI est démarré.")

st.divider()

# ── Onglets ───────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🏭 Zones d'activité", "📈 Signaux faibles", "🚨 Alertes BODACC",
    "🔮 Prévisions", "🤖 Machine Learning"
])

# ─── TAB 1 : Tableau des ZAE ──────────────────────────────────────────────────
with tab1:
    df = fetch_zae(
        commune=commune_filtre or None,
        evol_min=evol_min,
        evol_max=evol_max,
    )

    if df.empty:
        st.info("Aucune donnée disponible. Lancez le pipeline Airflow.")
    else:
        col_a, col_b = st.columns([3, 2])

        with col_a:
            top15 = df.nlargest(15, "effectif_2026")
            fig = px.bar(
                top15,
                x="effectif_2026",
                y="zone",
                orientation="h",
                color="evolution_pct",
                color_continuous_scale=["#A8001C", "#F5C4B3", "#EEEEEE", "#D9EFE0", "#1F6B35"],
                color_continuous_midpoint=0,
                labels={"effectif_2026": "Emplois 2026", "zone": "", "evolution_pct": "Évol. %"},
                title="Top 15 ZAE — Effectifs 2026",
                height=450,
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"}, margin=dict(l=10))
            st.plotly_chart(fig, use_container_width=True)

        with col_b:
            fig2 = px.scatter(
                df,
                x="evolution_pct",
                y="effectif_2026",
                color="evolution_pct",
                color_continuous_scale=["#A8001C", "#EEEEEE", "#1F6B35"],
                color_continuous_midpoint=0,
                size="effectif_2026",
                size_max=40,
                hover_data=["zone", "commune"],
                labels={"evolution_pct": "Évolution (%)", "effectif_2026": "Emplois 2026"},
                title="Taille vs Dynamique",
                height=450,
            )
            fig2.add_vline(x=0, line_dash="dash", line_color="#595959", opacity=0.5)
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("#### Détail par zone")

        def color_evol(val):
            if val < -20:
                return "background-color: #FAD4DB"
            elif val > 20:
                return "background-color: #D9EFE0"
            return ""

        cols_affichage = ["zone", "commune", "effectif_2021", "effectif_2026", "evolution_pct",
                          "etab_2021", "etab_2026"]
        df_display = df[cols_affichage].copy()
        df_display.columns = ["Zone", "Commune", "Emplois 2021", "Emplois 2026",
                               "Évol. %", "Étab. 2021", "Étab. 2026"]
        st.dataframe(
            df_display.style.map(color_evol, subset=["Évol. %"]).format({"Évol. %": "{:.1f}"}),
            use_container_width=True,
            height=400,
        )

        csv_bytes = df_display.to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button("⬇️ Exporter CSV", csv_bytes, "zae_rpdf.csv", "text/csv")


# ─── TAB 2 : Signaux faibles ──────────────────────────────────────────────────
with tab2:
    if not signaux:
        st.info("Signaux non disponibles.")
    else:
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            badge = "🔴" if signaux.get("score_risque_global") == "élevé" else (
                "🟡" if signaux.get("score_risque_global") == "modéré" else "🟢")
            st.metric("Score de risque global",
                      f"{badge} {signaux.get('score_risque_global', 'N/A').capitalize()}")
        with col_s2:
            st.metric("Zones anomalies détectées", signaux.get("nb_anomalies", 0),
                      help="Isolation Forest — ZAE dont l'évolution sort du cluster de pairs")
        with col_s3:
            st.metric("Alertes BODACC actives", signaux.get("nb_alertes_bodacc", 0),
                      help="Liquidations et redressements judiciaires")

        st.markdown("#### Zones en situation anormale (algorithme Isolation Forest)")
        anomalies = signaux.get("zones_anomalies", [])
        if anomalies:
            df_anom = pd.DataFrame(anomalies)
            st.dataframe(df_anom, use_container_width=True)
        else:
            st.success("Aucune anomalie détectée sur la période.")

        st.markdown("#### Top 5 zones en forte croissance")
        top_c = signaux.get("top_croissance", [])
        if top_c:
            df_top = pd.DataFrame(top_c)
            fig3 = px.bar(
                df_top, x="zone", y="evolution_pct",
                color="evolution_pct",
                color_continuous_scale=["#1F6B35", "#D9EFE0"],
                title="Zones à forte croissance 2021–2026 (>20%, effectif >100)",
            )
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("Aucune zone en forte croissance détectée.")


# ─── TAB 3 : Alertes BODACC ───────────────────────────────────────────────────
with tab3:
    st.markdown("#### 🚨 Procédures collectives — Val-d'Oise (95) & Seine-et-Marne (77)")
    st.caption("Source : BODACC (Bulletin Officiel des Annonces Civiles et Commerciales) — mis à jour quotidiennement")

    # Filtres
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        type_filtre = st.selectbox(
            "Type d'annonce",
            ["Tous", "Procédures collectives", "Ventes et cessions",
             "Créations", "Modifications diverses", "Radiations", "Dépôts des comptes"],
            key="type_bodacc"
        )
    with col_f2:
        dept_filtre = st.selectbox("Département", ["Tous", "95 - Val-d'Oise", "77 - Seine-et-Marne"],
                                   key="dept_bodacc")
    with col_f3:
        nb_alertes = st.slider("Nombre d'annonces à afficher", 20, 200, 50, key="nb_bodacc")

    alertes = fetch_alertes(limit=nb_alertes)

    if alertes.empty:
        st.info("Aucune alerte BODACC disponible. Le scraper sera lancé au prochain démarrage.")
    else:
        # Statistiques globales
        nb_procedures = len(alertes[alertes.get("type_avis", pd.Series()).str.contains(
            "Procédures|proc", case=False, na=False
        )]) if "type_avis" in alertes.columns else 0

        col_b1, col_b2, col_b3 = st.columns(3)
        with col_b1:
            st.metric("Total alertes affichées", len(alertes))
        with col_b2:
            st.metric("Procédures collectives", nb_procedures,
                      delta="liquidations & redressements", delta_color="inverse")
        with col_b3:
            if "date_parution" in alertes.columns:
                date_max = alertes["date_parution"].max()
                st.metric("Dernière mise à jour", str(date_max)[:10] if date_max else "N/A")

        st.divider()

        # Affichage enrichi des procédures collectives
        if "type_avis" in alertes.columns:
            proc_coll = alertes[alertes["type_avis"].str.contains(
                "Procédures|proc|liquidation|redressement|sauvegarde",
                case=False, na=False
            )]
            if not proc_coll.empty:
                st.markdown(f"##### 🔴 {len(proc_coll)} procédure(s) collective(s)")
                for _, row in proc_coll.head(20).iterrows():
                    denom = row.get("denomination", "Entreprise inconnue") or "Entreprise inconnue"
                    commune = row.get("commune", "") or ""
                    cp = row.get("cp", "") or ""
                    type_avis = row.get("type_avis", "") or ""
                    date_p = str(row.get("date_parution", ""))[:10]
                    siret = row.get("siret", "") or ""

                    st.markdown(f"""
<div class="bodacc-card">
  <div class="bodacc-denomination">🏢 {denom}</div>
  <div class="bodacc-meta">
    📍 {commune} ({cp}) &nbsp;|&nbsp;
    ⚖️ {type_avis} &nbsp;|&nbsp;
    📅 {date_p}
    {"&nbsp;|&nbsp; SIRET : " + siret if siret else ""}
  </div>
</div>
""", unsafe_allow_html=True)

        st.divider()

        # Tableau complet filtrable
        st.markdown("##### Toutes les alertes")
        df_alertes_display = alertes.copy()
        if "alerte" in df_alertes_display.columns:
            df_alertes_display = df_alertes_display.drop(columns=["alerte"])

        rename_map = {
            "denomination": "Entreprise",
            "commune": "Commune",
            "cp": "Code postal",
            "type_avis": "Type d'annonce",
            "date_parution": "Date parution",
            "siret": "SIRET",
            "source": "Source",
        }
        df_alertes_display = df_alertes_display.rename(
            columns={k: v for k, v in rename_map.items() if k in df_alertes_display.columns}
        )

        st.dataframe(df_alertes_display, use_container_width=True, height=350)

        # Export
        csv_alertes = df_alertes_display.to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button(
            "⬇️ Exporter les alertes CSV",
            csv_alertes,
            "alertes_bodacc.csv",
            "text/csv"
        )

    st.markdown("""
    ---
    **Source** : BODACC — Val-d'Oise (95) et Seine-et-Marne (77).
    Mise à jour automatique au démarrage de l'application (30 derniers jours).
    """)


# ─── TAB 4 : Prévisions ───────────────────────────────────────────────────────
with tab4:
    st.markdown("#### Projection d'emploi par zone")

    df_zae = fetch_zae()
    if not df_zae.empty:
        zone_sel = st.selectbox("Sélectionner une zone", df_zae["zone"].tolist())
        horizon = st.slider("Horizon de prévision (années)", 1, 10, 5)

        if st.button("Calculer la projection"):
            try:
                resp = requests.get(
                    f"{API_URL}/previsions/{zone_sel}",
                    params={"horizon": horizon},
                    timeout=10,
                )
                prev = resp.json()

                st.info(f"⚠️ {prev.get('avertissement', '')}")

                historique = pd.DataFrame([
                    {"annee": 2021, "emplois": df_zae[df_zae["zone"] == zone_sel]["effectif_2021"].values[0]},
                    {"annee": 2026, "emplois": prev["effectif_2026"]},
                ])
                projections = pd.DataFrame(prev["projections"]).rename(
                    columns={"emplois_projetes": "emplois"}
                )

                fig4 = go.Figure()
                fig4.add_trace(go.Scatter(
                    x=historique["annee"], y=historique["emplois"],
                    mode="lines+markers", name="Historique",
                    line=dict(color="#2E5597", width=2),
                ))
                fig4.add_trace(go.Scatter(
                    x=projections["annee"], y=projections["emplois"],
                    mode="lines+markers", name="Projection",
                    line=dict(color="#C55A11", dash="dash", width=2),
                ))
                fig4.update_layout(
                    title=f"Projection emploi — {zone_sel}",
                    xaxis_title="Année", yaxis_title="Emplois estimés",
                )
                st.plotly_chart(fig4, use_container_width=True)

                col_p1, col_p2 = st.columns(2)
                col_p1.metric("Taux annuel moyen", f"{prev['taux_annuel_moyen']:+.1f} %/an")
                col_p2.metric(
                    f"Emplois projetés {2026 + horizon}",
                    f"{prev['projections'][-1]['emplois_projetes']:,}".replace(",", " ")
                )
            except Exception as e:
                st.error(f"Erreur : {e}")
    else:
        st.info("Données ZAE non disponibles.")


# ─── TAB 5 : Machine Learning ─────────────────────────────────────────────────
with tab5:
    st.markdown("#### Prédictions par Machine Learning — avec explications")
    st.caption(
        "Modèles entraînés sur l'ensemble des 67 zones (apprentissage transversal). "
        "Chaque prédiction est accompagnée de ses facteurs explicatifs (SHAP)."
    )

    try:
        ml_status = requests.get(f"{API_URL}/ml/status", timeout=10, headers=_HEADERS).json()
        cols_status = st.columns(3)
        labels = {
            "prevision_emploi": "Prévision d'emploi",
            "scoring_defaillance": "Risque de défaillance",
            "devitalisation": "Risque de dévitalisation",
        }
        for i, (key, info) in enumerate(ml_status.items()):
            with cols_status[i]:
                if info.get("entraine"):
                    st.success(f"✅ {labels.get(key, key)}")
                    if info.get("mae_loo"):
                        st.caption(f"MAE (validation LOO) : {info['mae_loo']}")
                else:
                    st.warning(f"⏳ {labels.get(key, key)} — non entraîné")
    except Exception:
        st.error("API ML non disponible.")

    st.divider()

    df_zae_ml = fetch_zae()
    if not df_zae_ml.empty:
        zone_ml = st.selectbox("Zone à analyser", df_zae_ml["zone"].tolist(), key="zone_ml")
        ml_col1, ml_col2, ml_col3 = st.columns(3)

        with ml_col1:
            st.markdown("**Prévision d'emploi (LightGBM)**")
            if st.button("Calculer", key="btn_prevision"):
                try:
                    resp = requests.get(f"{API_URL}/ml/prevision/{zone_ml}", timeout=15, headers=_HEADERS)
                    if resp.status_code == 200:
                        data = resp.json()
                        pred = data["prediction"]
                        st.metric("Évolution projetée (P50)", f"{pred['evolution_pct_p50']:+.1f}%",
                                  help=f"Intervalle : {pred['intervalle_confiance']}")
                        st.caption(f"Incertitude : {pred['intervalle_confiance']}")
                        st.markdown("**Facteurs explicatifs :**")
                        for exp in data["explications"]:
                            st.markdown(f"- {exp['phrase']}")
                    else:
                        st.warning(resp.json().get("detail", "Erreur"))
                except Exception as e:
                    st.error(f"Erreur : {e}")

        with ml_col2:
            st.markdown("**Risque de défaillance (XGBoost)**")
            if st.button("Calculer", key="btn_defaillance"):
                try:
                    resp = requests.get(f"{API_URL}/ml/risque-defaillance/{zone_ml}", timeout=15, headers=_HEADERS)
                    if resp.status_code == 200:
                        data = resp.json()
                        score = data["score"]
                        couleur = {"élevé": "🔴", "modéré": "🟡", "faible": "🟢"}
                        st.metric("Niveau de risque",
                                  f"{couleur.get(score['niveau_risque'],'')} {score['niveau_risque']}",
                                  help=f"Probabilité : {score['probabilite_risque']*100:.0f}%")
                        st.caption(f"⚠️ {data.get('avertissement', '')}")
                        st.markdown("**Facteurs explicatifs :**")
                        for exp in data["explications"]:
                            st.markdown(f"- {exp['phrase']}")
                    else:
                        st.warning(resp.json().get("detail", "Erreur"))
                except Exception as e:
                    st.error(f"Erreur : {e}")

        with ml_col3:
            st.markdown("**Risque de dévitalisation**")
            st.caption("Zones à dominante commerce uniquement")
            if st.button("Calculer", key="btn_devital"):
                try:
                    resp = requests.get(f"{API_URL}/ml/devitalisation/{zone_ml}", timeout=15, headers=_HEADERS)
                    if resp.status_code == 200:
                        data = resp.json()
                        pred = data["prediction"]
                        st.metric("Taux de vacance projeté", f"{pred['taux_vacance_projete_pct']}%")
                        st.caption(pred["statut"])
                        st.markdown("**Facteurs explicatifs :**")
                        for exp in data["explications"]:
                            st.markdown(f"- {exp['phrase']}")
                    elif resp.status_code == 422:
                        st.info("Ce modèle ne s'applique qu'aux zones à dominante commerciale.")
                    else:
                        st.warning(resp.json().get("detail", "Erreur"))
                except Exception as e:
                    st.error(f"Erreur : {e}")

    st.divider()
    with st.expander("📋 Méthodologie et limites des modèles ML"):
        st.markdown("""
        **Prévision d'emploi** — LightGBM en régression quantile, entraîné sur
        les 67 zones. Validation en Leave-One-Out. Le résultat est
        systématiquement un intervalle [P10, P90], jamais un chiffre unique.

        **Risque de défaillance** — XGBoost entraîné sur un proxy de cible
        (zones dégradées + alertes BODACC). À traiter comme un indicateur
        d'attention, pas un verdict. La fiabilité s'améliorera avec l'accumulation
        de données BODACC dans le temps.

        **Dévitalisation commerciale** — Gradient Boosting sur les zones à
        dominante commerce. Cible proxée en l'absence d'enquête terrain.

        **Explicabilité** — Toutes les prédictions sont accompagnées des
        facteurs SHAP traduits en langage non technique.
        """)
