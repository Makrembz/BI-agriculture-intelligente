# Spécification des 4 dashboards Power BI

Le modèle sémantique est déjà construit dans Power BI Desktop (tables, relations, hiérarchies, mesures). Il reste à créer les pages du rapport avec les champs ci-dessous. Toutes les mesures sont dans la table `_Mesures` (dossiers 1 à 4).

**Règles générales**
- Thème : vert `#1F6F4A` (principal), `#13402C` (titres), orange `#B8741A` (accent). Police Segoe UI.
- Barre de filtres en haut de chaque page : segments `Temps[Année]`, `Comté[Vallée]`, `Comté[Comté]`.
- Cartes (KPI) en haut, graphiques en dessous. Titres des visuels en français. Infobulles activées.
- Ne jamais mettre les colonnes `sk_*` (masquées) dans les visuels ; utiliser les mesures de `_Mesures`.
- La surface irriguée est semi-additive : elle prend la dernière année du filtre. Le volume est additif.

## Page 1 — Directeur général (vue d'ensemble du district)
- Cartes : `Volume total distribué (ac-ft)`, `Surface irriguée (acres)`, `Volume par acre desservi (ac-ft/acre)`, `Évolution annuelle du volume`, `Couverture du district`, `Nombre de comtés desservis`.
- Histogramme + courbe : axe `Temps[Année]`, valeurs `Volume total distribué (ac-ft)`, ligne `Évolution annuelle du volume`.
- Carte à bulles : lieu `Comté[Comté]` (pays États-Unis, état Californie), taille `Volume total distribué (ac-ft)`, infobulle `Volume par acre desservi`.
- Barres : axe `Comté[Vallée]`, valeur `Volume total distribué (ac-ft)` (comparaison entre vallées).
- Matrice : lignes hiérarchie `Comté[Territoire]`, colonnes `Temps[Année]`, valeurs `Volume total distribué (ac-ft)`.

## Page 2 — Responsable ressources en eau
- Cartes : `ET mesurée - années déclarées (ac-ft)`, `Écart consommation réelle / autorisé`, `Déficit hydrique climatique (mm)`, `Part de la demande couverte par la pluie`, `Efficience par culture (ac-ft/acre)`.
- Courbe + histogramme : axe `Temps[Année-mois]`, `ET mesurée (ac-ft)` (courbe) et `Précipitations (mm)` (histogramme).
- Prévision à 12 mois : courbe, axe `Temps[Année-mois]`, valeurs `Prévision de demande à 12 mois (ac-ft)`, `Prévision - borne basse (ac-ft)`, `Prévision - borne haute (ac-ft)`, plus `ET mesurée (ac-ft)` pour l'historique. Segment `Comté[Comté]` pour choisir le comté.
- Validation du modèle : courbes `Demande prédite - validation (ac-ft)` et `Demande observée - validation (ac-ft)` par `Temps[Année-mois]` ; carte `Erreur absolue moyenne - validation (ac-ft)`.
- Barres : `Déficit hydrique climatique (mm)` par `Comté[Vallée]` (la météo existe pour un comté de référence par vallée).
- Tableau : `Bassin[Bassin]` avec `ET bassin (ac-ft)`, trié décroissant, top 15.

## Page 3 — Conformité et qualité des données
- Cartes : `Taux de complétude des déclarations`, `Part des déclarations sans culture`, `Déclarations incohérentes détectées`, `Incertitude de la mesure satellite`, `Capteurs actifs`, `Disponibilité du parc de capteurs`.
- Histogramme : `Taux de complétude des déclarations` par `Temps[Année]`.
- Barres : `Taux de complétude des déclarations` par `Comté[Comté]`, trié croissant, top 15 des moins complets.
- Tableau des anomalies : `Prédictions[N° déclaration (anomalie)]`, `Exploitant[Exploitant]`, `Comté[Comté]`, `Prédictions[Motif d'anomalie]`, `Score d'anomalie moyen` ; filtre du visuel `Prédictions[Type de prédiction]` = `anomalie_declaration`.
- Barres : `Déclarations incohérentes détectées` par `Prédictions[Motif d'anomalie]`.
- Barres : `Incertitude de la mesure satellite` par `Comté[Comté]`.
- Suivi des capteurs : courbe `Alertes capteurs` par `Temps[Année-mois]` ; carte avec `Parcelle[Latitude]`, `Parcelle[Longitude]`, taille `Alertes capteurs`, légende `Parcelle[Culture dominante]`.

## Page 4 — Adhérents et tarification
- Cartes : `Exploitants actifs`, `Volume moyen par exploitant (ac-ft)`, `Part du volume des 10 % plus gros exploitants`, `Recette simulée (USD)`.
- Segment curseur : `Tarif[Tarif (USD par ac-ft)]` (valeur par défaut 100) pour la simulation tarifaire.
- Anneau : `Part du volume par source d'eau` par `Source eau[Catégorie de source]`.
- Barres : `Volume total distribué (ac-ft)` par `Culture[Famille de culture]`.
- Tableau des segments : `Segments[Libellé du segment]`, `Segments[Nb exploitants]`, `Segments[Volume moyen (ac-ft)]`, `Segments[Surface moyenne (acres)]`, `Segments[Part eau souterraine]`.
- Nuage de points : axe X `Segments[Surface moyenne (acres)]`, axe Y `Segments[Volume moyen (ac-ft)]`, taille `Segments[Nb exploitants]`.
- Barres : top 10 `Exploitant[Exploitant]` par `Volume total distribué (ac-ft)`.

## Page 5 (facultative) — Qualité des modèles
- Tableau : `Évaluation modèles[Modèle]`, `[Cible]`, `[Périmètre]`, `[Métrique]`, `[Valeur]`, `[Modèle retenu]`.

## Navigation
Boutons de navigation entre les pages en haut à droite ; page d'accueil = page 1.
