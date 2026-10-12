"""Interface en ligne de commande : python run.py <commande> [options]"""
import argparse
import sys

from .config import DATA_RAW, MAPPING, SETTINGS


def cmd_init_db(a):
    from .db import run_sql_file
    run_sql_file("01_schema.sql")
    print("Schemas dwh et etl crees (tables vides).")


def cmd_extract(a):
    from .extract.ckan import download_resource
    from .extract.weather import extract_weather
    demo = (DATA_RAW / "MODE_DEMO")
    force = a.force or demo.exists()
    if demo.exists():
        demo.unlink()
        print("Donnees de demonstration detectees : elles sont remplacees par les vraies donnees.")
    res = SETTINGS["ckan"]["ressources"]
    download_resource(res["water_rights"], "water_rights", force)
    download_resource(res["et_comte"], "et_comte", force)
    download_resource(res["et_bassin"], "et_bassin", force)
    extract_weather(force)
    print("Extraction terminee. Etape suivante : python run.py profile")


def cmd_profile(a):
    """Affiche, pour chaque source, les colonnes reelles, 2 lignes d'exemple et la correspondance utilisee."""
    import pandas as pd
    from .config import ROOT, raw_path
    from .etl import crops
    from .etl.load import detect_et_columns
    from .utils import resolve_columns
    out = []

    def show(name, df, mapping_key=None):
        out.append(f"## {name} : {len(df.columns)} colonnes")
        out.append("Colonnes : " + ", ".join(map(str, df.columns)))
        for i in range(min(2, len(df))):
            out.append(f"Exemple {i + 1} : " + " | ".join(f"{c}={str(v)[:40]}" for c, v in df.iloc[i].items()))
        if mapping_key:
            m = resolve_columns(df, MAPPING[mapping_key], source=mapping_key)
            for k, v in m.items():
                out.append(f"   {k:16s} -> {v if v else '(non trouve)'}")
        if mapping_key in ("et_comte", "et_bassin"):
            acft, inch = detect_et_columns(df)
            out.append(f"   colonnes ET acre-pieds : {acft}\n   colonnes ET pouces     : {inch}")
        out.append("")

    for key in ("water_rights", "et_comte", "et_bassin", "cimis_stations"):
        p = raw_path(key)
        if not p.exists():
            out.append(f"## {key} : fichier absent ({p.name})\n")
            continue
        df = pd.read_csv(p, nrows=3000, low_memory=False, encoding_errors="replace")
        show(f"{key} ({p.name})", df, key if key in MAPPING else None)
    d = raw_path("crop_mapping_dossier")
    if d.exists():
        out.append("## crop_mapping : fichiers du dossier : " + ", ".join(sorted(f.name for f in d.rglob("*") if f.is_file())))
        attrs = crops.read_attributes()
        if attrs is not None:
            show("crop_mapping (attributs du shapefile, " + str(len(attrs)) + " polygones)", attrs.head(3000), "crop_mapping")
    else:
        out.append("## crop_mapping : dossier absent\n")
    txt = "\n".join(out)
    print(txt)
    dest = ROOT / "docs" / "profil_sources.txt"
    dest.write_text(txt, encoding="utf-8")
    print(f"\n(copie enregistree dans {dest})")


def cmd_simulate(a):
    from .simulate.sensors import simulate_sensors
    simulate_sensors()


def cmd_etl(a):
    from .etl.load import run_etl
    run_etl()


def cmd_ml(a):
    from .ml.run import run_ml
    run_ml(a.only)


def cmd_demo(a):
    from .demo import make_demo
    make_demo()


def cmd_all(a):
    cmd_init_db(a)
    if not a.skip_extract:
        cmd_extract(a)
    cmd_simulate(a)
    cmd_etl(a)
    cmd_ml(a)


def main():
    p = argparse.ArgumentParser(prog="run.py", description="Pipeline BI Agriculture Intelligente")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="cree (ou recree) les schemas dwh et etl").set_defaults(f=cmd_init_db)
    e = sub.add_parser("extract", help="telecharge les sources reelles (data.ca.gov, Open-Meteo)")
    e.add_argument("--force", action="store_true")
    e.set_defaults(f=cmd_extract)
    sub.add_parser("profile", help="affiche les colonnes reelles et la correspondance").set_defaults(f=cmd_profile)
    sub.add_parser("simulate", help="genere la couche de capteurs IoT simules").set_defaults(f=cmd_simulate)
    sub.add_parser("etl", help="charge dimensions et faits dans PostgreSQL").set_defaults(f=cmd_etl)
    m = sub.add_parser("ml", help="entraine les modeles et charge FAIT_PREDICTION")
    m.add_argument("--only", help="demande,prevision,segments,anomalies (liste separee par des virgules)")
    m.set_defaults(f=cmd_ml)
    sub.add_parser("demo-data", help="genere des donnees SYNTHETIQUES pour tester sans reseau").set_defaults(f=cmd_demo)
    al = sub.add_parser("all", help="init-db + extract + simulate + etl + ml")
    al.add_argument("--force", action="store_true")
    al.add_argument("--skip-extract", action="store_true")
    al.set_defaults(f=cmd_all)
    a = p.parse_args()
    try:
        a.f(a)
    except Exception as ex:                     # message lisible pour les erreurs attendues
        from .utils import ColumnMappingError
        if isinstance(ex, (ColumnMappingError, FileNotFoundError)):
            print(f"\nERREUR : {ex}")
            sys.exit(1)
        raise
