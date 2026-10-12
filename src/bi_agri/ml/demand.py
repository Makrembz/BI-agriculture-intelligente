"""Modele 1 : prediction de la demande en eau (ET agricole mensuelle) par comte - regression."""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from ..config import SETTINGS
from .data import et_monthly, meteo_monthly

try:
    from xgboost import XGBRegressor
except Exception:                      # xgboost facultatif
    XGBRegressor = None

SEED = SETTINGS["ml"]["graine"]


def _models():
    m = {"Régression linéaire (Ridge)": Ridge(alpha=1.0),
         "Random Forest": RandomForestRegressor(n_estimators=300, min_samples_leaf=2, n_jobs=-1, random_state=SEED)}
    if XGBRegressor is not None:
        m["XGBoost"] = XGBRegressor(n_estimators=400, max_depth=5, learning_rate=0.05, subsample=0.9,
                                    colsample_bytree=0.9, random_state=SEED, n_jobs=-1)
    return m


def _metrics(y, p):
    return {"rmse": float(np.sqrt(mean_squared_error(y, p))), "mae": float(mean_absolute_error(y, p)),
            "r2": float(r2_score(y, p))}


def _complete(et: pd.DataFrame) -> pd.DataFrame:
    """Serie mensuelle continue par comte (les mois manquants restent vides)."""
    parts = []
    for k, g in et.groupby("sk_comte"):
        idx = pd.date_range(g["date"].min(), g["date"].max(), freq="MS")
        g = g.set_index("date").reindex(idx)
        g["sk_comte"] = k
        g["nom_comte"] = g["nom_comte"].ffill().bfill()
        g["surface_agricole_acres"] = g["surface_agricole_acres"].ffill().bfill()
        g.index.name = "date"
        parts.append(g.reset_index())
    return pd.concat(parts, ignore_index=True)


def _features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["sk_comte", "date"]).copy()
    y = df["et_moyenne_acft"]
    g = df.groupby("sk_comte")["et_moyenne_acft"]
    df["lag1"] = g.shift(1)
    df["lag12"] = g.shift(12)
    df["lag3"] = pd.concat([g.shift(1), g.shift(2), g.shift(3)], axis=1).mean(axis=1, skipna=False)
    m = df["date"].dt.month
    df["m_sin"], df["m_cos"] = np.sin(2 * np.pi * m / 12), np.cos(2 * np.pi * m / 12)
    df["tendance"] = (df["date"].dt.year - 2003) + m / 12
    for c in ("lag1", "lag3", "lag12"):
        df[c] = np.log1p(df[c])
    df["surface"] = np.log1p(df["surface_agricole_acres"].fillna(0))
    return df


def _matrix(df: pd.DataFrame, comtes: list):
    X = df[["lag1", "lag3", "lag12", "m_sin", "m_cos", "tendance", "surface"]].copy()
    for k in comtes:
        X[f"c_{k}"] = (df["sk_comte"] == k).astype(float)
    return X


def run_demand(version: str):
    cfg = SETTINGS["ml"]
    et = _complete(et_monthly())
    f = _features(et)
    comtes = sorted(f["sk_comte"].unique())
    obs = f[f["et_moyenne_acft"].notna() & f[["lag1", "lag3", "lag12"]].notna().all(axis=1)].copy()
    cutoff = obs["date"].max() - pd.DateOffset(months=cfg["jours_test_mois"] - 1)
    train, test = obs[obs["date"] < cutoff], obs[obs["date"] >= cutoff]
    if len(train) < 200 or len(test) < 20:
        print("Demande : pas assez de donnees ET pour entrainer le modele")
        return [], pd.DataFrame()
    ytr = np.log1p(train["et_moyenne_acft"])
    Xtr, Xte = _matrix(train, comtes), _matrix(test, comtes)

    evals, results, preds_test = [], {}, {}
    base = np.expm1(test["lag12"])
    for k, v in _metrics(test["et_moyenne_acft"], base).items():
        evals.append(("Saisonnier naïf (lag 12)", "demande_mensuelle", "tous comtés", k, v))
    for name, mdl in _models().items():
        mdl.fit(Xtr, ytr)
        p = np.clip(np.expm1(mdl.predict(Xte)), 0, None)
        results[name] = _metrics(test["et_moyenne_acft"], p)
        preds_test[name] = p
        for k, v in results[name].items():
            evals.append((name, "demande_mensuelle", "tous comtés", k, v))
    best = min(results, key=lambda n: results[n]["rmse"])
    print(f"Demande : meilleur modele = {best} (RMSE {results[best]['rmse']:.1f} acre-pieds)")

    # predictions de validation (24 derniers mois) + mois suivant, avec le modele retenu
    from ..etl.load import date_to_sk
    bt = pd.DataFrame({"sk_temps": date_to_sk(test["date"]), "sk_comte": test["sk_comte"].to_numpy(),
                       "valeur_predite": preds_test[best], "valeur_observee": test["et_moyenne_acft"].to_numpy()})
    bt["erreur_absolue"] = (bt["valeur_predite"] - bt["valeur_observee"]).abs()

    final = dict(_models())[best]
    all_X = _matrix(obs, comtes)
    final.fit(all_X, np.log1p(obs["et_moyenne_acft"]))
    nxt = []
    for k, g in et.groupby("sk_comte"):
        g = g.sort_values("date")
        last = g["date"].max()
        new = pd.DataFrame({"date": [last + pd.DateOffset(months=1)], "sk_comte": k,
                            "nom_comte": g["nom_comte"].iloc[0],
                            "surface_agricole_acres": g["surface_agricole_acres"].iloc[0], "et_moyenne_acft": np.nan})
        ff = _features(pd.concat([g, new], ignore_index=True)).iloc[[-1]]
        if ff[["lag1", "lag3", "lag12"]].notna().all(axis=1).iloc[0]:
            nxt.append(ff)
    if nxt:
        nf = pd.concat(nxt)
        pn = np.clip(np.expm1(final.predict(_matrix(nf, comtes))), 0, None)
        nx = pd.DataFrame({"sk_temps": date_to_sk(nf["date"]), "sk_comte": nf["sk_comte"].to_numpy(),
                           "valeur_predite": pn, "valeur_observee": np.nan, "erreur_absolue": np.nan})
        bt = pd.concat([bt, nx], ignore_index=True)
    bt["nom_modele"] = best
    bt["type_prediction"] = "demande_mensuelle"

    # diagnostic climatique : meteo disponible seulement pour les comtes de reference des vallees
    try:
        evals += _climate_diagnostic(et)
    except Exception as e:                     # diagnostic facultatif
        print(f"   (diagnostic climat ignore : {e})")
    evals = [(m, c, p, k, v, m == best and c == "demande_mensuelle" and p == "tous comtés") for m, c, p, k, v in
             [e if len(e) == 5 else e[:5] for e in evals]]
    return evals, bt


def _climate_diagnostic(et):
    w = meteo_monthly()
    if w.empty:
        return []
    d = et.merge(w, on=["date", "sk_comte"], how="inner").dropna(subset=["et_moyenne_acft"])
    if len(d) < 60:
        return []
    m = d["date"].dt.month
    d["m_sin"], d["m_cos"] = np.sin(2 * np.pi * m / 12), np.cos(2 * np.pi * m / 12)
    cols = ["m_sin", "m_cos", "temp_moy", "precip", "et0", "rayonnement", "vent", "humidite"]
    comtes = sorted(d["sk_comte"].unique())
    X = d[cols].copy()
    for k in comtes:
        X[f"c_{k}"] = (d["sk_comte"] == k).astype(float)
    cut = d["date"].max() - pd.DateOffset(months=23)
    tr, te = d["date"] < cut, d["date"] >= cut
    if tr.sum() < 20 or te.sum() < 8:
        return []
    out = []
    y = d["et_moyenne_acft"]
    for k, v in _metrics(y[te], d.loc[te].groupby("sk_comte")["et_moyenne_acft"].transform("mean")).items():
        out.append(("Référence : moyenne du comte", "demande_mensuelle_climat", "4 vallées (météo)", k, v))
    for name, mdl in _models().items():
        mdl.fit(X[tr], np.log1p(y[tr]))
        p = np.clip(np.expm1(mdl.predict(X[te])), 0, None)
        for k, v in _metrics(y[te], p).items():
            out.append((f"{name} + météo", "demande_mensuelle_climat", "4 vallées (météo)", k, v))
    return out
