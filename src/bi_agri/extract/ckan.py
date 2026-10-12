"""Telechargement des ressources du portail data.ca.gov (API CKAN)."""
import time
from pathlib import Path

import pandas as pd
import requests

from ..config import SETTINGS, raw_path

BASE = SETTINGS["ckan"]["base_url"].rstrip("/")


def _session():
    s = requests.Session()
    s.headers["User-Agent"] = "bi-agriculture-intelligente/1.0 (projet universitaire)"
    return s


def _get(session, url, **kw):
    for attempt in range(4):
        try:
            r = session.get(url, timeout=120, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def resource_info(rid: str) -> dict:
    r = _get(_session(), f"{BASE}/api/3/action/resource_show", params={"id": rid})
    return r.json()["result"]


def _paginate(rid: str, dest: Path, page: int = 30000):
    s = _session()
    offset, frames = 0, []
    while True:
        r = _get(s, f"{BASE}/api/3/action/datastore_search",
                 params={"resource_id": rid, "limit": page, "offset": offset})
        recs = r.json()["result"]["records"]
        if not recs:
            break
        frames.append(pd.DataFrame(recs))
        offset += len(recs)
        print(f"   {offset} lignes...")
        if len(recs) < page:
            break
    df = pd.concat(frames, ignore_index=True)
    df = df.drop(columns=[c for c in ("_id", "_full_text") if c in df.columns])
    df.to_csv(dest, index=False)


def download_resource(rid: str, name: str, force: bool = False) -> Path:
    """Telecharge la ressource vers data/raw/<name>.csv (CSV direct, sinon API datastore)."""
    dest = raw_path(name)
    if dest.exists() and not force:
        print(f"{dest.name} existe deja (utiliser --force pour retelecharger)")
        return dest
    info = resource_info(rid)
    url = info.get("url") or ""
    fmt = (info.get("format") or "").upper()
    if url and fmt == "CSV":
        print(f"Telechargement {name} depuis {url}")
        s = _session()
        with s.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
    else:
        print(f"Telechargement {name} via l'API datastore (ressource {rid})")
        _paginate(rid, dest)
    return dest
