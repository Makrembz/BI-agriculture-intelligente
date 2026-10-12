"""Fonctions utilitaires : normalisation de noms, correspondance de colonnes."""
import re
import unicodedata

import pandas as pd


class ColumnMappingError(Exception):
    pass


def norm(s) -> str:
    """minuscules, sans accents ni ponctuation : 'Face_Value (ac-ft)' -> 'facevalueacft'."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def slug(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def clean_text(s):
    """Texte propre ou None si vide."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if s and s.lower() not in {"nan", "none", "null", "n/a", "na"} else None


def resolve_columns(df: pd.DataFrame, mapping: dict, required=(), source: str = "") -> dict:
    """Associe chaque champ logique a une colonne reelle du DataFrame (ou None)."""
    cols = list(df.columns)
    by_norm = {}
    for c in cols:
        by_norm.setdefault(norm(c), c)
    out = {}
    for logical, aliases in mapping.items():
        found = None
        for a in aliases:                      # 1) correspondance exacte
            if not str(a).startswith("~") and norm(a) in by_norm:
                found = by_norm[norm(a)]
                break
        if found is None:                      # 2) correspondance "contient"
            for a in aliases:
                if str(a).startswith("~"):
                    key = norm(a[1:])
                    hit = next((c for n, c in by_norm.items() if key in n), None)
                    if hit:
                        found = hit
                        break
        out[logical] = found
    missing = [k for k in required if out.get(k) is None]
    if missing:
        raise ColumnMappingError(
            f"[{source}] colonnes introuvables pour : {missing}.\n"
            f"Colonnes reelles : {cols}\n"
            f"-> ajoutez le bon nom dans config/column_mapping.yml (section {source})."
        )
    return out


def title_county(s):
    s = clean_text(s)
    if s is None:
        return None
    s = re.sub(r"\s+county$", "", s, flags=re.I)
    return s.title()
