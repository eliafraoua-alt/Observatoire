-- Mart : KPIs de synthèse du territoire.
-- Reprend la logique de la vue v_kpis_territoire définie en SQL brut dans
-- observatoire_ingestion.py, mais versionnée, documentée et testable via dbt.
-- À terme, cette table dbt doit devenir la source de vérité unique pour
-- l'endpoint /kpis de l'API (actuellement encore branché sur la vue brute).

with zae as (
    select * from {{ ref('stg_emploi_zae') }}
),

agregats as (
    select
        sum(effectif_2026)                                              as emplois_zae_total,
        count(distinct zone)                                            as nb_zones,
        round(avg(evolution_pct), 1)                                    as evolution_moy_pct,
        sum(case when evolution_pct > 0 then 1 else 0 end)             as zones_en_croissance,
        sum(case when evolution_pct < -20 then 1 else 0 end)           as zones_en_alerte,
        -- 179 000 = emploi total du territoire (INSEE RP2021), valeur de
        -- référence documentée dans le rapport — à terme, brancher sur une
        -- vraie table emploi_territoire alimentée par l'API INSEE Flores
        -- plutôt qu'une constante en dur.
        round(sum(effectif_2026) * 100.0 / 179000, 1)                  as poids_zae_territoire_pct,
        max(date_extraction)                                            as derniere_maj
    from zae
)

select * from agregats
