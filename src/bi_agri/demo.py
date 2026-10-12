"""Jeu de donnees SYNTHETIQUE de demonstration (pour tester le pipeline sans reseau).

Ces donnees imitent la forme des sources reelles mais ne sont PAS reelles. Un fichier
marqueur data/raw/MODE_DEMO est cree ; le journal ETL indique alors mode_donnees = 'demo'.
`python run.py extract` supprime ce marqueur et retelecharge les vraies donnees.
"""
import numpy as np
import pandas as pd

from .config import DATA_RAW, SETTINGS, raw_path

COUNTIES = ["Alameda", "Alpine", "Amador", "Butte", "Calaveras", "Colusa", "Contra Costa", "Del Norte", "El Dorado",
            "Fresno", "Glenn", "Humboldt", "Imperial", "Inyo", "Kern", "Kings", "Lake", "Lassen", "Los Angeles",
            "Madera", "Marin", "Mariposa", "Mendocino", "Merced", "Modoc", "Mono", "Monterey", "Napa", "Nevada",
            "Orange", "Placer", "Plumas", "Riverside", "Sacramento", "San Benito", "San Bernardino", "San Diego",
            "San Francisco", "San Joaquin", "San Luis Obispo", "San Mateo", "Santa Barbara", "Santa Clara",
            "Santa Cruz", "Shasta", "Sierra", "Siskiyou", "Solano", "Sonoma", "Stanislaus", "Sutter", "Tehama",
            "Trinity", "Tulare", "Tuolumne", "Ventura", "Yolo", "Yuba"]
CROPS = ["Almonds", "Grapes", "Alfalfa", "Tomatoes", "Rice", "Corn", "Pasture", "Citrus", "Walnuts", "Pistachios",
         "Other", "Vegetables", "Wheat", "Cotton"]
SOURCES = ["Kings River", "Well No. 3", "Groundwater Well", "Sacramento River", "Deer Creek", "Main Canal",
           "Spring A", "Reservoir Lake", "Pump Station 12", "Salinas River"]
TYPES = ["Appropriative", "Statement of Diversion and Use", "Riparian", "Permit", "License", "Registration"]
MODELS = ["alexi_disalexi", "eemetric", "geesebal", "ptjpl", "sims", "ssebop"]


def make_demo(seed: int = 7):
    rng = np.random.default_rng(seed)
    # ---------------- ET par comte et par bassin (memes colonnes que les fichiers DWR reels)
    months = pd.date_range("2003-10-01", "2026-07-01", freq="MS")
    MOD = ["DISALEXI", "EEMETRIC", "ENSEMBLE", "GEESEBAL", "PTJPL", "SIMS", "SSEBOP"]
    def et_table(names, namecol, scale):
        rows = []
        for n in names:
            mask = float(rng.lognormal(scale, 1.0))
            for m in months:
                season = 0.15 + 0.85 * np.exp(-((m.month - 7) ** 2) / 8.0)
                depth = 5.0 * season * rng.lognormal(0, 0.1)               # pouces
                r = {"ID": len(rows), namecol: n, "area_acres": round(mask * 40, 2), "max_mask_area_acres": round(mask, 1),
                     "year_month": m.strftime("%Y-%m"), "year": m.year, "month": float(m.month), "timestep": "month"}
                inches = {k: depth * rng.lognormal(0, 0.12) for k in MOD}
                for k in MOD:
                    r[f"{k}_ET_mean_in"] = round(inches[k], 2)
                for k in MOD:
                    r[f"{k}_ET_acre_ft"] = round(inches[k] / 12 * mask, 2)
                rows.append(r)
        return pd.DataFrame(rows)
    et_table(COUNTIES, "NAME", 8.0).to_csv(raw_path("et_comte"), index=False)
    et_table([f"{(i % 9) + 1}-{i:03d}" for i in range(1, 61)], "Basin_Subb", 7.0).to_csv(raw_path("et_bassin"), index=False)

    # ---------------- declarations Water Rights (colonnes du fichier reel)
    n_rights = 3000
    owners = [f"FARM {chr(65 + i % 26)}{i % 977} LLC" if i % 7 else f"HOLDER {i // 3}" for i in range(n_rights)]
    rights = pd.DataFrame({"APPLICATION_NUMBER": [f"A{100000 + i}" for i in range(n_rights)], "PRIMARY_OWNER": owners,
        "COUNTY": rng.choice(COUNTIES, n_rights), "SOURCE_OF_WATER": rng.choice(SOURCES, n_rights),
        "WATER_RIGHT_TYPE": rng.choice(TYPES, n_rights), "FACE_VALUE": rng.lognormal(5.5, 1.2, n_rights).round(2),
        "FACE_VALUE_UNIT": rng.choice(["ac-ft", "ac-ft", "ac-ft", "gallons"], n_rights)})
    rights.loc[rights["FACE_VALUE_UNIT"] == "gallons", "FACE_VALUE"] *= 325851
    rows = []
    for y in range(2016, 2025):
        sub = rights.sample(frac=0.85, random_state=y)
        for _, r in sub.iterrows():
            irrigue = rng.random() > 0.35
            ncrop = int(rng.integers(1, 4)) if irrigue else 1
            for k in range(ncrop):
                rows.append({"REPORT_YEAR": y, "REVISION": 0, "REVISION_ATTRIBUTE": "Last_Revision" if rng.random() > 0.1 else "Previous_Revision",
                             "REPORT_SYSTEM_UNIQUE_ID": len(rows), **{k_: v for k_, v in r.to_dict().items()},
                             "IRRIGATION": "yes" if irrigue else "no",
                             "CROP_TYPE": (rng.choice(CROPS) if (y >= 2019 or rng.random() < 0.3) and rng.random() > 0.04 else None) if irrigue else None,
                             "AREA_IRRIGATED": round(float(rng.lognormal(3.6, 1.0)), 2) if irrigue else None,
                             "PRIMARY_IRRIG_METHOD": rng.choice(["Drip", "Flood", "Sprinkler", None]) if irrigue else None})
    wr = pd.DataFrame(rows)
    out = rng.choice(len(wr), 40, replace=False)
    wr.loc[out, "FACE_VALUE"] = wr.loc[out, "FACE_VALUE"] * 200
    wr.loc[rng.choice(len(wr), 200, replace=False), "COUNTY"] = None
    wr["TOTAL_ACRES_IRRIGATED"] = wr.groupby(["APPLICATION_NUMBER", "REPORT_YEAR"])["AREA_IRRIGATED"].transform("sum")
    wr.to_csv(raw_path("water_rights"), index=False)

    # ---------------- meteo journaliere
    p = SETTINGS["periode"]
    days = pd.date_range(p["meteo_debut"], p["meteo_fin"], freq="D")
    frames = []
    for v in SETTINGS["vallees"]:
        doy = days.dayofyear.to_numpy()
        t = 17 + 11 * np.sin(2 * np.pi * (doy - 110) / 365) + rng.normal(0, 2, len(days))
        rain = np.where((rng.random(len(days)) < 0.12) & ((doy < 110) | (doy > 290)), rng.gamma(1.5, 4, len(days)), 0)
        frames.append(pd.DataFrame({
            "vallee": v["nom"], "comte_ref": v["comte_ref"], "date": days,
            "temperature_min_c": t - 6, "temperature_max_c": t + 7, "temperature_moy_c": t,
            "precipitations_mm": rain, "et0_mm": np.clip(2.5 + 3.5 * np.sin(2 * np.pi * (doy - 80) / 365), 0.3, None),
            "humidite_relative_pct": np.clip(55 - 15 * np.sin(2 * np.pi * (doy - 110) / 365) + rng.normal(0, 6, len(days)), 10, 100),
            "vent_kmh": np.clip(rng.normal(10, 4, len(days)), 1, None),
            "rayonnement_mjm2": np.clip(17 + 9 * np.sin(2 * np.pi * (doy - 80) / 365) + rng.normal(0, 2, len(days)), 2, None),
            "humidite_sol_m3m3": np.clip(0.2 + 0.08 * np.cos(2 * np.pi * (doy - 30) / 365) + rng.normal(0, 0.01, len(days)), 0.05, 0.45),
            "temperature_sol_c": t - 1 + rng.normal(0, 0.5, len(days))}))
    pd.concat(frames).to_csv(DATA_RAW / "open_meteo_daily.csv", index=False)
    (DATA_RAW / "MODE_DEMO").write_text("Donnees synthetiques de demonstration - ne pas utiliser pour les resultats.")
    print("Donnees de DEMONSTRATION (synthetiques) ecrites dans data/raw/")
