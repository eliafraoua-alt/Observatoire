-- Mart : dynamique des ZAE avec catégorisation par taille et tendance.
-- Reprend et enrichit la logique de typologie en 4 catégories du rapport
-- d'analyse (pôles métropolitains, logistiques, commerciaux en tension,
-- petites zones), pour que cette segmentation soit calculée une fois et
-- réutilisable par tous les dashboards plutôt que recalculée en Python
-- dans chaque app Streamlit.

with zae as (
    select * from {{ ref('stg_emploi_zae') }}
),

enrichi as (
    select
        *,
        effectif_2026::double / nullif(etab_2026, 0)  as effectif_moyen_2026,
        (etab_2026 - etab_2021)::double
            / nullif(etab_2021, 0) * 100               as delta_etablissements_pct,

        case
            when effectif_2026 >= 5000 then 'pole_majeur'
            when effectif_2026 >= 1000 then 'pole_intermediaire'
            when effectif_2026 >= 100  then 'petit_pole'
            else 'micro_zone'
        end as categorie_taille,

        case
            when evolution_pct >= 20  then 'forte_croissance'
            when evolution_pct >= 0   then 'croissance_moderee'
            when evolution_pct >= -20 then 'recul_modere'
            else 'recul_marque'
        end as categorie_tendance

    from zae
)

select * from enrichi
