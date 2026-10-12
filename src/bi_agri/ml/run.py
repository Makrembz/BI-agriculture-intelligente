"""Orchestration des 4 modeles et chargement des resultats dans l'entrepot."""
from datetime import datetime

import pandas as pd
from sqlalchemy import text

from ..config import SCHEMA
from ..db import copy_df, current_mode, engine, log, read_sql
from .anomalies import run_anomalies
from .clustering import run_clustering
from .data import declarations
from .demand import run_demand
from .forecast import run_forecast

PRED_COLS = ["sk_temps", "sk_comte", "sk_exploitant", "nom_modele", "version_modele", "type_prediction",
             "id_declaration", "motif_anomalie", "valeur_predite", "borne_basse", "borne_haute",
             "valeur_observee", "erreur_absolue", "score_anomalie", "indicateur_anomalie", "numero_segment"]


def run_ml(only: str | None = None):
    mode = current_mode()
    version = datetime.now().strftime("%Y%m%d")
    steps = only.split(",") if only else ["demande", "prevision", "segments", "anomalies"]
    evals, preds, seg = [], [], None
    decl = declarations() if ("segments" in steps or "anomalies" in steps) else None

    if "demande" in steps:
        e, p = run_demand(version)
        evals += e
        preds.append(p)
    if "prevision" in steps:
        e, p = run_forecast(version)
        evals += e
        preds.append(p)
    if "segments" in steps:
        e, p, seg = run_clustering(decl, version)
        evals += e
        preds.append(p)
    if "anomalies" in steps:
        e, p = run_anomalies(decl, version)
        evals += e
        preds.append(p)

    preds = [p for p in preds if p is not None and len(p)]
    allp = pd.concat(preds, ignore_index=True) if preds else pd.DataFrame(columns=PRED_COLS)
    for c in PRED_COLS:
        if c not in allp.columns:
            allp[c] = pd.NA
    allp["version_modele"] = version
    allp["sk_comte"] = allp["sk_comte"].fillna(-1).astype(int)
    allp["sk_exploitant"] = allp["sk_exploitant"].fillna(-1).astype(int)
    for c in ("numero_segment", "indicateur_anomalie"):
        allp[c] = allp[c].astype("Int64")
    if len(allp):
        valid = set(read_sql(f"SELECT sk_temps FROM {SCHEMA}.dim_temps")["sk_temps"])
        bad = ~allp["sk_temps"].isin(valid)
        if bad.any():
            print(f"   /!\\ {int(bad.sum())} predictions hors de DIM_TEMPS ignorees (etendre dim_temps_fin dans config/settings.yml)")
            allp = allp[~bad]
    types = allp["type_prediction"].unique().tolist() if len(allp) else []
    with engine().begin() as con:
        if types:
            con.execute(text(f"DELETE FROM {SCHEMA}.fait_prediction WHERE type_prediction = ANY(:t)"), {"t": types})
        if evals:
            ev_models = {e[1] for e in evals}
            con.execute(text(f"DELETE FROM {SCHEMA}.ref_modele_evaluation WHERE cible = ANY(:c)"), {"c": list(ev_models)})
        if seg is not None and len(seg):
            con.execute(text(f"DELETE FROM {SCHEMA}.ref_segment"))
    if len(allp):
        copy_df(allp, f"{SCHEMA}.fait_prediction", PRED_COLS)
    if evals:
        ev = pd.DataFrame([(a, version, b, c, d_, v, bool(r)) for a, b, c, d_, v, *rest in evals
                           for r in [rest[0] if rest else False]],
                          columns=["nom_modele", "version_modele", "cible", "perimetre", "metrique", "valeur", "retenu"])
        copy_df(ev, f"{SCHEMA}.ref_modele_evaluation",
                ["nom_modele", "version_modele", "cible", "perimetre", "metrique", "valeur", "retenu"])
    if seg is not None and len(seg):
        copy_df(seg, f"{SCHEMA}.ref_segment", ["numero_segment", "libelle_segment", "nb_exploitants", "volume_moyen_acft",
                                               "surface_moyenne_acres", "part_eau_souterraine", "nb_cultures_moyen"])
    log("ml", mode, f"{len(allp)} predictions chargees ({', '.join(types)}) ; {len(evals)} mesures d'evaluation")
