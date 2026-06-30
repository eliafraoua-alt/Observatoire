-- Modèle staging : nettoyage et typage de la table brute emploi_zae.
-- Isole les transformations de nettoyage des calculs métier (couche marts),
-- pour que toute correction de qualité de données se fasse à un seul endroit.

with source as (
    select * from emploi_zae
),

nettoye as (
    select
        trim(zone)                       as zone,
        trim(commune)                    as commune,
        cast(effectif_2021 as integer)   as effectif_2021,
        cast(effectif_2026 as integer)   as effectif_2026,
        cast(evolution_pct as double)    as evolution_pct,
        cast(etab_2021 as integer)       as etab_2021,
        cast(etab_2026 as integer)       as etab_2026,
        source,
        cast(date_extraction as date)    as date_extraction
    from source
    where source = 'nikonoff_2026'
      -- Exclusion défensive des lignes manifestement invalides plutôt que
      -- de laisser planter les calculs avals
      and effectif_2021 is not null
      and effectif_2026 is not null
      and etab_2021 >= 0
      and etab_2026 >= 0
)

select * from nettoye
