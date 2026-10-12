"""Chargement de la configuration (settings.yml, column_mapping.yml, .env)."""
import os
import pathlib

import yaml
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DATA_RAW = ROOT / "data" / "raw"
DATA_STAGING = ROOT / "data" / "staging"
DATA_MODELS = ROOT / "data" / "models"
SQL_DIR = ROOT / "sql"
for _d in (DATA_RAW, DATA_STAGING, DATA_MODELS):
    _d.mkdir(parents=True, exist_ok=True)


def _yaml(name):
    with open(ROOT / "config" / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


SETTINGS = _yaml("settings.yml")
MAPPING = _yaml("column_mapping.yml")
SCHEMA = SETTINGS.get("schema", "dwh")


def db_url() -> str:
    env = os.environ
    return "postgresql+psycopg2://{u}:{p}@{h}:{port}/{d}".format(
        u=env.get("PGUSER", "postgres"), p=env.get("PGPASSWORD", ""),
        h=env.get("PGHOST", "localhost"), port=env.get("PGPORT", "5432"),
        d=env.get("PGDATABASE", "bi_agriculture_dw"))


def raw_path(key: str) -> pathlib.Path:
    """Chemin d'un fichier de data/raw d'apres settings.yml (section fichiers)."""
    return DATA_RAW / SETTINGS["fichiers"][key]
