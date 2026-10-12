"""Statewide Crop Mapping (DWR) : surface agricole par comte et parcelles reelles pour DIM_PARCELLE.

Lecture des attributs sans geometrie (rapide) ; les geometries ne sont lues que pour les
quelques centaines de parcelles tirees au hasard.
"""
import numpy as np
import pandas as pd

from ..config import MAPPING, SETTINGS, raw_path
from ..utils import clean_text, resolve_columns, slug, title_county

_ATTR = None

# Classe agricole = premiere(s) lettre(s) du code MAIN_CROP (ex. D3 -> D). Libelles a confirmer avec la legende DWR.
CLASSES = {"G": "Céréales et foin", "R": "Riz", "F": "Cultures de plein champ", "P": "Pâturage et fourrage",
           "T": "Maraîchage et baies", "C": "Agrumes et subtropicales", "D": "Arbres fruitiers et noyers",
           "V": "Vigne", "YP": "Jeunes cultures pérennes"}


def decode_crop(code):
    code = clean_text(code)
    if not code:
        return None
    cls = "YP" if code.upper().startswith("YP") else code[0].upper()
    return f"{CLASSES[cls]} ({code})" if cls in CLASSES else None


def find_shapefile():
    d = raw_path("crop_mapping_dossier")
    if not d.exists():
        return None
    shp = sorted(d.rglob("*.shp"))
    return shp[0] if shp else None


def read_attributes() -> pd.DataFrame | None:
    """Attributs de la couche (fid en index). None si la couche ou geopandas/pyogrio est absent."""
    global _ATTR
    if _ATTR is not None:
        return _ATTR
    shp = find_shapefile()
    if shp is None:
        return None
    try:
        import pyogrio
    except ImportError:
        print("   (pyogrio/geopandas non installe : `pip install geopandas pyogrio` pour utiliser le crop mapping)")
        return None
    print(f"Lecture des attributs de {shp.name} ...")
    _ATTR = pyogrio.read_dataframe(shp, read_geometry=False, fid_as_index=True)
    return _ATTR


def _cols(df):
    return resolve_columns(df, MAPPING["crop_mapping"], required=["comte", "surface"], source="crop_mapping")


def county_acres() -> dict:
    """{code_comte: surface cartographiee en acres}."""
    df = read_attributes()
    if df is None:
        return {}
    c = _cols(df)
    t = pd.DataFrame({"comte": df[c["comte"]].map(title_county), "acres": pd.to_numeric(df[c["surface"]], errors="coerce")})
    t = t.dropna()
    return {slug(k): float(v) for k, v in t.groupby("comte")["acres"].sum().items()}


def county_names() -> list[str]:
    df = read_attributes()
    if df is None:
        return []
    c = _cols(df)
    return sorted({x for x in df[c["comte"]].map(title_county).dropna().unique()})


def sample_parcels() -> pd.DataFrame | None:
    """Parcelles agricoles REELLES tirees au hasard dans les comtes des 4 vallees."""
    df = read_attributes()
    if df is None:
        return None
    import pyogrio
    import geopandas as gpd
    cfg = SETTINGS["parcelles_sig"]
    c = _cols(df)
    rng = np.random.default_rng(SETTINGS["capteurs"]["graine"])
    attrs = pd.DataFrame({"comte": df[c["comte"]].map(title_county),
                          "acres": pd.to_numeric(df[c["surface"]], errors="coerce"),
                          "culture": df[c["culture"]].map(clean_text) if c.get("culture") else None})
    attrs["label"] = attrs["culture"].map(decode_crop) if c.get("culture") else None
    shp = find_shapefile()
    picks = []
    for v in SETTINGS["vallees"]:
        counties = {slug(x) for x in SETTINGS["comtes_par_vallee"][v["nom"]]}
        ok = attrs[attrs["comte"].map(lambda x: slug(x) in counties if x else False)
                   & attrs["acres"].between(cfg["surface_min_acres"], cfg["surface_max_acres"])
                   & attrs["label"].notna()]            # uniquement des parcelles cultivees
        if ok.empty:
            continue
        idx = rng.choice(ok.index.to_numpy(), size=min(cfg["par_vallee"], len(ok)), replace=False)
        sub = ok.loc[idx].copy()
        sub["vallee"] = v["nom"]
        picks.append(sub)
    if not picks:
        return None
    sel = pd.concat(picks)
    gdf = pyogrio.read_dataframe(shp, fids=[int(i) for i in sel.index])
    gdf.index = sel.index if len(gdf) == len(sel) else gdf.index
    if gdf.crs is not None:
        cent = gpd.GeoSeries(gdf.geometry.to_crs(3310).centroid, crs=3310).to_crs(4326)
    else:
        cent = gdf.geometry.centroid
    sel["latitude"] = cent.y.round(5).to_numpy()
    sel["longitude"] = cent.x.round(5).to_numpy()
    sel["culture"] = sel["label"]
    sel["id_source"] = sel.index.astype(str)
    return sel.reset_index(drop=True)
