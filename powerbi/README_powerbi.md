# Modèle Power BI

Le modèle sémantique se connecte au schéma `dwh` de PostgreSQL (mode Import).

## Relations (toutes 1-N, filtre unidirectionnel de la dimension vers le fait)
| Dimension | Faits reliés |
|---|---|
| dim_temps[sk_temps] | les 6 faits |
| dim_comte[sk_comte] | fait_declaration_irrigation, fait_et_mensuelle_comte, fait_meteo_jour, fait_releve_capteur, fait_prediction |
| dim_exploitant[sk_exploitant] | fait_declaration_irrigation, fait_prediction |
| dim_culture, dim_source_eau, dim_type_droit | fait_declaration_irrigation |
| dim_bassin[sk_bassin] | fait_et_mensuelle_bassin |
| dim_parcelle, dim_capteur | fait_releve_capteur |
| ref_segment[numero_segment] | fait_prediction[numero_segment] |

Bonnes pratiques : masquer les colonnes `sk_*` des faits, trier `nom_mois` par `mois`, trier `annee_mois`, marquer les mesures de `measures.dax` dans une table `_Mesures`.
Les mesures sont dans `measures.dax`.
