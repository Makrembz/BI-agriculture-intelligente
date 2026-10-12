"""Acces PostgreSQL : moteur SQLAlchemy, execution de scripts, chargement rapide par COPY."""
import io

import pandas as pd
from sqlalchemy import create_engine, text

from .config import SQL_DIR, db_url

_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = create_engine(db_url(), future=True)
    return _engine


def run_sql_file(name: str):
    sql = (SQL_DIR / name).read_text(encoding="utf-8")
    raw = engine().raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute(sql)
        raw.commit()
    finally:
        raw.close()


def execute(sql: str, params: dict | None = None):
    with engine().begin() as con:
        con.execute(text(sql), params or {})


def read_sql(sql: str, params: dict | None = None) -> pd.DataFrame:
    with engine().connect() as con:
        return pd.read_sql(text(sql), con, params=params)


def copy_df(df: pd.DataFrame, table: str, columns: list[str] | None = None):
    """Charge un DataFrame dans une table avec COPY (rapide, meme pour 365 000 lignes)."""
    columns = columns or list(df.columns)
    buf = io.StringIO()
    df[columns].to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    cols = ", ".join(columns)
    raw = engine().raw_connection()
    try:
        with raw.cursor() as cur:
            cur.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv, NULL '\\N')", buf)
        raw.commit()
    finally:
        raw.close()


def log(etape: str, mode: str, message: str = ""):
    execute("INSERT INTO etl.journal (etape, mode_donnees, message) VALUES (:e, :m, :msg)",
            {"e": etape, "m": mode, "msg": message})
    print(f"[{etape}] {message}")


def log_reject(fait: str, motif: str, n: int):
    if n:
        execute("INSERT INTO etl.rejets (fait, motif, nb_lignes) VALUES (:f, :m, :n)",
                {"f": fait, "m": motif, "n": int(n)})
        print(f"   rejet {fait}: {motif} -> {n} lignes")


def current_mode() -> str:
    """'reel' ou 'demo' selon le fichier marqueur dans data/raw."""
    from .config import DATA_RAW
    return "demo" if (DATA_RAW / "MODE_DEMO").exists() else "reel"
