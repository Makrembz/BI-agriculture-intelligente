"""Modele 3 : segmentation des exploitants - K-Means (coude + score de silhouette)."""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from ..config import SETTINGS


def _features(decl: pd.DataFrame) -> pd.DataFrame:
    d = decl[decl["sk_exploitant"] != -1].copy()
    per_year = d.groupby(["sk_exploitant", "annee"]).agg(vol=("volume_autorise_acft", "sum"),
                                                         surf=("surface_irriguee_acres", "sum")).reset_index()
    base = per_year.groupby("sk_exploitant").agg(volume_moyen_acft=("vol", "mean"), surface_moyenne_acres=("surf", "mean"))
    d["vol_sout"] = np.where(d["categorie_source"] == "Souterraine", d["volume_autorise_acft"].fillna(0), 0.0)
    g = d.groupby("sk_exploitant")
    base["nb_cultures"] = g["sk_culture"].apply(lambda s: s[s != -1].nunique())
    base["nb_comtes"] = g["sk_comte"].nunique()
    tot = g["volume_autorise_acft"].sum().replace(0, np.nan)
    base["part_eau_souterraine"] = (g["vol_sout"].sum() / tot).fillna(0)
    return base.fillna(0).reset_index()


def _elbow(ks, inertias):
    x, y = np.array(ks, float), np.array(inertias, float)
    x, y = (x - x.min()) / (x.max() - x.min()), (y - y.min()) / (y.max() - y.min() + 1e-12)
    x1, y1, x2, y2 = x[0], y[0], x[-1], y[-1]
    norm = np.hypot(x2 - x1, y2 - y1) or 1.0
    dist = [abs((x2 - x1) * (b - y1) - (y2 - y1) * (a - x1)) / norm for a, b in zip(x, y)]   # distance a la corde
    return ks[int(np.argmax(dist))]


def _label(rank, k, row):
    niveau = "petits volumes" if rank == 1 else ("très gros volumes" if rank == k else "volumes moyens")
    extra = []
    if row["part_eau_souterraine"] > 0.6:
        extra.append("eau souterraine")
    if row["nb_comtes"] > 1.5:
        extra.append("multi-comtés")
    return f"S{rank} · {niveau}" + (" · " + ", ".join(extra) if extra else "")


def run_clustering(decl: pd.DataFrame, version: str):
    from ..etl.load import date_to_sk
    cfg = SETTINGS["ml"]
    f = _features(decl)
    if len(f) < 30:
        print("Segmentation : trop peu d'exploitants")
        return [], pd.DataFrame(), pd.DataFrame()
    X = np.column_stack([np.log1p(f["volume_moyen_acft"]), np.log1p(f["surface_moyenne_acres"]),
                         f["nb_cultures"], f["part_eau_souterraine"], f["nb_comtes"]])
    Xs = StandardScaler().fit_transform(X)
    ks = list(range(cfg["k_min"], min(cfg["k_max"], len(f) - 1) + 1))
    inert, sil = [], []
    for k in ks:
        km = KMeans(n_clusters=k, n_init=10, random_state=cfg["graine"]).fit(Xs)
        inert.append(float(km.inertia_))
        sil.append(float(silhouette_score(Xs, km.labels_)))
    k_best = _elbow(ks, inert)
    km = KMeans(n_clusters=k_best, n_init=10, random_state=cfg["graine"]).fit(Xs)
    f["cluster"] = km.labels_
    order = f.groupby("cluster")["volume_moyen_acft"].mean().sort_values().index.tolist()
    rank = {c: i + 1 for i, c in enumerate(order)}
    f["numero_segment"] = f["cluster"].map(rank)
    print(f"Segmentation : k={k_best} (coude), silhouette={sil[ks.index(k_best)]:.3f}")

    prof = f.groupby("numero_segment").agg(nb_exploitants=("sk_exploitant", "count"),
                                           volume_moyen_acft=("volume_moyen_acft", "mean"),
                                           surface_moyenne_acres=("surface_moyenne_acres", "mean"),
                                           part_eau_souterraine=("part_eau_souterraine", "mean"),
                                           nb_cultures_moyen=("nb_cultures", "mean"),
                                           nb_comtes=("nb_comtes", "mean")).reset_index()
    prof["libelle_segment"] = [_label(int(r["numero_segment"]), k_best, r) for r in prof.to_dict("records")]
    prof = prof.drop(columns=["nb_comtes"]).round(4)
    year = int(decl["annee"].max())
    preds = pd.DataFrame({"sk_temps": date_to_sk(pd.Series([pd.Timestamp(year, 12, 31)] * len(f))),
                          "sk_exploitant": f["sk_exploitant"].to_numpy(), "nom_modele": "K-Means",
                          "type_prediction": "segment_exploitant",
                          "numero_segment": f["numero_segment"].astype("Int64").to_numpy()})
    evals = [("K-Means", "segment_exploitant", "exploitants", "k_choisi_coude", float(k_best), True)]
    for k, s, i in zip(ks, sil, inert):
        evals.append(("K-Means", "segment_exploitant", f"k={k}", "silhouette", s, False))
        evals.append(("K-Means", "segment_exploitant", f"k={k}", "inertie", i, False))
    return evals, preds, prof
