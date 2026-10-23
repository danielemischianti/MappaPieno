#!/usr/bin/env python3
"""
Aggiorna data/prezzi.json leggendo i prezzi dal servizio Osservaprezzi del MIMIT
(carburanti.mise.gov.it/ospzApi), cioè la stessa fonte del sito ufficiale del Ministero.

Perché non i file CSV: da ottobre 2026 www.mimit.gov.it non risponde ai server di GitHub
(timeout), mentre carburanti.mise.gov.it sì. In più questo servizio dà i prezzi in vigore
al momento della lettura, non la fotografia delle 8 di mattina.

Una richiesta per regione (20 in tutto), con una pausa tra l'una e l'altra.
Produce lo stesso formato di update.py, quindi l'app non cambia.

Uso:
    python3 update_api.py --out _site/data/prezzi.json [--precedente URL_o_file] [--regioni 9,12]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request

API = os.environ.get("OSPZ_API", "https://carburanti.mise.gov.it/ospzApi")
UA = {"User-Agent": "pieno-kamiq/1.0 (uso personale)", "Accept": "application/json",
      "Content-Type": "application/json"}
FUEL_BENZINA = 1
FUEL_METANO = 3          # L-GNC (323) e GNL (324) esclusi di proposito, vedi update.py
try:
    from zoneinfo import ZoneInfo
    ROME = ZoneInfo("Europe/Rome")
except Exception:  # tzdata assente: basta per ricavare la data
    ROME = dt.timezone(dt.timedelta(hours=1))


def call(path, body=None, attempts=4):
    data = json.dumps(body).encode() if body is not None else None
    for n in range(attempts):
        try:
            req = urllib.request.Request(API + path, data=data, headers=UA, method="POST" if data else "GET")
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:
            if n == attempts - 1:
                raise RuntimeError(f"{path}: {e}") from e
            time.sleep((10, 30, 60)[min(n, 2)])


def gh(level, msg):
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level}::{msg}")
    print(msg, file=sys.stderr)


def title(s):
    s = " ".join(str(s or "").split())
    return s.title() if s.isupper() else s


def load_prev(src):
    """Dati pubblicati in precedenza: servono per comune, provincia e flag autostradale."""
    if not src:
        return {}
    try:
        if src.startswith("http"):
            req = urllib.request.Request(src + "?t=" + str(int(time.time())), headers={"User-Agent": UA["User-Agent"]})
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.load(r)
        else:
            with open(src, encoding="utf-8") as f:
                d = json.load(f)
        c = {k: i for i, k in enumerate(d["campi"])}
        return {str(r[c["id"]]): {"comune": r[c["comune"]], "prov": r[c["prov"]], "aut": r[c["autostrada"]],
                                  "indirizzo": r[c["indirizzo"]]} for r in d["impianti"]}
    except Exception as e:
        print(f"Dati precedenti non disponibili ({e}): comune e provincia ricavati dall'indirizzo", file=sys.stderr)
        return {}


ADDR = re.compile(r"^(?P<via>.*?)\s*-\s*(?P<cap>\d{5})?\s*-?\s*(?P<comune>.+?)\s+(?P<prov>[A-Z]{2})\s*$")
AUT = re.compile(r"autostrad|area di servizio|\bA\d{1,2}\b(?!\s*G\.?R\.?A)", re.I)


def parse_address(a):
    m = ADDR.match(" ".join(str(a or "").split()))
    if not m:
        return title(a), "", ""
    return title(m["via"]), title(m["comune"]), m["prov"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--precedente", default="")
    ap.add_argument("--regioni", default="", help="id regione separati da virgola (default: tutte)")
    ap.add_argument("--pausa", type=float, default=1.5)
    args = ap.parse_args()

    prev = load_prev(args.precedente)
    regions = call("/registry/region")["results"]
    if args.regioni:
        want = {x.strip() for x in args.regioni.split(",")}
        regions = [r for r in regions if str(r["id"]) in want]

    stations = {}
    for reg in regions:
        res = call("/search/area", {"region": int(reg["id"])})
        if not res.get("success"):
            raise RuntimeError(f"regione {reg['description']}: risposta non valida")
        for x in res.get("results") or []:
            stations[str(x["id"])] = x
        print(f"{reg['description']}: {len(res.get('results') or [])} impianti", file=sys.stderr)
        time.sleep(args.pausa)

    out, n_m = [], 0
    for sid, x in stations.items():
        loc = x.get("location") or {}
        lat, lon = loc.get("lat"), loc.get("lng")
        if lat is None or lon is None or not (35 < lat < 48 and 6 < lon < 19):
            continue
        p = {}
        for f in x.get("fuels") or []:
            fid, price = f.get("fuelId"), f.get("price")
            if fid not in (FUEL_BENZINA, FUEL_METANO) or not price or price <= 0.3 or price > 5:
                continue
            key = ("b" if fid == FUEL_BENZINA else "m") + ("s" if f.get("isSelf") else "v")
            p[key] = min(price, p.get(key, price))
        if not p:
            continue
        day = ""
        if x.get("insertDate"):
            try:
                day = dt.datetime.fromisoformat(x["insertDate"]).date().isoformat()
            except ValueError:
                day = str(x["insertDate"])[:10]
        via, comune, prov = parse_address(x.get("address"))
        old = prev.get(sid, {})
        aut = old.get("aut")
        if aut is None:
            aut = 1 if AUT.search(f"{x.get('name', '')} {x.get('address', '')}") else 0
        m = min([v for k, v in p.items() if k[0] == "m"], default=None)
        n_m += m is not None
        out.append([int(sid) if sid.isdigit() else sid, title(x.get("name")), x.get("brand") or "",
                    old.get("indirizzo") or via, old.get("comune") or comune, old.get("prov") or prov, aut,
                    round(lat, 5), round(lon, 5), p.get("bs"), p.get("bv"), m,
                    day if ("bs" in p or "bv" in p) else "", day if m is not None else "",
                    p.get("ms"), p.get("mv")])

    if not args.regioni and len(out) < 15000:
        raise SystemExit(gh("error", f"Solo {len(out)} impianti dal servizio MIMIT (di solito oltre 20.000): dati incompleti, non pubblico") or 1)

    now = dt.datetime.now(dt.timezone.utc)
    data = {
        "fonte": "MIMIT - Osservaprezzi carburanti (servizio carburanti.mise.gov.it, prezzi in vigore alla lettura)",
        "estrazione": now.astimezone(ROME).date().isoformat(),
        "aggiornato": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generato": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "campi": ["id", "nome", "bandiera", "indirizzo", "comune", "prov", "autostrada", "lat", "lon",
                  "benzina_self", "benzina_servito", "metano", "agg_benzina", "agg_metano",
                  "metano_self", "metano_servito"],
        "impianti": out,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, args.out)
    print(f"OK: {len(out)} impianti ({n_m} con metano) da {len(regions)} regioni -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
