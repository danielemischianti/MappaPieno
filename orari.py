#!/usr/bin/env python3
"""
Aggiorna data/orari.json con gli orari di apertura dei distributori (MIMIT Osservaprezzi).

Gli orari non sono nei CSV giornalieri: si leggono dalla scheda di ogni impianto
(carburanti.mise.gov.it/ospzApi/registry/servicearea/<id>). Per non caricare il
servizio, ogni esecuzione scarica al massimo --max schede: prima quelle mai lette
(i distributori di metano per primi), poi quelle più vecchie di --giorni giorni.
Il resto viene preso dalla cache (il file pubblicato il giorno prima).

Formato di uscita, per impianto:
  "id": {"t": "AAAA-MM-GG", "d": [giorno1..giorno8]}   (1 = lunedì … 7 = domenica, 8 = festivi)
  ogni giorno: [orario, self]  dove orario è
     "H"                  aperto 24 ore
     "C"                  chiuso
     ""                   non comunicato
     "07:00-12:30 15:00-19:30"   fasce di apertura con personale
  e self = 1 se il gestore dichiara il self service attivo quel giorno.

Uso:
  python3 orari.py --prezzi _site/data/prezzi.json --cache https://.../data/orari.json --out _site/data/orari.json
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

API = os.environ.get("ORARI_API", "https://carburanti.mise.gov.it/ospzApi/registry/servicearea/{}")
UA = {"User-Agent": "pieno-kamiq/1.0 (uso personale)", "Accept": "application/json"}
TIME = re.compile(r"(\d{1,2})[:.](\d{2})")


def load_json(src):
    if not src:
        return None
    try:
        if src.startswith("http"):
            req = urllib.request.Request(src, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        with open(src, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # cache assente al primo giro: si parte da zero
        print(f"Cache non disponibile ({src}): {e}", file=sys.stderr)
        return None


def hhmm(v):
    m = TIME.search(str(v or ""))
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def day_code(o):
    if o.get("flagH24"):
        return "H"
    if o.get("flagChiusura"):
        return "C"
    if o.get("flagNonComunicato"):
        return ""
    spans = []
    if o.get("flagOrarioContinuato"):
        a, b = hhmm(o.get("oraAperturaOrarioContinuato")), hhmm(o.get("oraChiusuraOrarioContinuato"))
        if a and b:
            spans.append(f"{a}-{b}")
    else:
        for ka, kb in (("oraAperturaMattina", "oraChiusuraMattina"), ("oraAperturaPomeriggio", "oraChiusuraPomeriggio")):
            a, b = hhmm(o.get(ka)), hhmm(o.get(kb))
            if a and b:
                spans.append(f"{a}-{b}")
    return " ".join(spans)


def fetch_hours(sid):
    req = urllib.request.Request(API.format(sid), headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        j = json.load(r)
    days = [["", 0] for _ in range(8)]
    for o in j.get("orariapertura") or []:
        g = o.get("giornoSettimanaId")
        if isinstance(g, int) and 1 <= g <= 8:
            days[g - 1] = [day_code(o), 1 if o.get("flagSelf") else 0]
    return days


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prezzi", required=True)
    ap.add_argument("--cache", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max", type=int, default=6000)
    ap.add_argument("--giorni", type=int, default=7, help="rilegge le schede più vecchie di N giorni")
    ap.add_argument("--thread", type=int, default=2)
    ap.add_argument("--pausa", type=float, default=0.3, help="secondi tra una richiesta e l'altra, per thread")
    ap.add_argument("--minuti", type=float, default=20, help="tempo massimo per esecuzione")
    args = ap.parse_args()

    prezzi = load_json(args.prezzi)
    campi = {c: i for i, c in enumerate(prezzi["campi"])}
    stations = [(str(r[campi["id"]]), r[campi["metano"]] is not None) for r in prezzi["impianti"]]
    ids = {sid for sid, _ in stations}

    cache = (load_json(args.cache) or {}).get("orari", {})
    orari = {k: v for k, v in cache.items() if k in ids}
    today = dt.date.today()
    limit_age = (today - dt.timedelta(days=args.giorni)).isoformat()

    has_metano = dict(stations)
    missing = [sid for sid, _ in stations if sid not in orari]
    missing.sort(key=lambda sid: 0 if has_metano[sid] else 1)   # metano prima
    old = sorted((sid for sid in orari if orari[sid].get("t", "") < limit_age), key=lambda s: orari[s].get("t", ""))
    todo = (missing + old)[: args.max]
    print(f"Orari: {len(orari)} in cache, {len(missing)} mancanti, {len(old)} da rinfrescare, ne leggo {len(todo)}", file=sys.stderr)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    def save():
        tmp = args.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"fonte": "MIMIT - Osservaprezzi carburanti, schede impianto",
                       "generato": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "orari": dict(orari)}, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, args.out)

    diag = {"letti": 0, "errori": 0, "codici": {}, "interrotto": ""}

    def save():
        tmp = args.out + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"fonte": "MIMIT - Osservaprezzi carburanti, schede impianto",
                       "generato": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "ultimo_giro": diag, "orari": dict(orari)}, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, args.out)

    save()   # subito la cache: se il passo viene interrotto, il file resta valido
    stop = threading.Event()
    lock = threading.Lock()
    deadline = time.monotonic() + args.minuti * 60
    fails_in_row = 0

    def note_err(code):
        nonlocal fails_in_row
        with lock:
            diag["errori"] += 1
            diag["codici"][code] = diag["codici"].get(code, 0) + 1
            fails_in_row += 1
            if fails_in_row >= 10 and not stop.is_set():
                diag["interrotto"] = "10 errori di fila (ultimo: " + code + ")"
                stop.set()

    def work(sid):
        nonlocal fails_in_row
        for attempt in range(3):
            if stop.is_set():
                return
            if time.monotonic() > deadline:
                diag["interrotto"] = diag["interrotto"] or "tempo massimo raggiunto"
                stop.set()
                return
            try:
                d = fetch_hours(sid)
                with lock:
                    orari[sid] = {"t": today.isoformat(), "d": d}
                    diag["letti"] += 1
                    fails_in_row = 0
                    if diag["letti"] % 500 == 0:
                        save()
                time.sleep(args.pausa)
                return
            except urllib.error.HTTPError as e:
                note_err(str(e.code))
                if e.code == 404:
                    return
                wait = e.headers.get("Retry-After") if e.headers else None
                time.sleep(min(60, int(wait)) if wait and wait.isdigit() else 10 * (attempt + 1))
            except Exception as e:
                note_err(type(e).__name__)
                time.sleep(5 * (attempt + 1))

    with cf.ThreadPoolExecutor(max_workers=args.thread) as ex:
        list(ex.map(work, todo))

    save()
    print(f"OK: letti {diag['letti']}, errori {diag['errori']} {diag['codici']} {diag['interrotto']}; "
          f"{len(orari)}/{len(ids)} impianti con scheda -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
