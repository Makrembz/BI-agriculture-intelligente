"""Controles de qualite et reconciliation source -> entrepot (table etl.controle)."""
from ..config import SCHEMA
from ..db import execute, read_sql


def _record(nom, attendu, obtenu, tol=0.0):
    attendu = float(attendu) if attendu is not None else 0.0
    obtenu = float(obtenu) if obtenu is not None else 0.0
    ecart = obtenu - attendu
    ok = abs(ecart) <= max(tol, 0.0005 * abs(attendu))
    execute("INSERT INTO etl.controle (controle, attendu, obtenu, ecart, statut) VALUES (:c,:a,:o,:e,:s)",
            {"c": nom, "a": attendu, "o": obtenu, "e": ecart, "s": "OK" if ok else "ALERTE"})
    return ok


def check_count(nom, attendu, table):
    n = read_sql(f"SELECT count(*) AS n FROM {table}")["n"][0]
    _record(f"{nom} : lignes chargees = lignes preparees", attendu, n)


def check_sum(nom, attendu, sql):
    v = read_sql(sql).iloc[0, 0]
    _record(nom, attendu, v)


def check_value(nom, attendu, obtenu):
    _record(nom, attendu, obtenu)


def report():
    df = read_sql("SELECT controle, attendu, obtenu, statut FROM etl.controle ORDER BY id")
    print("\n=== Controles qualite ===")
    for r in df.itertuples():
        print(f"  [{r.statut}] {r.controle}: attendu={r.attendu:,.0f} obtenu={r.obtenu:,.0f}")
    comp = read_sql(f"""SELECT count(*) total,
        round(100.0*avg(nb_champs_renseignes::numeric/nullif(nb_champs_attendus,0)),1) completude_pct,
        sum(1-indicateur_culture_renseignee) sans_culture
        FROM {SCHEMA}.fait_declaration_irrigation""")
    if not comp.empty and comp["total"][0]:
        print(f"  Completude moyenne des declarations : {comp['completude_pct'][0]} % ; "
              f"sans culture : {int(comp['sans_culture'][0])}")
    alerts = df[df["statut"] == "ALERTE"]
    if len(alerts):
        print(f"  /!\\ {len(alerts)} controle(s) en ALERTE : voir etl.controle")
