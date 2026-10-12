# Plan de réalisation

| Phase | Contenu | État |
|---|---|---|
| 1. Entrepôt | Schéma PostgreSQL (constellation : 6 faits, 9 dimensions), tables de suivi ETL | Fait, testé sur données de démo |
| 2. Collecte | CKAN data.ca.gov (Water Rights, ET comté, ET bassin) + Open-Meteo | Code écrit, **à lancer chez vous** (accès réseau) |
| 3. Simulation | 200 capteurs × 1 827 jours calibrés sur Open-Meteo, pannes et dérives | Fait, testé |
| 4. ETL | Python : dimensions (upsert), faits (rechargement complet), contrôles | Fait, testé sur données de démo |
| 5. Modèles | Régression de la demande, prévision à 12 mois, K-Means, anomalies | Fait, testé sur données de démo |
| 6. Power BI | Modèle sémantique, relations, mesures DAX, 4 dashboards | Mesures écrites ; modèle à construire une fois l'entrepôt chargé |
| 7. Recette | Contrôles KPI vs SQL, documentation, soutenance | À faire |
