# Sources de données — état réel des accès (audit du 30/06/2026)

Ce document journalise les résultats réels de l'audit `robots_gate.audit_source()`
sur les sources candidates. Il doit être mis à jour à chaque ajout ou retrait
de source dans le pipeline.

## Résultat de l'audit initial

| Source | Verdict | Raison |
|--------|---------|--------|
| SeLoger.com | ❌ Refusé | robots.txt interdit `/immobilier-entreprise/` et `/recherche.html` |
| LeBonCoin.fr | ❌ Refusé | robots.txt interdit les pages de recherche |
| PAP.fr | ❌ Refusé | robots.txt interdit `/annonce/...` |
| Indeed.fr | ❌ Refusé | robots.txt interdit `/jobs` et `/emplois` |
| FranceTravail.fr (site web) | ❌ Refusé | robots.txt interdit le scraping — **utiliser l'API officielle**, déjà intégrée dans `observatoire_ingestion.py` |
| data.gouv.fr (HTML) | ❌ Refusé | robots.txt interdit le scraping — **utiliser l'API REST**, déjà intégrée |
| BODACC (portail web) | ❌ Refusé | idem — **API opendatasoft déjà intégrée** |
| INSEE.fr (site web) | ❌ Refusé | idem — **API insee.fr déjà intégrée** |

## Conclusion honnête

**Le scraping HTML générique des grandes plateformes n'est, dans les faits,
quasiment jamais une option viable**, et ce n'est pas spécifique à RPDF :
c'est la politique standard de l'ensemble des grandes plateformes immobilières,
d'emploi et même des portails open data institutionnels. Ces derniers bloquent
volontairement le scraping HTML pour orienter vers leurs API REST — ce qui est
en réalité une meilleure nouvelle : une API structurée est plus fiable et plus
stable dans le temps qu'un scraper HTML qui casse à chaque refonte de site.

**Conséquence concrète pour l'observatoire** : la quasi-totalité des données
utiles transitent déjà par API officielle (`observatoire_ingestion.py`). Le
module de scraping (`scraper_immobilier_emploi.py`) reste dans le pipeline
pour les cas réels où il a un sens : petits sites locaux (CCI, CMA, mairies,
agences indépendantes) sans API mais qui n'interdisent pas le crawl dans leur
robots.txt. Chaque source candidate DOIT être auditée individuellement avant
intégration — le registre dans `scraper_immobilier_emploi.py` ne doit contenir
que des sources dont l'audit a confirmé `autorise: true`.

## Marche à suivre quand une source utile est bloquée

1. Vérifier s'il existe une API officielle (c'est le cas le plus fréquent) :
   - SeLoger Pro : https://www.seloger.com/api (accès partenaire)
   - LeBonCoin Pro : programme partenaire LBC
   - Indeed Publisher : https://docs.indeed.com/job-search-api
2. Si aucune API n'existe, contacter la source pour un partenariat data
   (citer l'usage d'intérêt général de l'observatoire territorial)
3. Si ni l'un ni l'autre n'aboutit, écarter la source — ne jamais contourner
   un refus robots.txt par rotation de proxy, falsification de user-agent,
   ou tout autre moyen technique

## Sources à auditer en priorité (candidats réalistes)

Ces sources sont plus susceptibles d'autoriser le scraping car ce sont de
petites structures sans dispositif anti-bot industriel :

- Sites des communes membres de CA-RPDF (annonces de locaux municipaux)
- CCI Versailles Yvelines / Val d'Oise (à ré-auditer avec la vraie URL exacte
  du site, celle utilisée dans ce dépôt est un exemple à corriger)
- Chambre des métiers et de l'artisanat du Val d'Oise
- Sites d'agences immobilières indépendantes locales

**Action requise avant mise en production** : remplacer les URLs d'exemple
dans `SOURCES_IMMOBILIER_ACTIVITE` et `SOURCES_EMPLOI` par les vraies URLs
des sites ciblés, puis relancer `audit_toutes_sources()` pour confirmer
l'autorisation avant d'activer le scraping dans le DAG.
