"""Meteo journaliere Open-Meteo (reanalyses ERA5 / ERA5-Land) pour les 4 vallees."""
import time

import pandas as pd
import requests

from ..config import DATA_RAW, SETTINGS

HOURLY = ["temperature_2m", "relative_humidity_2m", "precipitation", "et0_fao_evapotranspiration",
          "wind_speed_10m", "shortwave_radiation", "soil_temperature_0_to_7cm", "soil_moisture_0_to_7cm"]


def _fetch_year(lat, lon, start, end):
    cfg = SETTINGS["open_meteo"]
    params = {"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
              "hourly": ",".join(HOURLY), "timezone": cfg["timezone"], "wind_speed_unit": "kmh"}
    for attempt in range(5):
        r = requests.get(cfg["url"], params=params, timeout=120)
        if r.status_code == 429:
            time.sleep(20 * (attempt + 1))
            continue
        r.raise_for_status()
        h = r.json()["hourly"]
        return pd.DataFrame(h)
    raise RuntimeError("Open-Meteo : trop de requetes (429), reessayer plus tard")


def hourly_to_daily(h: pd.DataFrame) -> pd.DataFrame:
    h = h.copy()
    h["time"] = pd.to_datetime(h["time"])
    h["date"] = h["time"].dt.normalize()
    g = h.groupby("date")
    d = pd.DataFrame({
        "temperature_min_c": g["temperature_2m"].min(),
        "temperature_max_c": g["temperature_2m"].max(),
        "temperature_moy_c": g["temperature_2m"].mean(),
        "precipitations_mm": g["precipitation"].sum(min_count=1),
        "et0_mm": g["et0_fao_evapotranspiration"].sum(min_count=1),
        "humidite_relative_pct": g["relative_humidity_2m"].mean(),
        "vent_kmh": g["wind_speed_10m"].mean(),
        "rayonnement_mjm2": g["shortwave_radiation"].sum(min_count=1) * 0.0036,   # W/m2 horaire -> MJ/m2
        "humidite_sol_m3m3": g["soil_moisture_0_to_7cm"].mean(),
        "temperature_sol_c": g["soil_temperature_0_to_7cm"].mean(),
    })
    return d.reset_index()


def extract_weather(force: bool = False):
    dest = DATA_RAW / "open_meteo_daily.csv"
    if dest.exists() and not force:
        print(f"{dest.name} existe deja (utiliser --force pour refaire)")
        return dest
    start = pd.Timestamp(SETTINGS["periode"]["meteo_debut"])
    end = pd.Timestamp(SETTINGS["periode"]["meteo_fin"])
    frames = []
    for v in SETTINGS["vallees"]:
        print(f"Meteo {v['nom']} ({v['lat']}, {v['lon']})")
        parts = []
        for y in range(start.year, end.year + 1):
            s = max(start, pd.Timestamp(y, 1, 1)).strftime("%Y-%m-%d")
            e = min(end, pd.Timestamp(y, 12, 31)).strftime("%Y-%m-%d")
            parts.append(_fetch_year(v["lat"], v["lon"], s, e))
            time.sleep(1.5)
        daily = hourly_to_daily(pd.concat(parts, ignore_index=True))
        daily.insert(0, "vallee", v["nom"])
        daily.insert(1, "comte_ref", v["comte_ref"])
        frames.append(daily)
    out = pd.concat(frames, ignore_index=True)
    out.to_csv(dest, index=False)
    print(f"{len(out)} lignes journalieres ecrites dans {dest.name}")
    return dest
