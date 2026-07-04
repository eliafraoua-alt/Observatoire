"""
Observatoire RPDF — Dashboard Streamlit
Accès direct DuckDB — compatible HF Spaces (port unique 7860).
"""

import os
import duckdb
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date

DB_PATH = os.environ.get("DUCKDB_PATH", "warehouse.duckdb")

st.set_page_config(
    page_title="Observatoire — Roissy Pays de France",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .bodacc-card {
    background: #fff8f8; border-left: 4px solid #A8001C;
    border-radius: 8px; padding: 0.8rem 1rem; margin-bottom: 0.5rem;
  }
  .bodacc-denomination { font-weight: 600; color: #1B2A4A; }
  .bodacc-meta { font-size: 0.8rem; color: #595959; }
  .friche-card {
    background: #fffbf0; border-left: 4px solid #C55A11;
    border-radius: 8px; padding: 0.8rem 1rem; margin-bottom: 0.5rem;
  }
  .friche-nom { font-weight: 600; color: #1B2A4A; }
  .friche-meta { font-size: 0.8rem; color: #595959; }
</style>
""", unsafe_allow_html=True)


def get_db():
    return duckdb.connect(DB_PATH, read_only=False)


@st.cache_data(ttl=300)
def fetch_kpis():
    try:
        con = get_db()
        row = con.execute("""
            SELECT COALESCE(SUM(effectif_2026),0), COUNT(DISTINCT zone),
                   ROUND(AVG(evolution_pct),1),
                   SUM(CASE WHEN evolution_pct>0 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN evolution_pct<-20 THEN 1 ELSE 0 END),
                   ROUND(SUM(effectif_2026)*100.0/179000,1)
            FROM emploi_zae WHERE source='nikonoff_2026'
        """).fetchone()
        con.close()
        if not row or row[0] == 0:
            return None
        return {
            "emplois_zae_total": int(row[0] or 0),
            "nb_zones": int(row[1] or 0),
            "evolution_moy_pct": float(row[2] or 0),
            "zones_en_croissance": int(row[3] or 0),
            "zones_en_alerte": int(row[4] or 0),
            "poids_zae_territoire_pct": float(row[5] or 0),
        }
    except Exception:
        return None


@st.cache_data(ttl=300)
def fetch_zae(commune=None, evol_min=None, evol_max=None):
    try:
        con = get_db()
        where = ["source='nikonoff_2026'"]
        params = []
        if commune:
            where.append("LOWER(commune) LIKE LOWER(?)")
            params.append(f"%{commune}%")
        if evol_min is not None:
            where.append("evolution_pct >= ?")
            params.append(evol_min)
        if evol_max is not None:
            where.append("evolution_pct <= ?")
            params.append(evol_max)
        df = con.execute(
            f"SELECT zone,commune,effectif_2021,effectif_2026,evolution_pct,etab_2021,etab_2026 FROM emploi_zae WHERE {' AND '.join(where)} ORDER BY effectif_2026 DESC LIMIT 100",
            params
        ).df()
        con.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_signaux():
    try:
        con = get_db()
        nb_bodacc = con.execute("SELECT COUNT(*) FROM alertes_bodacc WHERE alerte=true").fetchone()[0]
        top_c = con.execute("""
            SELECT zone, commune, evolution_pct, effectif_2026
            FROM emploi_zae WHERE evolution_pct>20 AND source='nikonoff_2026' AND effectif_2026>100
            ORDER BY evolution_pct DESC LIMIT 5
        """).df().to_dict(orient="records")
        nb_alerte = con.execute("SELECT COUNT(*) FROM emploi_zae WHERE evolution_pct<-20 AND source='nikonoff_2026'").fetchone()[0]
        con.close()
        score = "élevé" if nb_alerte >= 5 else "modéré" if nb_alerte >= 2 else "faible"
        return {"score_risque_global": score, "nb_anomalies": 0,
                "nb_alertes_bodacc": nb_bodacc, "zones_anomalies": [], "top_croissance": top_c}
    except Exception:
        return {}


@st.cache_data(ttl=60)
def fetch_alertes(limit=100):
    try:
        con = get_db()
        df = con.execute(f"""
            SELECT siret, denomination, commune, cp, type_avis, date_parution, source
            FROM alertes_bodacc WHERE alerte=true
            ORDER BY date_parution DESC LIMIT {limit}
        """).df()
        con.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_friches(departement=None, statut=None, type_site=None):
    try:
        con = get_db()
        where = ["1=1"]
        params = []
        if departement and departement != "Tous":
            where.append("departement=?")
            params.append(departement[:2])
        if statut and statut != "Tous":
            where.append("statut=?")
            params.append(statut)
        if type_site and type_site != "Tous":
            where.append("site_type=?")
            params.append(type_site)
        df = con.execute(
            f"SELECT site_id, site_nom, site_type, commune, departement, surface_ha, statut, type_projet, site_url FROM friches WHERE {' AND '.join(where)} ORDER BY surface_ha DESC NULLS LAST LIMIT 500",
            params
        ).df()
        con.close()
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_friches_stats():
    try:
        con = get_db()
        total = con.execute("SELECT COUNT(*) FROM friches").fetchone()[0]
        surface = con.execute("SELECT ROUND(SUM(surface_ha),0) FROM friches WHERE surface_ha IS NOT NULL AND surface_ha < 1000").fetchone()[0]
        par_statut = con.execute("SELECT statut, COUNT(*) as n FROM friches WHERE statut IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 8").df()
        par_dept = con.execute("SELECT departement, COUNT(*) as n FROM friches GROUP BY 1").df()
        par_type = con.execute("SELECT site_type, COUNT(*) as n FROM friches WHERE site_type IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 8").df()
        con.close()
        return {"total": total, "surface_ha": surface, "par_statut": par_statut,
                "par_dept": par_dept, "par_type": par_type}
    except Exception:
        return {}


@st.cache_data(ttl=300)
def fetch_eau_stats():
    try:
        con = get_db()
        total = con.execute("SELECT COUNT(*) FROM eau_indicateurs").fetchone()[0]
        if total == 0:
            con.close()
            return {}
        rendement = con.execute("SELECT ROUND(AVG(rendement_reseau),1) FROM eau_indicateurs WHERE rendement_reseau IS NOT NULL AND rendement_reseau < 100 AND type_service='AEP'").fetchone()[0]
        prix = con.execute("SELECT ROUND(AVG(prix_eau_m3),2) FROM eau_indicateurs WHERE prix_eau_m3 IS NOT NULL AND prix_eau_m3 > 0 AND type_service='AEP'").fetchone()[0]
        desserte = con.execute("SELECT ROUND(AVG(taux_desserte),1) FROM eau_indicateurs WHERE taux_desserte IS NOT NULL AND type_service='AC'").fetchone()[0]
        conformite = con.execute("SELECT ROUND(AVG(conformite_eru),1) FROM eau_indicateurs WHERE conformite_eru IS NOT NULL AND type_service='AC'").fetchone()[0]
        par_annee = con.execute("SELECT annee, ROUND(AVG(rendement_reseau),1) as rend, ROUND(AVG(prix_eau_m3),2) as prix FROM eau_indicateurs WHERE rendement_reseau IS NOT NULL AND rendement_reseau<100 AND type_service='AEP' GROUP BY 1 ORDER BY 1").df()
        df_detail = con.execute("SELECT commune, departement, annee, type_service, ROUND(rendement_reseau,1) as rendement, ROUND(prix_eau_m3,2) as prix_m3, ROUND(taux_desserte,1) as desserte, ROUND(conformite_eru,1) as conformite_eru FROM eau_indicateurs WHERE commune IS NOT NULL AND commune != '' ORDER BY departement, commune, annee DESC LIMIT 200").df()
        con.close()
        return {"total": total, "rendement_moyen": rendement, "prix_moyen_m3": prix,
                "desserte_moy": desserte, "conformite_eru_moy": conformite,
                "par_annee": par_annee, "detail": df_detail}
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
    - Nikonoff Conseils avr. 2026
    - BODACC (quotidien)
    - Cartofriches / Cerema
    - Hub'Eau / SISPEA

    **Périmètre** : 26 communes, 67 ZAE, CA-RPDF
    """)
    if st.button("🔄 Actualiser"):
        st.cache_data.clear()
        st.rerun()
    st.markdown(f"*Données au {datetime.today().strftime('%d/%m/%Y')}*")


# ── En-tête ───────────────────────────────────────────────────────────────────
st.title("📊 Observatoire Économique & Territorial")
st.markdown("**Communauté d'Agglomération Roissy Pays de France**")
st.divider()

# ── KPIs ──────────────────────────────────────────────────────────────────────
kpis = fetch_kpis()
signaux = fetch_signaux()
friches_stats = fetch_friches_stats()
eau_stats = fetch_eau_stats()

col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
if kpis:
    with col1:
        st.metric("Emplois ZAE", f"{kpis['emplois_zae_total']:,}".replace(",", " "))
    with col2:
        st.metric("Zones analysées", kpis["nb_zones"])
    with col3:
        st.metric("Évol. moy.", f"{kpis['evolution_moy_pct']:+.1f}%")
    with col4:
        st.metric("Alertes BODACC", signaux.get("nb_alertes_bodacc", 0))
with col5:
    st.metric("Friches", friches_stats.get("total", 0), help="Val-d'Oise + Seine-et-Marne")
with col6:
    surface = friches_stats.get("surface_ha")
    st.metric("Surface friches", f"{int(surface):,} ha".replace(",", " ") if surface else "N/A")
with col7:
    st.metric("Prix eau moyen", f"{eau_stats.get('prix_moyen_m3', 'N/A')} €/m³" if eau_stats else "N/A")

st.divider()

# ── Onglets ───────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🏭 Zones d'activité", "📈 Signaux faibles", "🚨 Alertes BODACC",
    "🏗️ Friches", "💧 Eau", "🔮 Prévisions"
])


# ─── TAB 1 : ZAE ─────────────────────────────────────────────────────────────
with tab1:
    df = fetch_zae(commune=commune_filtre or None, evol_min=evol_min, evol_max=evol_max)
    if df.empty:
        st.info("Aucune donnée disponible.")
    else:
        col_a, col_b = st.columns([3, 2])
        with col_a:
            top15 = df.nlargest(15, "effectif_2026")
            fig = px.bar(top15, x="effectif_2026", y="zone", orientation="h",
                color="evolution_pct",
                color_continuous_scale=["#A8001C","#F5C4B3","#EEEEEE","#D9EFE0","#1F6B35"],
                color_continuous_midpoint=0,
                labels={"effectif_2026":"Emplois 2026","zone":"","evolution_pct":"Évol. %"},
                title="Top 15 ZAE — Effectifs 2026", height=450)
            fig.update_layout(yaxis={"categoryorder":"total ascending"})
            st.plotly_chart(fig, use_container_width=True)
        with col_b:
            fig2 = px.scatter(df, x="evolution_pct", y="effectif_2026",
                color="evolution_pct",
                color_continuous_scale=["#A8001C","#EEEEEE","#1F6B35"],
                color_continuous_midpoint=0, size="effectif_2026", size_max=40,
                hover_data=["zone","commune"], title="Taille vs Dynamique", height=450)
            fig2.add_vline(x=0, line_dash="dash", line_color="#595959", opacity=0.5)
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("#### Détail par zone")
        def color_evol(val):
            if val < -20: return "background-color: #FAD4DB"
            elif val > 20: return "background-color: #D9EFE0"
            return ""
        df_d = df[["zone","commune","effectif_2021","effectif_2026","evolution_pct","etab_2021","etab_2026"]].copy()
        df_d.columns = ["Zone","Commune","Emplois 2021","Emplois 2026","Évol. %","Étab. 2021","Étab. 2026"]
        st.dataframe(df_d.style.map(color_evol, subset=["Évol. %"]).format({"Évol. %": "{:.1f}"}),
                     use_container_width=True, height=400)
        csv = df_d.to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button("⬇️ Exporter CSV", csv, "zae_rpdf.csv", "text/csv")


# ─── TAB 2 : Signaux faibles ─────────────────────────────────────────────────
with tab2:
    if not signaux:
        st.info("Signaux non disponibles.")
    else:
        col_s1, col_s2, col_s3 = st.columns(3)
        with col_s1:
            badge = "🔴" if signaux.get("score_risque_global") == "élevé" else (
                "🟡" if signaux.get("score_risque_global") == "modéré" else "🟢")
            st.metric("Score de risque global", f"{badge} {signaux.get('score_risque_global','N/A').capitalize()}")
        with col_s2:
            st.metric("Zones anomalies", signaux.get("nb_anomalies", 0))
        with col_s3:
            st.metric("Alertes BODACC", signaux.get("nb_alertes_bodacc", 0))

        st.markdown("#### Zones en situation anormale")
        if signaux.get("zones_anomalies"):
            st.dataframe(pd.DataFrame(signaux["zones_anomalies"]), use_container_width=True)
        else:
            st.success("Aucune anomalie détectée sur la période.")

        st.markdown("#### Top 5 zones en forte croissance")
        top_c = signaux.get("top_croissance", [])
        if top_c:
            df_top = pd.DataFrame(top_c)
            fig3 = px.bar(df_top, x="zone", y="evolution_pct",
                color="evolution_pct", color_continuous_scale=["#1F6B35","#D9EFE0"],
                title="Zones à forte croissance 2021–2026 (>20%, effectif >100)")
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("Aucune zone en forte croissance détectée.")


# ─── TAB 3 : Alertes BODACC ──────────────────────────────────────────────────
with tab3:
    st.markdown("#### 🚨 Procédures collectives — Val-d'Oise (95) & Seine-et-Marne (77)")
    st.caption("Source : BODACC — mis à jour au démarrage (7 derniers jours)")

    nb_alertes = st.slider("Nombre d'alertes", 20, 500, 100, key="nb_bodacc")
    alertes = fetch_alertes(limit=nb_alertes)

    if alertes.empty:
        st.info("Aucune alerte BODACC disponible.")
    else:
        col_b1, col_b2, col_b3 = st.columns(3)
        with col_b1:
            st.metric("Total alertes", len(alertes))
        with col_b2:
            proc = alertes[alertes.get("type_avis", pd.Series()).str.contains("Proc|liquid|redress", case=False, na=False)] if "type_avis" in alertes.columns else pd.DataFrame()
            st.metric("Procédures collectives", len(proc), delta_color="inverse")
        with col_b3:
            if "date_parution" in alertes.columns:
                st.metric("Dernière annonce", str(alertes["date_parution"].max())[:10])

        if not proc.empty:
            st.markdown(f"##### 🔴 {len(proc)} procédure(s) collective(s)")
            for _, row in proc.head(20).iterrows():
                denom = row.get("denomination","") or "Entreprise inconnue"
                commune = row.get("commune","") or ""
                cp = row.get("cp","") or ""
                type_avis = row.get("type_avis","") or ""
                date_p = str(row.get("date_parution",""))[:10]
                siret = row.get("siret","") or ""
                st.markdown(f"""<div class="bodacc-card">
  <div class="bodacc-denomination">🏢 {denom}</div>
  <div class="bodacc-meta">📍 {commune} ({cp}) &nbsp;|&nbsp; ⚖️ {type_avis} &nbsp;|&nbsp; 📅 {date_p}{" &nbsp;|&nbsp; SIRET : " + siret if siret else ""}</div>
</div>""", unsafe_allow_html=True)

        st.divider()
        df_aff = alertes.copy()
        if "alerte" in df_aff.columns:
            df_aff = df_aff.drop(columns=["alerte"])
        df_aff = df_aff.rename(columns={"denomination":"Entreprise","commune":"Commune",
            "cp":"CP","type_avis":"Type","date_parution":"Date","siret":"SIRET","source":"Source"})
        st.dataframe(df_aff, use_container_width=True, height=350)
        csv_a = df_aff.to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button("⬇️ Exporter CSV", csv_a, "alertes_bodacc.csv", "text/csv")


# ─── TAB 4 : Friches ─────────────────────────────────────────────────────────
with tab4:
    st.markdown("#### 🏗️ Friches industrielles et urbaines")
    st.caption("Source : Cartofriches / Cerema — data.gouv.fr — Licence Ouverte 2.0")

    if not friches_stats or friches_stats.get("total", 0) == 0:
        st.info("Données Cartofriches non disponibles. Lancez `python ingestion/scrapers/scraper_friches.py`")
    else:
        # KPIs friches
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        with col_f1:
            st.metric("Total friches", friches_stats.get("total", 0))
        with col_f2:
            surface = friches_stats.get("surface_ha")
            st.metric("Surface totale", f"{int(surface):,} ha".replace(",", " ") if surface else "N/A",
                      help="Hors valeurs aberrantes >1000 ha")
        with col_f3:
            par_dept = friches_stats.get("par_dept", pd.DataFrame())
            n95 = par_dept[par_dept["departement"] == "95"]["n"].values[0] if not par_dept.empty and "95" in par_dept["departement"].values else 0
            st.metric("Val-d'Oise (95)", int(n95))
        with col_f4:
            n77 = par_dept[par_dept["departement"] == "77"]["n"].values[0] if not par_dept.empty and "77" in par_dept["departement"].values else 0
            st.metric("Seine-et-Marne (77)", int(n77))

        st.divider()

        # Filtres
        col_ff1, col_ff2, col_ff3 = st.columns(3)
        with col_ff1:
            dept_sel = st.selectbox("Département", ["Tous", "95 - Val-d'Oise", "77 - Seine-et-Marne"], key="dept_friche")
        with col_ff2:
            statuts = ["Tous"] + list(friches_stats.get("par_statut", pd.DataFrame()).get("statut", pd.Series()).dropna().unique())
            statut_sel = st.selectbox("Statut", statuts, key="statut_friche")
        with col_ff3:
            types = ["Tous"] + list(friches_stats.get("par_type", pd.DataFrame()).get("site_type", pd.Series()).dropna().unique())
            type_sel = st.selectbox("Type de friche", types, key="type_friche")

        dept_param = dept_sel if dept_sel != "Tous" else None
        statut_param = statut_sel if statut_sel != "Tous" else None
        type_param = type_sel if type_sel != "Tous" else None
        df_friches = fetch_friches(departement=dept_param, statut=statut_param, type_site=type_param)

        if not df_friches.empty:
            col_g1, col_g2 = st.columns(2)

            with col_g1:
                par_statut = friches_stats.get("par_statut", pd.DataFrame())
                if not par_statut.empty:
                    fig_statut = px.pie(par_statut, values="n", names="statut",
                        title="Répartition par statut",
                        color_discrete_sequence=px.colors.qualitative.Set2)
                    fig_statut.update_traces(textposition="inside", textinfo="percent+label")
                    st.plotly_chart(fig_statut, use_container_width=True)

            with col_g2:
                par_type = friches_stats.get("par_type", pd.DataFrame())
                if not par_type.empty:
                    fig_type = px.bar(par_type, x="n", y="site_type", orientation="h",
                        title="Types de friches",
                        color="n", color_continuous_scale=["#EEEEEE", "#C55A11"])
                    fig_type.update_layout(yaxis={"categoryorder": "total ascending"})
                    st.plotly_chart(fig_type, use_container_width=True)

            st.markdown(f"#### {len(df_friches)} friche(s) — Top par surface")

            # Affichage cartes pour les plus grandes friches
            grandes = df_friches[df_friches["surface_ha"].notna()].head(10)
            if not grandes.empty:
                for _, row in grandes.iterrows():
                    nom = row.get("site_nom","") or "Site sans nom"
                    commune = row.get("commune","") or ""
                    dept = row.get("departement","") or ""
                    surface_ha = row.get("surface_ha")
                    statut = row.get("statut","") or ""
                    type_s = row.get("site_type","") or ""
                    url = row.get("site_url","") or ""
                    surf_str = f"{surface_ha:.1f} ha" if surface_ha else "surface N/A"
                    lien = f' &nbsp;|&nbsp; <a href="{url}" target="_blank">Voir fiche</a>' if url and url.startswith("http") else ""
                    st.markdown(f"""<div class="friche-card">
  <div class="friche-nom">🏭 {nom}</div>
  <div class="friche-meta">📍 {commune} ({dept}) &nbsp;|&nbsp; 📐 {surf_str} &nbsp;|&nbsp; {type_s} &nbsp;|&nbsp; {statut}{lien}</div>
</div>""", unsafe_allow_html=True)

            st.divider()
            st.markdown("#### Tableau complet")
            df_aff_f = df_friches.rename(columns={
                "site_id":"ID","site_nom":"Nom","site_type":"Type",
                "commune":"Commune","departement":"Dept",
                "surface_ha":"Surface (ha)","statut":"Statut","type_projet":"Projet"
            })
            if "site_url" in df_aff_f.columns:
                df_aff_f = df_aff_f.drop(columns=["site_url"])
            st.dataframe(df_aff_f, use_container_width=True, height=400)
            csv_f = df_aff_f.to_csv(index=False, sep=";").encode("utf-8-sig")
            st.download_button("⬇️ Exporter CSV", csv_f, "friches_rpdf.csv", "text/csv")

    st.markdown("---\n**Source** : Cartofriches (Cerema) — Val-d'Oise (95) et Seine-et-Marne (77).")


# ─── TAB 5 : Eau ─────────────────────────────────────────────────────────────
with tab5:
    st.markdown("#### 💧 Services d'eau potable et d'assainissement")
    st.caption("Source : Hub'Eau / SISPEA — données 2017-2019 (dernières disponibles via API)")

    if not eau_stats or eau_stats.get("total", 0) == 0:
        st.info("Données eau non disponibles. Lancez `python ingestion/scrapers/scraper_eau.py`")
    else:
        # KPIs eau
        col_e1, col_e2, col_e3, col_e4 = st.columns(4)
        with col_e1:
            st.metric("Services recensés", eau_stats.get("total", 0))
        with col_e2:
            rend = eau_stats.get("rendement_moyen")
            badge_rend = "🟢" if rend and rend >= 80 else "🟡" if rend and rend >= 70 else "🔴"
            st.metric("Rendement réseau moyen", f"{badge_rend} {rend}%" if rend else "N/A",
                      help="Seuil réglementaire : 80% (commune >500 hab.)")
        with col_e3:
            st.metric("Prix eau moyen", f"{eau_stats.get('prix_moyen_m3','N/A')} €/m³",
                      help="Prix TTC eau potable — moyenne des services AEP")
        with col_e4:
            conf = eau_stats.get("conformite_eru_moy")
            st.metric("Conformité ERU", f"{conf}%" if conf else "N/A",
                      help="Conformité à la Directive Eaux Résiduaires Urbaines")

        st.divider()

        # Évolution par année
        par_annee = eau_stats.get("par_annee", pd.DataFrame())
        if not par_annee.empty:
            col_ea1, col_ea2 = st.columns(2)
            with col_ea1:
                fig_rend = px.bar(par_annee, x="annee", y="rend",
                    title="Rendement moyen réseau AEP par année (%)",
                    labels={"annee":"Année","rend":"Rendement (%)"},
                    color="rend",
                    color_continuous_scale=["#A8001C","#EEEEEE","#1F6B35"],
                    color_continuous_midpoint=80)
                fig_rend.add_hline(y=80, line_dash="dash", line_color="#A8001C",
                                   annotation_text="Seuil réglementaire 80%")
                st.plotly_chart(fig_rend, use_container_width=True)
            with col_ea2:
                fig_prix = px.bar(par_annee, x="annee", y="prix",
                    title="Prix moyen eau potable par année (€/m³)",
                    labels={"annee":"Année","prix":"Prix (€/m³)"},
                    color_discrete_sequence=["#2E5597"])
                st.plotly_chart(fig_prix, use_container_width=True)

        st.divider()
        st.markdown("#### Détail par commune")

        detail = eau_stats.get("detail", pd.DataFrame())
        if not detail.empty:
            dept_eau = st.selectbox("Département", ["Tous", "95", "77"], key="dept_eau")
            type_eau = st.selectbox("Type de service", ["Tous", "AEP", "AC"], key="type_eau")

            df_eau = detail.copy()
            if dept_eau != "Tous":
                df_eau = df_eau[df_eau["departement"] == dept_eau]
            if type_eau != "Tous":
                df_eau = df_eau[df_eau["type_service"] == type_eau]

            df_eau = df_eau.rename(columns={
                "commune":"Commune","departement":"Dept","annee":"Année",
                "type_service":"Service","rendement":"Rendement %",
                "prix_m3":"Prix €/m³","desserte":"Desserte %","conformite_eru":"Conf. ERU %"
            })

            def color_rend(val):
                try:
                    v = float(val)
                    if v < 70: return "background-color: #FAD4DB"
                    elif v >= 80: return "background-color: #D9EFE0"
                    return "background-color: #FFF3CD"
                except Exception:
                    return ""

            if "Rendement %" in df_eau.columns:
                st.dataframe(
                    df_eau.style.map(color_rend, subset=["Rendement %"]),
                    use_container_width=True, height=400
                )
            else:
                st.dataframe(df_eau, use_container_width=True, height=400)

            csv_e = df_eau.to_csv(index=False, sep=";").encode("utf-8-sig")
            st.download_button("⬇️ Exporter CSV", csv_e, "eau_rpdf.csv", "text/csv")

        st.markdown("""
        ---
        **Indicateurs clés :**
        - **Rendement réseau** : part de l'eau produite effectivement livrée aux abonnés. Seuil réglementaire 80%.
        - **Prix eau** : prix TTC au m³ eau potable (abonnement + consommation, 120 m³/an de référence).
        - **Taux de desserte** : % de la population raccordée au réseau d'assainissement collectif.
        - **Conformité ERU** : conformité à la Directive Eaux Résiduaires Urbaines.

        *Données Hub'Eau SISPEA 2017-2019. Les données 2020-2024 sont disponibles sur data.gouv.fr en CSV annuel.*
        """)


# ─── TAB 6 : Prévisions ──────────────────────────────────────────────────────
with tab6:
    st.markdown("#### Projection d'emploi par zone")
    df_zae = fetch_zae()
    if not df_zae.empty:
        zone_sel = st.selectbox("Sélectionner une zone", df_zae["zone"].tolist())
        horizon = st.slider("Horizon de prévision (années)", 1, 10, 5)

        if st.button("Calculer la projection"):
            try:
                row_z = df_zae[df_zae["zone"] == zone_sel].iloc[0]
                e2021 = int(row_z["effectif_2021"])
                e2026 = int(row_z["effectif_2026"])
                taux = (e2026 / max(e2021, 1)) ** (1/5) - 1

                historique = pd.DataFrame([{"annee": 2021, "emplois": e2021}, {"annee": 2026, "emplois": e2026}])
                projections = []
                e_courant = e2026
                for i in range(1, horizon + 1):
                    e_courant = round(e_courant * (1 + taux))
                    projections.append({"annee": 2026 + i, "emplois": e_courant})
                df_proj = pd.DataFrame(projections)

                fig4 = go.Figure()
                fig4.add_trace(go.Scatter(x=historique["annee"], y=historique["emplois"],
                    mode="lines+markers", name="Historique", line=dict(color="#2E5597", width=2)))
                fig4.add_trace(go.Scatter(x=df_proj["annee"], y=df_proj["emplois"],
                    mode="lines+markers", name="Projection", line=dict(color="#C55A11", dash="dash", width=2)))
                fig4.update_layout(title=f"Projection emploi — {zone_sel}",
                                   xaxis_title="Année", yaxis_title="Emplois")
                st.plotly_chart(fig4, use_container_width=True)

                col_p1, col_p2 = st.columns(2)
                col_p1.metric("Taux annuel moyen", f"{taux*100:+.1f} %/an")
                col_p2.metric(f"Emplois {2026+horizon}", f"{projections[-1]['emplois']:,}".replace(",", " "))
                st.info("⚠️ Projection indicative — extrapolation du taux 2021-2026.")
            except Exception as e:
                st.error(f"Erreur : {e}")
    else:
        st.info("Données ZAE non disponibles.")
