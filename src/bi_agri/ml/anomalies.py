"""Modele 4 : detection d'anomalies de declaration - Isolation Forest + regles statistiques."""
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from ..config import SETTINGS
from .data import et_monthly


def _z(s: pd.Series, by: pd.Series) -> pd.Series:
    g = s.groupby(by)
    mu, sd = g.transform("mean"), g.transform("std").fillna(0).clip(lower=0.15)
    return (s - mu) / sd


def run_anomalies(decl: pd.DataFrame, version: str):
    from ..etl.load import date_to_sk
    cfg = SETTINGS["ml"]
    d = decl.copy()
    vol = d["volume_autorise_acft"].fillna(d["volume_declare_acft"])
    surf = d["surface_irriguee_acres"]
    d["vpa"] = np.where(surf > 0, vol / surf.where(surf > 0), np.nan)
    d["log_vpa"] = np.log1p(d["vpa"])
    d["z_vpa"] = _z(d["log_vpa"], d["famille_culture"]).fillna(0)

    # volume attendu = surface x profondeur d'ET du comte (ET annuelle / surface agricole du comte)
    et = et_monthly()
    d["log_ratio_et"] = np.nan
    if not et.empty:
        et["annee"] = et["date"].dt.year
        ya = et.groupby(["sk_comte", "annee"]).agg(et=("et_moyenne_acft", "sum"),
                                                   sa=("surface_agricole_acres", "first")).reset_index()
        ya["profondeur"] = ya["et"] / ya["sa"].where(ya["sa"] > 0)
        d = d.merge(ya[["sk_comte", "annee", "profondeur"]], on=["sk_comte", "annee"], how="left")
        expected = d["surface_irriguee_acres"] * d["profondeur"]
        d["log_ratio_et"] = np.log1p(vol) - np.log1p(expected)
    d["z_et"] = _z(d["log_ratio_et"], d["annee"]).fillna(0)
    d["complet"] = d["nb_champs_renseignes"] / d["nb_champs_attendus"].replace(0, np.nan)

    feats = pd.DataFrame({"log_vpa": d["log_vpa"].fillna(d["log_vpa"].median()), "z_vpa": d["z_vpa"], "z_et": d["z_et"],
                          "log_vol": np.log1p(vol.fillna(0)), "log_surf": np.log1p(surf.fillna(0)),
                          "complet": d["complet"].fillna(0), "sans_culture": (d["sk_culture"] == -1).astype(int)})
    iso = IsolationForest(n_estimators=300, contamination=cfg["contamination_anomalies"], random_state=cfg["graine"],
                          n_jobs=-1).fit(feats)
    flag_iso = iso.predict(feats) == -1
    score = -iso.decision_function(feats)

    rules = {
        "volume incohérent avec la surface": d["z_vpa"].abs() > 3,
        "culture absente": d["sk_culture"] == -1,
        "écart fort volume autorisé / ET mesurée": d["z_et"].abs() > 3,
        "volume sans surface": (surf.fillna(0) <= 0) & (vol.fillna(0) > 0),
        "modèle Isolation Forest": pd.Series(flag_iso, index=d.index),
    }
    motifs = pd.Series("", index=d.index)
    for name, mask in rules.items():
        motifs = np.where(mask, np.where(motifs == "", name, motifs + " ; " + name), motifs)
        motifs = pd.Series(motifs, index=d.index)
    flagged = motifs != ""
    print(f"Anomalies : {int(flagged.sum())} declarations signalees sur {len(d)} "
          f"({100 * flagged.mean():.1f} %)")

    year_series = pd.to_datetime(d["annee"].astype(int).astype(str) + "-01-01")
    preds = pd.DataFrame({"sk_temps": date_to_sk(year_series[flagged]), "sk_comte": d.loc[flagged, "sk_comte"].to_numpy(),
                          "sk_exploitant": d.loc[flagged, "sk_exploitant"].to_numpy(),
                          "nom_modele": "Isolation Forest + règles", "type_prediction": "anomalie_declaration",
                          "id_declaration": d.loc[flagged, "id_declaration"].to_numpy(),
                          "motif_anomalie": motifs[flagged].to_numpy(),
                          "score_anomalie": score[flagged.to_numpy()], "indicateur_anomalie": 1})
    evals = [("Isolation Forest + règles", "anomalie_declaration", "déclarations", "part_signalee_pct",
              float(100 * flagged.mean()), True)]
    for name, mask in rules.items():
        evals.append(("Isolation Forest + règles", "anomalie_declaration", "déclarations", f"nb · {name}",
                      float(mask.sum()), False))
    return evals, preds
