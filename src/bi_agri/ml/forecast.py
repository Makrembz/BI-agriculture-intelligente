"""Modele 2 : prevision de la demande a 12 mois par comte - series temporelles (SARIMA, Holt-Winters, Prophet si installe)."""
import warnings

import numpy as np
import pandas as pd

from ..config import SETTINGS
from .data import et_monthly

warnings.filterwarnings("ignore")
try:
    from prophet import Prophet                      # facultatif
except Exception:
    Prophet = None


def _mape(y, p):
    y, p = np.asarray(y, float), np.asarray(p, float)
    m = y > 0
    return float(np.mean(np.abs((y[m] - p[m]) / y[m])) * 100) if m.any() else np.nan


def _fit_forecast(name, train: pd.Series, h: int):
    """Retourne (prevision, borne_basse, borne_haute) sur h mois apres la serie train."""
    if name == "SARIMA":
        from statsmodels.tsa.statespace.sarimax import SARIMAX
        r = SARIMAX(train, order=(1, 1, 1), seasonal_order=(1, 1, 1, 12), enforce_stationarity=False,
                    enforce_invertibility=False).fit(disp=False, maxiter=100)
        fc = r.get_forecast(h)
        ci = fc.conf_int(alpha=0.05)
        return fc.predicted_mean.to_numpy(), ci.iloc[:, 0].to_numpy(), ci.iloc[:, 1].to_numpy()
    if name == "Holt-Winters":
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        r = ExponentialSmoothing(train, trend="add", seasonal="add", seasonal_periods=12,
                                 initialization_method="estimated").fit()
        f = r.forecast(h).to_numpy()
        s = float(np.std(r.resid)) * 1.96
        return f, f - s, f + s
    if name == "Prophet" and Prophet is not None:
        df = pd.DataFrame({"ds": train.index, "y": train.values})
        m = Prophet(yearly_seasonality=True, weekly_seasonality=False, daily_seasonality=False)
        m.fit(df)
        fut = m.make_future_dataframe(periods=h, freq="MS").tail(h)
        p = m.predict(fut)
        return p["yhat"].to_numpy(), p["yhat_lower"].to_numpy(), p["yhat_upper"].to_numpy()
    raise ValueError(name)


def run_forecast(version: str):
    from ..etl.load import date_to_sk
    cfg = SETTINGS["ml"]
    h, hold = cfg["horizon_mois"], cfg["jours_test_mois"]
    et = et_monthly()
    cands = ["SARIMA", "Holt-Winters"] + (["Prophet"] if Prophet is not None else [])
    mape = {c: [] for c in cands}
    wins = {c: 0 for c in cands}
    rows = []
    comtes = list(et.groupby("sk_comte"))
    for i, (k, g) in enumerate(comtes, 1):
        s = g.set_index("date")["et_moyenne_acft"].asfreq("MS").interpolate(limit_direction="both")
        if s.notna().sum() < hold + 36 or s.max() <= 0:
            continue
        train, test = s.iloc[:-hold], s.iloc[-hold:]
        scores = {}
        for c in cands:
            try:
                f, _, _ = _fit_forecast(c, train, hold)
                scores[c] = _mape(test.values, np.clip(f, 0, None))
                mape[c].append(scores[c])
            except Exception as e:
                scores[c] = np.nan
        valid = {c: v for c, v in scores.items() if not np.isnan(v)}
        if not valid:
            continue
        best = min(valid, key=valid.get)
        wins[best] += 1
        try:
            f, lo, hi = _fit_forecast(best, s, h)
        except Exception:
            continue
        idx = pd.date_range(s.index[-1] + pd.DateOffset(months=1), periods=h, freq="MS")
        rows.append(pd.DataFrame({"sk_temps": date_to_sk(pd.Series(idx)), "sk_comte": k,
                                  "valeur_predite": np.clip(f, 0, None), "borne_basse": np.clip(lo, 0, None),
                                  "borne_haute": np.clip(hi, 0, None), "nom_modele": best,
                                  "type_prediction": "prevision_12_mois"}))
        if i % 10 == 0:
            print(f"   prevision : {i}/{len(comtes)} comtes")
    evals = []
    best_global = min((c for c in cands if mape[c]), key=lambda c: np.nanmean(mape[c]), default=None)
    for c in cands:
        if mape[c]:
            evals.append((c, "prevision_12_mois", "tous comtés", "mape_moyen_pct", float(np.nanmean(mape[c])),
                          c == best_global))
            evals.append((c, "prevision_12_mois", "tous comtés", "mape_median_pct", float(np.nanmedian(mape[c])), False))
            evals.append((c, "prevision_12_mois", "tous comtés", "nb_comtes_ou_meilleur", float(wins[c]), False))
    print(f"Prevision : meilleur modele global = {best_global}")
    return evals, (pd.concat(rows, ignore_index=True) if rows else pd.DataFrame())
