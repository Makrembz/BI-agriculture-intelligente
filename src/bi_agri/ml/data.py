"""Lecture des donnees de l'entrepot pour les modeles."""
import pandas as pd

from ..config import SCHEMA
from ..db import read_sql


def et_monthly() -> pd.DataFrame:
    df = read_sql(f"""
        SELECT t.date, c.sk_comte, c.nom_comte, c.surface_agricole_acres, f.et_moyenne_acft
        FROM {SCHEMA}.fait_et_mensuelle_comte f
        JOIN {SCHEMA}.dim_temps t USING (sk_temps)
        JOIN {SCHEMA}.dim_comte c USING (sk_comte)
        ORDER BY c.sk_comte, t.date""")
    df["date"] = pd.to_datetime(df["date"])
    df["et_moyenne_acft"] = pd.to_numeric(df["et_moyenne_acft"])
    df["surface_agricole_acres"] = pd.to_numeric(df["surface_agricole_acres"])
    return df


def meteo_monthly() -> pd.DataFrame:
    df = read_sql(f"""
        SELECT date_trunc('month', t.date)::date AS date, f.sk_comte,
               avg(f.temperature_moy_c) AS temp_moy, sum(f.precipitations_mm) AS precip,
               sum(f.et0_mm) AS et0, sum(f.rayonnement_mjm2) AS rayonnement,
               avg(f.vent_kmh) AS vent, avg(f.humidite_relative_pct) AS humidite
        FROM {SCHEMA}.fait_meteo_jour f JOIN {SCHEMA}.dim_temps t USING (sk_temps)
        GROUP BY 1, 2 ORDER BY 2, 1""")
    df["date"] = pd.to_datetime(df["date"])
    for c in df.columns[2:]:
        df[c] = pd.to_numeric(df[c])
    return df


def declarations() -> pd.DataFrame:
    df = read_sql(f"""
        SELECT f.id_declaration, t.annee, f.sk_comte, c.nom_comte, c.surface_agricole_acres,
               f.sk_exploitant, f.sk_culture, cu.famille_culture, f.sk_source_eau, s.categorie_source,
               f.volume_autorise_acft, f.volume_declare_acft, f.surface_irriguee_acres,
               f.nb_champs_renseignes, f.nb_champs_attendus
        FROM {SCHEMA}.fait_declaration_irrigation f
        JOIN {SCHEMA}.dim_temps t USING (sk_temps)
        JOIN {SCHEMA}.dim_comte c USING (sk_comte)
        JOIN {SCHEMA}.dim_culture cu USING (sk_culture)
        JOIN {SCHEMA}.dim_source_eau s USING (sk_source_eau)""")
    for c in ("surface_agricole_acres", "volume_autorise_acft", "volume_declare_acft", "surface_irriguee_acres"):
        df[c] = pd.to_numeric(df[c])
    return df
