"""ETL : lecture des fichiers bruts, transformation, chargement de l'entrepot PostgreSQL.

Ordre : dimensions (upsert, cles de substitution) puis faits (rechargement complet, rejouable).
"""
import re

import numpy as np
import pandas as pd
from sqlalchemy import text

from ..config import DATA_RAW, DATA_STAGING, MAPPING, SCHEMA, SETTINGS, raw_path
from ..db import copy_df, current_mode, engine, execute, log, log_reject, read_sql
from ..utils import ColumnMappingError, clean_text, norm, resolve_columns, slug, title_county
from . import quality

MODE = None
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"]
JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
FACTS = ["fait_declaration_irrigation", "fait_et_mensuelle_comte", "fait_et_mensuelle_bassin",
         "fait_meteo_jour", "fait_releve_capteur", "fait_prediction"]


# --------------------------------------------------------------------- outils
def to_records(df: pd.DataFrame) -> list[dict]:
    out = []
    for r in df.astype(object).where(df.notna(), None).to_dict("records"):
        out.append({k: (v.item() if hasattr(v, "item") else v) for k, v in r.items()})
    return out


def upsert(table: str, df: pd.DataFrame, conflict: str):
    if df.empty:
        return
    cols = list(df.columns)
    sets = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != conflict)
    sql = (f"INSERT INTO {SCHEMA}.{table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)}) "
           f"ON CONFLICT ({conflict}) DO UPDATE SET {sets}")
    with engine().begin() as con:
        con.execute(text(sql), to_records(df))


def sk_map(table: str, nk: str, sk: str) -> dict:
    d = read_sql(f"SELECT {nk}, {sk} FROM {SCHEMA}.{table} WHERE {sk} <> -1")
    return dict(zip(d[nk], d[sk]))


def apply_sk(series: pd.Series, mapping: dict) -> pd.Series:
    return series.map(mapping).fillna(-1).astype(int)


def famille_culture(nom):
    if nom is None:
        return "Non renseignée"
    low = nom.lower()
    for fam, words in SETTINGS["familles_culture"].items():
        if any(w in low for w in words):
            return fam
    return "Autre"


def categorie_source(nom):
    if nom is None:
        return "Inconnue"
    low = nom.lower()
    for cat, words in SETTINGS["categories_source"].items():
        if any(w in low for w in words):
            return cat
    return "Autre"


def date_to_sk(s: pd.Series) -> pd.Series:
    return (s.dt.year * 10000 + s.dt.month * 100 + s.dt.day).astype(int)


# ----------------------------------------------------------- DIM_TEMPS
def load_dim_temps():
    p = SETTINGS["periode"]
    d = pd.date_range(p["dim_temps_debut"], p["dim_temps_fin"], freq="D")
    df = pd.DataFrame({"date": d})
    df["sk_temps"] = date_to_sk(df["date"])
    df["annee"] = df["date"].dt.year
    df["mois"] = df["date"].dt.month
    df["annee_hydrologique"] = np.where(df["mois"] >= 10, df["annee"] + 1, df["annee"])
    df["trimestre"] = df["date"].dt.quarter
    df["nom_mois"] = df["mois"].map(lambda m: MOIS_FR[m - 1])
    df["annee_mois"] = df["date"].dt.strftime("%Y-%m")
    df["jour"] = df["date"].dt.day
    df["jour_semaine"] = df["date"].dt.dayofweek + 1
    df["nom_jour_semaine"] = df["jour_semaine"].map(lambda j: JOURS_FR[j - 1])
    df["est_premier_jour_mois"] = df["jour"] == 1
    df["date"] = df["date"].dt.date
    upsert("dim_temps", df[["sk_temps", "date", "annee", "annee_hydrologique", "trimestre", "mois", "nom_mois",
                            "annee_mois", "jour", "jour_semaine", "nom_jour_semaine", "est_premier_jour_mois"]],
           "sk_temps")
    log("dim_temps", MODE, f"{len(df)} jours")


# --------------------------------------------------- lecture des sources
def parse_month_start(df: pd.DataFrame, cols: dict) -> pd.Series:
    if cols.get("annee") and cols.get("mois"):
        y = pd.to_numeric(df[cols["annee"]], errors="coerce")
        m = pd.to_numeric(df[cols["mois"]], errors="coerce")
        if m.isna().all():
            m = pd.to_datetime(df[cols["mois"]].astype(str).str[:3], format="%b", errors="coerce").dt.month
        d = pd.to_datetime({"year": y, "month": m, "day": 1}, errors="coerce")
    elif cols.get("date"):
        d = pd.to_datetime(df[cols["date"]], errors="coerce")
    else:
        raise ColumnMappingError("ET : ni (annee + mois) ni date trouves, voir config/column_mapping.yml")
    return d.dt.to_period("M").dt.to_timestamp()


def detect_et_columns(df: pd.DataFrame):
    low = {c: c.lower() for c in df.columns}
    acft = [c for c, l in low.items() if re.search(r"ac[ _-]?ft|acre[ _-]?f", l)]
    inch = [c for c, l in low.items() if c not in acft and re.search(r"(^|[ _-])(in|inch|inches)($|[ _-])", l)]
    acft = [c for c in acft if pd.to_numeric(df[c], errors="coerce").notna().any()]
    inch = [c for c in inch if pd.to_numeric(df[c], errors="coerce").notna().any()]
    return acft, inch


def prepare_et(name: str, key_logical: str) -> pd.DataFrame:
    """Retourne un DataFrame (mois, cle, mesures ET agregees) au grain cle x mois."""
    path = raw_path(name)
    df = pd.read_csv(path, low_memory=False, encoding_errors="replace")
    cols = resolve_columns(df, MAPPING[name], required=[key_logical], source=name)
    df["_mois"] = parse_month_start(df, cols)
    n_all = len(df)
    ts = next((c for c in df.columns if norm(c) == "timestep"), None)
    if ts:                                   # ne garder que les lignes mensuelles
        df = df[df[ts].astype(str).str.lower().str.startswith("month")]
    df = df[df["_mois"].notna()].copy()
    log_reject(name, "ligne annuelle ou sans mois (ignoree)", n_all - len(df))
    acft, inch = detect_et_columns(df)
    if not acft:
        raise ColumnMappingError(f"[{name}] aucune colonne d'ET en acre-pieds trouvee. Colonnes : {list(df.columns)}")

    model_col = next((c for c in df.columns if norm(c) in ("model", "openetmodel", "etmodel", "modelname")), None)
    key = cols[key_logical]
    if model_col and len(acft) == 1:                       # format long -> large
        piv = df.pivot_table(index=[key, "_mois"], columns=model_col, values=acft[0], aggfunc="mean")
        piv.columns = [f"m_{slug(c)}_acft" for c in piv.columns]
        wide = piv.reset_index()
        acft = [c for c in wide.columns if c.endswith("_acft")]
        inch_part = None
        if len(inch) == 1:
            pi = df.pivot_table(index=[key, "_mois"], columns=model_col, values=inch[0], aggfunc="mean")
            pi.columns = [f"m_{slug(c)}_in" for c in pi.columns]
            wide = wide.merge(pi.reset_index(), on=[key, "_mois"], how="left")
            inch = [c for c in wide.columns if c.endswith("_in")]
        df = wide
    for c in acft + inch:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    ens = next((c for c in acft if "ensemble" in c.lower()), None)
    models = [c for c in acft if c != ens] or acft
    out = pd.DataFrame({"cle": df[key].map(clean_text), "mois": df["_mois"]})
    out["et_moyenne_acft"] = df[ens] if ens else df[models].mean(axis=1)
    out["et_min_modeles_acft"] = df[models].min(axis=1)
    out["et_max_modeles_acft"] = df[models].max(axis=1)
    out["et_ecart_type_modeles_acft"] = df[models].std(axis=1) if len(models) > 1 else np.nan
    out["nb_modeles_renseignes"] = df[models].notna().sum(axis=1)
    ens_in = next((c for c in inch if "ensemble" in c.lower()), None)
    out["et_moyenne_pouces"] = df[ens_in] if ens_in else (df[inch].mean(axis=1) if inch else np.nan)
    if cols.get("surface") and cols["surface"] in df.columns:
        out["_surface"] = pd.to_numeric(df[cols["surface"]], errors="coerce")
    out = out[out["cle"].notna()]
    n0 = len(out)
    num = [c for c in out.columns if c not in ("cle", "mois")]
    out = out.groupby(["cle", "mois"], as_index=False)[num].mean()   # supprime d'eventuels doublons
    log_reject(name, "doublons (cle, mois) fusionnes", n0 - len(out))
    out["nb_modeles_renseignes"] = out["nb_modeles_renseignes"].round().astype(int)
    return out


def to_acft(value: pd.Series, unit: pd.Series | None) -> pd.Series:
    """Convertit un volume vers des acre-pieds selon l'unite (ac-ft, gallons, pieds cubes). Unite inconnue -> vide."""
    if unit is None:
        return value
    u = unit.fillna("").astype(str).str.lower().str.strip()
    f = pd.Series(np.nan, index=value.index)
    f[u.str.contains(r"ac[\s._-]*ft|acre[\s._-]*f|^af$")] = 1.0
    gal = u.str.contains("gal") & ~u.str.contains(r"min|day|per|/")
    f[gal] = 1 / 325851.0
    f[gal & u.str.contains("million|mgal")] = 1e6 / 325851.0
    f[u.str.contains(r"cubic f|^cf$|^ft3$") & ~u.str.contains(r"sec|/|per")] = 1 / 43560.0
    f[(u == "") & value.notna()] = 1.0            # unite absente : on suppose des acre-pieds
    top = u[value.notna()].value_counts().head(6).to_dict()
    print(f"   unites du volume autorise : {top}")
    return value * f


def prepare_water_rights():
    """Declarations 2019-2024 avec irrigation effective, pretes pour les dimensions et le fait."""
    df = pd.read_csv(raw_path("water_rights"), low_memory=False, encoding_errors="replace")
    cols = resolve_columns(df, MAPPING["water_rights"],
                           required=["annee", "comte", "surface", "volume_autorise"], source="water_rights")
    g = lambda k: df[cols[k]] if cols.get(k) else pd.Series([None] * len(df), index=df.index)
    p = SETTINGS["periode"]
    n_raw = len(df)
    fait = "fait_declaration_irrigation"

    if cols.get("revision_attr"):                # le fichier contient les versions successives des rapports
        last = df[cols["revision_attr"]].astype(str).str.lower().str.contains("last")
        log_reject(fait, "ancienne version d'un rapport (revision non finale)", (~last).sum())
        df, g = df[last].copy(), (lambda k: df[cols[k]] if cols.get(k) else pd.Series([None] * len(df), index=df.index))
        df = df.reset_index(drop=True)

    d = pd.DataFrame(index=df.index)
    d["annee"] = pd.to_numeric(g("annee"), errors="coerce")
    d["surface"] = pd.to_numeric(g("surface"), errors="coerce")
    d["vol_aut"] = to_acft(pd.to_numeric(g("volume_autorise"), errors="coerce"),
                           df[cols["unite_volume"]] if cols.get("unite_volume") else None)
    d["vol_dec"] = pd.to_numeric(g("volume_declare"), errors="coerce")
    for c in ("surface", "vol_aut", "vol_dec"):
        d.loc[d[c] < 0, c] = np.nan
    d["comte"] = g("comte").map(title_county)
    d["culture"] = g("culture").map(clean_text)
    d["exploitant"] = g("exploitant").map(clean_text)
    d["source"] = g("source").map(clean_text)
    d["type_droit"] = g("type_droit").map(clean_text)
    d["droit_id"] = g("droit_id").map(clean_text)
    if cols.get("irrigation_flag"):
        d["irrigue"] = df[cols["irrigation_flag"]].astype(str).str.strip().str.lower().isin(["yes", "y", "true", "1", "oui"])
    else:
        d["irrigue"] = d["surface"] > 0

    keep = d["annee"].between(p["declarations_annee_min"], p["declarations_annee_max"])
    log_reject(fait, f"hors fenetre {p['declarations_annee_min']}-{p['declarations_annee_max']}", (~keep).sum())
    d = d[keep]
    log_reject(fait, "pas d'irrigation declaree", (~d["irrigue"]).sum())
    d = d[d["irrigue"]]
    sans_surface = ~(d["surface"] > 0)      # ex. fournisseurs en gros (DWR, Bureau of Reclamation) : volumes enormes, aucune surface
    log_reject(fait, "irrigation declaree sans surface irriguee (fournisseurs d'eau en gros)", sans_surface.sum())
    d = d[~sans_surface]
    if p.get("declarations_exiger_volume"):
        has_vol = d["vol_aut"].notna() | d["vol_dec"].notna()
        log_reject(fait, "aucun volume renseigne", (~has_vol).sum())
        d = d[has_vol]
    d = d.copy()

    # Le volume autorise (FACE_VALUE) est repete sur chaque ligne-culture d'un meme droit et d'une meme annee :
    # on le repartit au prorata des surfaces pour ne pas le compter plusieurs fois.
    d["annee"] = d["annee"].astype(int)
    grp = d["droit_id"].fillna(pd.Series("ligne" + d.index.astype(str), index=d.index)) + "|" + d["annee"].astype(str)
    fmax = d["vol_aut"].groupby(grp).transform("max")
    area = d["surface"].fillna(0)
    garea = area.groupby(grp).transform("sum")
    n_g = grp.groupby(grp).transform("size")
    share = np.where(garea > 0, area / garea.replace(0, np.nan), 1.0 / n_g)
    multi = int((n_g > 1).sum())
    d["vol_aut"] = fmax * share
    print(f"   volume autorise reparti entre cultures sur {multi} lignes ({int(grp[n_g > 1].nunique())} droits-annees)")

    d["culture_code"] = d["culture"].map(lambda x: slug(x) if x else None)
    d["source_code"] = d["source"].map(lambda x: slug(x) if x else None)
    d["type_code"] = d["type_droit"].map(lambda x: slug(x) if x else None)
    d["comte_code"] = d["comte"].map(lambda x: slug(x) if x else None)
    d["id_exploitant"] = d["exploitant"].map(lambda x: re.sub(r"\s+", " ", x.upper()) if x else None)
    d.loc[d["id_exploitant"].isna() & d["droit_id"].notna(), "id_exploitant"] = "DROIT-" + d["droit_id"]

    present = {"comte": d["comte"].notna(), "culture": d["culture"].notna(), "surface": d["surface"] > 0,
               "source": d["source"].notna(), "volume_autorise": d["vol_aut"].notna(),
               "exploitant": d["exploitant"].notna()}
    attendus = [c for c in SETTINGS["champs_attendus"] if c in present]
    d["nb_attendus"] = len(attendus)
    d["nb_renseignes"] = sum(present[c].astype(int) for c in attendus)

    k = (d["droit_id"].fillna("NA") + "|" + d["annee"].astype(str) + "|" + d["culture_code"].fillna("NA"))
    d["id_declaration"] = k + "|" + (k.groupby(k).cumcount() + 1).astype(str)
    print(f"Declarations : {n_raw} lignes brutes -> {len(d)} retenues "
          f"({int(d['vol_aut'].notna().sum())} avec volume autorise, {int(d['culture'].notna().sum())} avec culture)")
    return d


# ----------------------------------------------------------- DIMENSIONS
def load_dimensions(wr: pd.DataFrame, et_c: pd.DataFrame, et_b: pd.DataFrame):
    # --- comtes
    vall_of = {}
    for vname, lst in SETTINGS["comtes_par_vallee"].items():
        for c in lst:
            vall_of[slug(c)] = vname
    ref = {slug(v["comte_ref"]): v for v in SETTINGS["vallees"]}
    names = {}
    for s in (et_c["cle"].map(title_county), wr["comte"]):
        for n in s.dropna().unique():
            names[slug(n)] = n
    for v in SETTINGS["vallees"]:
        names.setdefault(slug(v["comte_ref"]), v["comte_ref"])
    surf = {}
    if "_surface" in et_c.columns:
        t = et_c.assign(_k=et_c["cle"].map(lambda x: slug(title_county(x))))
        surf = t.groupby("_k")["_surface"].median().dropna().to_dict()
    try:                                  # surface agricole cartographiee 2024 (Statewide Crop Mapping)
        from . import crops
        for n in crops.county_names():
            names.setdefault(slug(n), n)
        for k_, v_ in crops.county_acres().items():     # comble les comtes sans masque ET
            surf.setdefault(k_, v_)
    except Exception as e:
        print(f"   (crop mapping ignore : {e})")
    rows = [{"code_comte": code, "nom_comte": nom, "vallee_agricole": vall_of.get(code, "Autre"),
             "surface_agricole_acres": surf.get(code),
             "latitude_ref": ref[code]["lat"] if code in ref else None,
             "longitude_ref": ref[code]["lon"] if code in ref else None} for code, nom in sorted(names.items())]
    upsert("dim_comte", pd.DataFrame(rows), "code_comte")

    # --- culture / source / type de droit
    cu = wr[["culture_code", "culture"]].dropna().drop_duplicates("culture_code")
    upsert("dim_culture", pd.DataFrame({"code_culture": cu["culture_code"], "nom_culture": cu["culture"],
                                        "famille_culture": cu["culture"].map(famille_culture),
                                        "est_renseignee": True}), "code_culture")
    so = wr[["source_code", "source"]].dropna().drop_duplicates("source_code")
    upsert("dim_source_eau", pd.DataFrame({"code_source": so["source_code"], "libelle_source": so["source"],
                                           "categorie_source": so["source"].map(categorie_source)}), "code_source")
    td = wr[["type_code", "type_droit"]].dropna().drop_duplicates("type_code")
    upsert("dim_type_droit", pd.DataFrame({"code_type_droit": td["type_code"], "libelle_type_droit": td["type_droit"]}),
           "code_type_droit")

    # --- exploitants
    ex = (wr.dropna(subset=["id_exploitant"]).groupby("id_exploitant")
          .agg(nom_exploitant=("exploitant", "first"), nb_comtes_actifs=("comte_code", "nunique")).reset_index())
    ex["nom_exploitant"] = ex["nom_exploitant"].fillna(ex["id_exploitant"])
    ex = ex.rename(columns={"id_exploitant": "id_exploitant_source"})
    upsert("dim_exploitant", ex, "id_exploitant_source")

    # --- bassins
    b = et_b[["cle"]].drop_duplicates()
    upsert("dim_bassin", pd.DataFrame({"code_bassin": b["cle"].map(slug), "nom_bassin": b["cle"]}), "code_bassin")

    # --- parcelles et capteurs simules
    pp, cp = DATA_STAGING / "sim_parcelles.csv", DATA_STAGING / "sim_capteurs.csv"
    if pp.exists() and cp.exists():
        par = pd.read_csv(pp)
        upsert("dim_parcelle", par[["id_parcelle", "surface_acres", "culture_dominante", "latitude", "longitude",
                                    "origine"]], "id_parcelle")
        cap = pd.read_csv(cp)
        upsert("dim_capteur", cap[["id_capteur", "type_capteur", "date_installation", "statut"]], "id_capteur")
    for t in ("dim_comte", "dim_culture", "dim_source_eau", "dim_type_droit", "dim_exploitant", "dim_bassin",
              "dim_parcelle", "dim_capteur"):
        n = read_sql(f"SELECT count(*) n FROM {SCHEMA}.{t} WHERE sk_{t[4:]} <> -1" if t != "dim_comte"
                     else f"SELECT count(*) n FROM {SCHEMA}.dim_comte WHERE sk_comte <> -1")["n"][0]
        log(t, MODE, f"{n} lignes")


# ---------------------------------------------------------------- FAITS
def load_fait_declaration(wr: pd.DataFrame):
    m_c, m_x = sk_map("dim_comte", "code_comte", "sk_comte"), sk_map("dim_exploitant", "id_exploitant_source", "sk_exploitant")
    m_u, m_s = sk_map("dim_culture", "code_culture", "sk_culture"), sk_map("dim_source_eau", "code_source", "sk_source_eau")
    m_t = sk_map("dim_type_droit", "code_type_droit", "sk_type_droit")
    f = pd.DataFrame({
        "id_declaration": wr["id_declaration"],
        "sk_temps": wr["annee"] * 10000 + 101,                       # 1er janvier de l'annee declaree
        "sk_comte": apply_sk(wr["comte_code"], m_c), "sk_exploitant": apply_sk(wr["id_exploitant"], m_x),
        "sk_culture": apply_sk(wr["culture_code"], m_u), "sk_source_eau": apply_sk(wr["source_code"], m_s),
        "sk_type_droit": apply_sk(wr["type_code"], m_t),
        "volume_autorise_acft": wr["vol_aut"].round(3), "volume_declare_acft": wr["vol_dec"].round(3),
        "surface_irriguee_acres": wr["surface"].round(3), "nb_declarations": 1,
        "nb_champs_renseignes": wr["nb_renseignes"].astype(int), "nb_champs_attendus": wr["nb_attendus"].astype(int),
        "indicateur_culture_renseignee": wr["culture"].notna().astype(int)})
    copy_df(f, f"{SCHEMA}.fait_declaration_irrigation")
    quality.check_count("fait_declaration_irrigation", len(f), f"{SCHEMA}.fait_declaration_irrigation")
    quality.check_sum("volume autorise (fait vs source)", wr["vol_aut"].sum(),
                      f"SELECT sum(volume_autorise_acft) FROM {SCHEMA}.fait_declaration_irrigation")
    log("fait_declaration_irrigation", MODE, f"{len(f)} lignes")


def load_fait_et(table: str, et: pd.DataFrame, dim: str, nk: str, sk: str, is_county: bool):
    if is_county:
        et = et.assign(code=et["cle"].map(lambda x: slug(title_county(x))))
    else:
        et = et.assign(code=et["cle"].map(slug))
    m = sk_map(dim, nk, sk)
    f = pd.DataFrame({"sk_temps": date_to_sk(et["mois"]), sk: apply_sk(et["code"], m)})
    for c in ("et_moyenne_acft", "et_moyenne_pouces", "et_min_modeles_acft", "et_max_modeles_acft",
              "et_ecart_type_modeles_acft"):
        f[c] = et[c].round(4)
    f["nb_modeles_renseignes"] = et["nb_modeles_renseignes"]
    bad = f[sk] == -1
    log_reject(table, "cle inconnue", bad.sum())
    f = f[~bad].drop_duplicates(["sk_temps", sk])
    copy_df(f, f"{SCHEMA}.{table}")
    quality.check_count(table, len(f), f"{SCHEMA}.{table}")
    log(table, MODE, f"{len(f)} lignes")


def load_fait_meteo():
    path = DATA_RAW / "open_meteo_daily.csv"
    w = pd.read_csv(path, parse_dates=["date"])
    m = sk_map("dim_comte", "code_comte", "sk_comte")
    f = pd.DataFrame({"sk_temps": date_to_sk(w["date"]), "sk_comte": apply_sk(w["comte_ref"].map(slug), m)})
    for c in ("temperature_min_c", "temperature_max_c", "temperature_moy_c", "precipitations_mm", "et0_mm",
              "humidite_relative_pct", "vent_kmh", "rayonnement_mjm2", "humidite_sol_m3m3", "temperature_sol_c"):
        f[c] = w[c].round(4)
    copy_df(f, f"{SCHEMA}.fait_meteo_jour")
    quality.check_count("fait_meteo_jour", len(f), f"{SCHEMA}.fait_meteo_jour")
    n_days = w["date"].nunique()
    quality.check_value("meteo : lignes = vallees x jours", len(SETTINGS["vallees"]) * n_days, len(f))
    log("fait_meteo_jour", MODE, f"{len(f)} lignes")


def load_fait_capteur():
    path = DATA_STAGING / "sim_releves.csv"
    if not path.exists():
        print("Pas de releves simules : lancer `python run.py simulate`")
        return
    r = pd.read_csv(path, parse_dates=["date"])
    m_c, m_p = sk_map("dim_capteur", "id_capteur", "sk_capteur"), sk_map("dim_parcelle", "id_parcelle", "sk_parcelle")
    m_k = sk_map("dim_comte", "code_comte", "sk_comte")
    f = pd.DataFrame({"sk_temps": date_to_sk(r["date"]), "sk_capteur": apply_sk(r["id_capteur"], m_c),
                      "sk_parcelle": apply_sk(r["id_parcelle"], m_p), "sk_comte": apply_sk(r["comte_ref"].map(slug), m_k)})
    for c in ("humidite_sol_m3m3", "temperature_sol_c", "ph", "conductivite_dsm"):
        f[c] = r[c]
    f["indicateur_alerte"] = r["indicateur_alerte"].astype(int)
    f["indicateur_capteur_actif"] = r["indicateur_capteur_actif"].astype(int)
    copy_df(f, f"{SCHEMA}.fait_releve_capteur")
    quality.check_count("fait_releve_capteur", len(f), f"{SCHEMA}.fait_releve_capteur")
    log("fait_releve_capteur", MODE, f"{len(f)} lignes")


# ------------------------------------------------------------- ORCHESTRATION
def run_etl():
    global MODE
    MODE = current_mode()
    log("etl", MODE, "debut du chargement" + (" (DONNEES DE DEMONSTRATION)" if MODE == "demo" else ""))
    with engine().begin() as con:   # faits : rechargement complet (les predictions sont a recalculer)
        con.execute(text("TRUNCATE " + ", ".join(f"{SCHEMA}.{t}" for t in FACTS) + " RESTART IDENTITY"))
        con.execute(text("TRUNCATE etl.rejets, etl.controle"))
    wr = prepare_water_rights()
    et_c = prepare_et("et_comte", "comte")
    et_b = prepare_et("et_bassin", "bassin")
    load_dim_temps()
    load_dimensions(wr, et_c, et_b)
    load_fait_declaration(wr)
    load_fait_et("fait_et_mensuelle_comte", et_c, "dim_comte", "code_comte", "sk_comte", True)
    load_fait_et("fait_et_mensuelle_bassin", et_b, "dim_bassin", "code_bassin", "sk_bassin", False)
    if (DATA_RAW / "open_meteo_daily.csv").exists():
        load_fait_meteo()
    load_fait_capteur()
    quality.report()
    log("etl", MODE, "termine. Relancer `python run.py ml` pour recalculer les predictions.")
