-- Modèle staging : nettoyage de la table brute alertes_bodacc.

with source as (
    select * from alertes_bodacc
),

nettoye as (
    select
        trim(siret)                      as siret,
        trim(denomination)               as denomination,
        trim(commune)                    as commune,
        trim(cp)                         as cp,
        trim(type_avis)                  as type_avis,
        cast(date_parution as date)      as date_parution,
        coalesce(alerte, false)          as alerte,
        source,
        cast(date_extraction as date)    as date_extraction
    from source
    where commune is not null
)

select * from nettoye
