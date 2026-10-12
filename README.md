# BI pour l'Agriculture Intelligente

Système décisionnel pour un district d'irrigation californien : entrepôt PostgreSQL en constellation de faits, collecte de données publiques réelles, couche de capteurs IoT simulée, 4 modèles de machine learning et modèle Power BI.

## 1. Prérequis
- Python 3.11 ou plus récent
- PostgreSQL (base `bi_agriculture_dw` déjà créée, vide)
- Accès Internet (data.ca.gov et open-meteo.com) pour la collecte

## 2. Installation (PowerShell, dans le dossier du projet)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # puis ouvrir .env et mettre le mot de passe PostgreSQL
```

## 3. Fichiers attendus dans `data/raw/`
Les noms sont définis dans `config/settings.yml` (section `fichiers`) ; adaptez-les si vous renommez un fichier.
| Source | Fichier / dossier | Usage |
|---|---|---|
| Water Rights Irrigation Use | `water-rights-irrigation-water-use-annual-report.csv` | fait des déclarations, dimensions exploitant / culture / source / type de droit |
| ET satellite par bassin | `gw_basin_ag_mask_open_data.csv` | fait ET par bassin |
| ET satellite par comté | `et_comte.csv` (téléchargé par `extract` s'il est absent) | fait ET par comté |
| Statewide Crop Mapping | dossier `i15_crop_mapping_2024_provisional/` (le `.shp` et ses fichiers `.dbf .shx .prj .cpg` au même endroit) | surface agricole par comté, 200 parcelles réelles pour les capteurs |
| CIMIS Weather Stations | `i04_CIMIS_Weather_Stations.csv` | informatif (liste des stations) |
| Open-Meteo | téléchargé par `extract` | fait météo |

## 4. Exécution, dans cet ordre
```powershell
python run.py init-db      # crée les schémas dwh et etl (efface leur contenu)
python run.py extract      # télécharge ce qui manque (ET par comté, météo Open-Meteo) ; ne retélécharge pas les fichiers déjà présents
python run.py profile      # affiche les colonnes réelles de chaque fichier et la correspondance utilisée (copie dans docs/profil_sources.txt)
python run.py simulate     # génère les 365 400 relevés de capteurs simulés
python run.py etl          # charge dimensions et faits
python run.py ml           # entraîne les 4 modèles et charge FAIT_PREDICTION (3 à 10 minutes)
```
`python run.py all` enchaîne tout. Chaque étape peut être relancée seule (l'ETL recharge les faits à zéro ; relancer `ml` ensuite).

**Si `profile` ou `etl` signale des colonnes introuvables** : le message liste les colonnes réelles. Ajouter le bon nom dans `config/column_mapping.yml` (liste d'alias de la section concernée) et relancer.

**Tests uniquement** : `python run.py demo-data` génère des données SYNTHÉTIQUES (à ne pas utiliser pour vos résultats) (le journal `etl.journal` indique `mode_donnees = 'demo'`). `python run.py extract` les remplace par les vraies données.

## 5. Vérifier le résultat (SQL)
```sql
SELECT * FROM etl.controle ORDER BY id;          -- réconciliations source -> entrepôt
SELECT * FROM etl.rejets ORDER BY id;            -- lignes écartées et motif
SELECT type_prediction, count(*) FROM dwh.fait_prediction GROUP BY 1;
SELECT * FROM dwh.ref_modele_evaluation ORDER BY cible, metrique;
```

## 6. Contenu
```
config/      settings.yml (paramètres), column_mapping.yml (alias de colonnes)
sql/         01_schema.sql (entrepôt)
src/bi_agri/ extract/ (CKAN, Open-Meteo)  simulate/ (capteurs)  etl/ (chargement, contrôles)  ml/ (4 modèles)
powerbi/     measures.dax, README_powerbi.md
docs/        PLAN.md
data/        raw/ (sources), staging/ (simulation), models/  - ignorés par git
```

## 7. Écarts avec le document de modélisation du SID (v1)
- `fait_declaration_irrigation` : ajout de `volume_declare_acft` (volume utilisé déclaré, si la source le fournit).
- `fait_prediction` : ajout de `id_declaration` et `motif_anomalie` pour lister les anomalies.
- Tables d'appui ajoutées : `ref_modele_evaluation`, `ref_segment`, `etl.journal`, `etl.rejets`, `etl.controle`.
- `dim_temps` va jusqu'au 31/12/2027 pour contenir les prévisions à 12 mois.
- **ETL en Python** et non en Talend : un job Talend se construit dans l'interface graphique et ne peut pas être fourni sous forme de code.
- Régression de la demande : la météo n'existe que pour 4 comtés de référence (une par vallée), pas pour les 58 comtés. Le modèle principal utilise donc des retards (mois précédent, même mois l'an dernier), la saison et le comté ; un diagnostic avec la météo est calculé sur les 4 vallées (`demande_mensuelle_climat`).
- Prophet est facultatif (décommenter dans `requirements.txt`) ; sans lui, SARIMA et Holt-Winters sont comparés.

## 8. Hypothèses à valider
- Rattachement comté → vallée (`comtes_par_vallee`) et comté de référence de chaque vallée.
- Familles de culture et catégories de source d'eau : règles par mots-clés dans `settings.yml`.
- Déclaration « exploitable » : année 2019-2024, irrigation effective (surface ou volume déclaré > 0), au moins un volume renseigné.
- Les colonnes exactes des fichiers réels n'ont pas pu être vérifiées depuis l'environnement de développement : lancer `profile` en premier.
- Seule donnée simulée : les relevés des capteurs IoT (aucun district ne les publie). Les parcelles qui les portent sont réelles (crop mapping) ; les relevés suivent l'humidité et la température du sol réelles d'Open-Meteo.
