"""Simulation de la couche de capteurs IoT (la seule donnee simulee du projet).

Principe : chaque capteur suit l'humidite et la temperature du sol REELLES de sa vallee
(Open-Meteo / ERA5-Land), avec un biais propre au capteur et du bruit. On y injecte des
pannes, des derives et de rares pics. Le script est un livrable : tout est reproductible
grace a la graine aleatoire (config/settings.yml).
"""
import numpy as np
import pandas as pd

from ..config import DATA_RAW, DATA_STAGING, MAPPING, SETTINGS, raw_path
from ..utils import clean_text, resolve_columns

DEFAULT_CROPS = ["Almonds", "Grapes", "Alfalfa", "Tomatoes", "Rice", "Corn", "Pasture",
                 "Citrus", "Walnuts", "Pistachios"]


def _top_crops() -> list[str]:
    path = raw_path("water_rights")
    if not path.exists():
        return DEFAULT_CROPS
    try:
        head = pd.read_csv(path, nrows=5, low_memory=False, encoding_errors="replace")
        col = resolve_columns(head, MAPPING["water_rights"], source="water_rights")["culture"]
        if not col:
            return DEFAULT_CROPS
        s = pd.read_csv(path, usecols=[col], low_memory=False, encoding_errors="replace")[col].map(clean_text).dropna()
        top = s.value_counts().head(12).index.tolist()
        return top or DEFAULT_CROPS
    except Exception:
        return DEFAULT_CROPS


def _ar1(rng, n_s, n_d, phi, sigma):
    e = rng.normal(0, sigma, (n_s, n_d))
    x = np.zeros((n_s, n_d))
    x[:, 0] = e[:, 0]
    for t in range(1, n_d):
        x[:, t] = phi * x[:, t - 1] + e[:, t]
    return x


def _episodes(rng, n_s, n_d, p_start, dmin, dmax):
    """Matrice booleenne d'episodes (pannes / derives) et matrice de progression 0..1."""
    flag = np.zeros((n_s, n_d), dtype=bool)
    prog = np.zeros((n_s, n_d))
    starts = rng.random((n_s, n_d)) < p_start
    for s, t in zip(*np.nonzero(starts)):
        d = int(rng.integers(dmin, dmax + 1))
        end = min(n_d, t + d)
        flag[s, t:end] = True
        prog[s, t:end] = np.linspace(0, 1, end - t)
    return flag, prog


def simulate_sensors():
    cfg = SETTINGS["capteurs"]
    rng = np.random.default_rng(cfg["graine"])
    n = int(cfg["nombre"])

    wpath = DATA_RAW / "open_meteo_daily.csv"
    if not wpath.exists():
        raise FileNotFoundError("Lancer d'abord l'extraction meteo : python run.py extract")
    w = pd.read_csv(wpath, parse_dates=["date"])
    dates = pd.date_range(w["date"].min(), w["date"].max(), freq="D")
    n_d = len(dates)

    valleys = SETTINGS["vallees"]
    vnames = [v["nom"] for v in valleys]
    moist = {}
    temp = {}
    for v in vnames:
        wv = w[w["vallee"] == v].set_index("date").reindex(dates)
        moist[v] = wv["humidite_sol_m3m3"].ffill().bfill().to_numpy()
        temp[v] = wv["temperature_sol_c"].ffill().bfill().to_numpy()

    # ---- parcelles et capteurs : parcelles REELLES du crop mapping (SIG) si disponibles, sinon simulees
    real = None
    try:
        from ..etl.crops import sample_parcels
        real = sample_parcels()
    except Exception as e:
        print(f"   (parcelles SIG indisponibles : {e})")
    rows_p, rows_c = [], []
    if real is not None and len(real):
        real = real.head(n)
        n = len(real)
        print(f"Parcelles : {n} parcelles reelles (crop mapping)")
        for i, r in real.iterrows():
            pid, cid = f"PAR-{i + 1:03d}", f"CAP-{i + 1:03d}"
            rows_p.append({"id_parcelle": pid, "surface_acres": round(float(r["acres"]), 2),
                           "culture_dominante": r["culture"] if isinstance(r["culture"], str) else None,
                           "latitude": r["latitude"], "longitude": r["longitude"], "origine": "SIG",
                           "vallee": r["vallee"], "comte_ref": r["comte"], "id_source": r["id_source"]})
    else:
        print("Parcelles : crop mapping absent, parcelles SIMULEES")
        crops = _top_crops()
        for i in range(n):
            v = valleys[i % len(valleys)]
            pid = f"PAR-{i + 1:03d}"
            rows_p.append({
                "id_parcelle": pid, "surface_acres": round(float(np.clip(rng.lognormal(4.0, 0.7), 8, 600)), 2),
                "culture_dominante": crops[int(rng.integers(0, len(crops)))],
                "latitude": round(v["lat"] + float(rng.uniform(-0.15, 0.15)), 5),
                "longitude": round(v["lon"] + float(rng.uniform(-0.15, 0.15)), 5),
                "origine": "simulee", "vallee": v["nom"], "comte_ref": v["comte_ref"], "id_source": None})
    for i, p_ in enumerate(rows_p):
        inst = pd.Timestamp("2019-06-01") + pd.Timedelta(days=int(rng.integers(0, 200)))
        rows_c.append({"id_capteur": f"CAP-{i + 1:03d}", "id_parcelle": p_["id_parcelle"],
                       "type_capteur": "Multi-parametre sol (simule)", "date_installation": inst.date().isoformat(),
                       "statut": "actif"})
    parcelles, capteurs = pd.DataFrame(rows_p), pd.DataFrame(rows_c)
    vidx = np.array([vnames.index(v) for v in parcelles["vallee"]])

    M = np.stack([moist[v] for v in vnames])[vidx]       # (n, n_d)
    T = np.stack([temp[v] for v in vnames])[vidx]

    # ---- valeurs normales
    a = rng.normal(1.0, 0.08, (n, 1))
    b = rng.normal(0.0, 0.02, (n, 1))
    humid = np.clip(M * a + b + _ar1(rng, n, n_d, 0.8, 0.008), 0.02, 0.55)
    tsol = T + rng.normal(0, 0.8, (n, 1)) + _ar1(rng, n, n_d, 0.6, 0.35)
    ph_mean = np.clip(rng.normal(7.1, 0.5, (n, 1)), 5.8, 8.2)
    ph = ph_mean + _ar1(rng, n, n_d, 0.9, 0.02)
    cond_base = np.clip(rng.lognormal(0.1, 0.5, (n, 1)), 0.3, 3.2)
    cond = cond_base * (0.25 / np.clip(humid, 0.05, None)) ** 0.3 * (1 + rng.normal(0, 0.03, (n, n_d)))

    # ---- defauts : derives, pics, pannes
    drift_flag, drift_prog = _episodes(rng, n, n_d, cfg["taux_derives"], 20, 60)
    sign = rng.choice([-1.0, 1.0], size=(n, n_d))
    drift = np.where(drift_flag, sign * 0.09 * drift_prog, 0.0)
    humid = np.clip(humid + drift, 0.0, 0.6)
    spike = rng.random((n, n_d)) < 0.0005
    humid = np.where(spike, np.clip(humid + 0.25, 0, 0.6), humid)
    out_flag, _ = _episodes(rng, n, n_d, cfg["taux_pannes"], 1, 14)

    outage_start = out_flag & ~np.concatenate([np.zeros((n, 1), bool), out_flag[:, :-1]], axis=1)
    alert = (~out_flag) & ((humid < 0.05) | (humid > 0.45) | (ph < 5.5) | (ph > 8.5) | (cond > 4.0)
                           | (np.abs(drift) > 0.04) | spike)
    alert = alert | outage_start
    actif = (~out_flag).astype(int)

    # ---- table de faits (format long)
    idx_s, idx_d = np.meshgrid(np.arange(n), np.arange(n_d), indexing="ij")
    readings = pd.DataFrame({
        "id_capteur": capteurs["id_capteur"].to_numpy()[idx_s.ravel()],
        "id_parcelle": parcelles["id_parcelle"].to_numpy()[idx_s.ravel()],
        "comte_ref": parcelles["comte_ref"].to_numpy()[idx_s.ravel()],
        "date": dates[idx_d.ravel()],
        "humidite_sol_m3m3": np.where(out_flag, np.nan, humid).ravel().round(4),
        "temperature_sol_c": np.where(out_flag, np.nan, tsol).ravel().round(2),
        "ph": np.where(out_flag, np.nan, ph).ravel().round(2),
        "conductivite_dsm": np.where(out_flag, np.nan, cond).ravel().round(3),
        "indicateur_alerte": alert.astype(int).ravel(),
        "indicateur_capteur_actif": actif.ravel(),
    })
    # verite terrain (pour evaluer les alertes)
    truth_type = np.full((n, n_d), "", dtype=object)
    truth_type[drift_flag & (np.abs(drift) > 0.04)] = "derive"
    truth_type[spike] = "pic"
    truth_type[out_flag] = "panne"
    truth = readings[["id_capteur", "date"]].copy()
    truth["anomalie_injectee"] = truth_type.ravel()
    truth = truth[truth["anomalie_injectee"] != ""]

    parcelles.to_csv(DATA_STAGING / "sim_parcelles.csv", index=False)
    capteurs.to_csv(DATA_STAGING / "sim_capteurs.csv", index=False)
    readings.to_csv(DATA_STAGING / "sim_releves.csv", index=False)
    truth.to_csv(DATA_STAGING / "sim_verite_terrain.csv", index=False)
    print(f"Simulation : {n} capteurs x {n_d} jours = {len(readings)} releves "
          f"({int((1 - actif).sum())} jours de panne, {int(alert.sum())} alertes)")
    return readings
