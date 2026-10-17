#!/usr/bin/env python3
"""
Aggiorna data/prezzi.json con i prezzi carburante ufficiali MIMIT (Osservaprezzi).

Fonte: open data del Ministero delle Imprese e del Made in Italy, gli stessi prezzi
che i distributori sono obbligati a comunicare e che mostrano i siti di confronto
(prezzobenzina.it compreso). I file vengono pubblicati ogni mattina verso le 8.

Uso:
    python3 update.py                      # tutta Italia
    python3 update.py --prov RM,LT,FR      # solo alcune province (file più leggero)
    python3 update.py --anagrafica a.csv --prezzi p.csv   # file già scaricati

Solo libreria standard, nessuna dipendenza.
"""
import argparse
import datetime as dt
import io
import json
import os
import sys
import time
import traceback
import urllib.request

URL_ANAGRAFICA = "https://www.mimit.gov.it/images/exportCSV/anagrafica_impianti_attivi.csv"
URL_PREZZI = "https://www.mimit.gov.it/images/exportCSV/prezzo_alle_8.csv"

# Carburanti che interessano la Kamiq G-TEC
BENZINA = {"benzina"}                 # solo benzina normale (niente 98/100 ottani)
METANO = {"metano"}
# L-GNC escluso: in teoria è metano compresso ottenuto da GNL, ma nei dati MIMIT compare anche in impianti
# che vendono solo GNL per camion (es. Eni Borghesiana, Roma: metano rimosso nel 2024, L-GNC ancora comunicato).
# GNL (liquido, per camion) escluso.
LGNC = {"l-gnc"}


def fetch(url, attempts=4):
    """Scarica con alcuni tentativi: il sito MIMIT a volte non risponde per qualche minuto."""
    req = urllib.request.Request(url, headers={"User-Agent": "pieno-kamiq/1.0 (uso personale)"})
    for n in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
            if raw[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
                raise ValueError("il server ha risposto con una pagina HTML invece del CSV")
            break
        except Exception as e:
            if n == attempts - 1:
                raise RuntimeError(f"download non riuscito dopo {attempts} tentativi ({url}): {e}") from e
            wait = (20, 60, 120)[min(n, 2)]
            print(f"Tentativo {n + 1} fallito ({e}), riprovo tra {wait} s", file=sys.stderr)
            time.sleep(wait)
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def read_text(path_or_url):
    if path_or_url.startswith("http"):
        return fetch(path_or_url)
    with open(path_or_url, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def rows(text):
    """Restituisce (data_estrazione, header, righe). Gestisce separatore | o ;"""
    lines = [l for l in text.replace("\r", "").split("\n") if l.strip()]
    extraction = ""
    if lines and lines[0].lower().startswith("estrazione"):
        extraction = lines[0].split(" ", 2)[-1].strip()
        lines = lines[1:]
    header_line = lines[0]
    sep = "|" if header_line.count("|") >= header_line.count(";") else ";"
    header = [h.strip() for h in header_line.split(sep)]
    out = []
    for l in lines[1:]:
        parts = [p.strip() for p in l.split(sep)]
        if len(parts) > len(header):
            # separatore dentro un campo di testo: gli ultimi campi sono numerici, uniamo il centro
            extra = len(parts) - len(header)
            mid = len(header) // 2
            parts = parts[:mid] + [" ".join(parts[mid:mid + extra + 1])] + parts[mid + extra + 1:]
        if len(parts) < len(header):
            continue
        out.append(parts)
    return extraction, header, out


def to_float(s):
    try:
        return float(s.replace(",", "."))
    except (ValueError, AttributeError):
        return None


def to_date(s):
    # "25/09/2026 20:00:07" -> "2026-09-25"
    try:
        d = dt.datetime.strptime(s.split(" ")[0], "%d/%m/%Y")
        return d.strftime("%Y-%m-%d")
    except ValueError:
        return ""


def title(s):
    s = " ".join(s.split())
    return s.title() if s.isupper() else s


def gh(level, msg):
    """Messaggio visibile nel riepilogo della GitHub Action (annotazione)."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level}::{msg}")
    print(msg, file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anagrafica", default=URL_ANAGRAFICA)
    ap.add_argument("--prezzi", default=URL_PREZZI)
    ap.add_argument("--prov", default="", help="sigle provincia separate da virgola, es. RM,LT")
    ap.add_argument("--fallback", default="", help="file o URL dei dati pubblicati in precedenza, usati se il MIMIT non risponde")
    ap.add_argument("--max-giorni-fallback", type=int, default=3)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "prezzi.json"))
    args = ap.parse_args()
    try:
        build(args)
    except Exception as e:
        reason = f"{type(e).__name__}: {e}"
        traceback.print_exc()
        if use_fallback(args, reason):
            return
        gh("error", "Aggiornamento prezzi fallito, il sito resta con i dati precedenti. " + reason)
        sys.exit(1)


def use_fallback(args, reason):
    if not args.fallback:
        return False
    try:
        if args.fallback.startswith("http"):
            req = urllib.request.Request(args.fallback + "?t=" + str(int(time.time())), headers={"User-Agent": "pieno-kamiq/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                old = json.load(r)
        else:
            with open(args.fallback, encoding="utf-8") as f:
                old = json.load(f)
        age = (dt.date.today() - dt.date.fromisoformat(old["estrazione"])).days
    except Exception as e:
        gh("warning", f"Dati precedenti non disponibili: {e}")
        return False
    if age > args.max_giorni_fallback:
        gh("error", f"Aggiornamento non riuscito e i dati già pubblicati hanno {age} giorni, troppo vecchi per riusarli. {reason}")
        return False
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(old, f, ensure_ascii=False, separators=(",", ":"))
    gh("warning", f"Prezzi MIMIT non aggiornati oggi ({reason}). Ripubblicati i dati del {old['estrazione']}; si riprova al prossimo giro.")
    return True


def build(args):
    provs = {p.strip().upper() for p in args.prov.split(",") if p.strip()}

    print("Scarico anagrafica…", file=sys.stderr)
    ext_a, h_a, r_a = rows(read_text(args.anagrafica))
    print("Scarico prezzi…", file=sys.stderr)
    ext_p, h_p, r_p = rows(read_text(args.prezzi))

    ia = {k: i for i, k in enumerate(h_a)}
    ip = {k: i for i, k in enumerate(h_p)}
    need_a = {"idImpianto", "Bandiera", "Nome Impianto", "Indirizzo", "Comune", "Provincia", "Latitudine", "Longitudine"}
    need_p = {"idImpianto", "descCarburante", "prezzo", "isSelf", "dtComu"}
    if not need_a <= ia.keys():
        raise ValueError(f"formato anagrafica cambiato, mancano le colonne {sorted(need_a - ia.keys())}; trovate: {h_a}")
    if not need_p <= ip.keys():
        raise ValueError(f"formato prezzi cambiato, mancano le colonne {sorted(need_p - ip.keys())}; trovate: {h_p}")

    stations = {}
    for r in r_a:
        prov = r[ia["Provincia"]].upper()
        if provs and prov not in provs:
            continue
        lat, lon = to_float(r[ia["Latitudine"]]), to_float(r[ia["Longitudine"]])
        if lat is None or lon is None or not (35 < lat < 48 and 6 < lon < 19):
            continue  # coordinate mancanti o fuori Italia
        sid = r[ia["idImpianto"]]
        stations[sid] = {
            "nome": title(r[ia["Nome Impianto"]].replace("\t", " ")),
            "bandiera": r[ia["Bandiera"]],
            "indirizzo": title(r[ia["Indirizzo"]]),
            "comune": title(r[ia["Comune"]]),
            "prov": prov,
            "tipo": r[ia.get("Tipo Impianto", 0)] if "Tipo Impianto" in ia else "",
            "lat": round(lat, 5), "lon": round(lon, 5),
            "bs": None, "bv": None, "ms": None, "mv": None, "db": "", "dm": "", "lg": False,
        }

    for r in r_p:
        s = stations.get(r[ip["idImpianto"]])
        if not s:
            continue
        fuel = r[ip["descCarburante"]].strip().lower()
        price = to_float(r[ip["prezzo"]])
        if price is None or price <= 0.3 or price > 5:
            continue  # prezzi palesemente errati
        self_ = r[ip["isSelf"]] == "1"
        day = to_date(r[ip["dtComu"]])
        if fuel in BENZINA:
            key = "bs" if self_ else "bv"
            if s[key] is None or price < s[key]:
                s[key] = price
            s["db"] = max(s["db"], day)
        elif fuel in LGNC:
            s["lg"] = True
        elif fuel in METANO:
            key = "ms" if self_ else "mv"
            if s[key] is None or price < s[key]:
                s[key] = price
            s["dm"] = max(s["dm"], day)

    fields = ["id", "nome", "bandiera", "indirizzo", "comune", "prov", "autostrada",
              "lat", "lon", "benzina_self", "benzina_servito", "metano", "agg_benzina", "agg_metano",
              "metano_self", "metano_servito"]
    out = []
    for sid, s in stations.items():
        m = min([p for p in (s["ms"], s["mv"]) if p is not None], default=None)
        if s["bs"] is None and s["bv"] is None and m is None:
            continue
        out.append([int(sid) if sid.isdigit() else sid, s["nome"], s["bandiera"], s["indirizzo"],
                    s["comune"], s["prov"], 1 if "autostrad" in s["tipo"].lower() else 0,
                    s["lat"], s["lon"], s["bs"], s["bv"], m, s["db"], s["dm"], s["ms"], s["mv"]])

    solo_lgnc = sum(1 for s in stations.values() if s["lg"] and s["ms"] is None and s["mv"] is None)
    data = {
        "esclusi_solo_lgnc": solo_lgnc,
        "fonte": "MIMIT - Osservaprezzi carburanti (open data)",
        "estrazione": ext_p or ext_a,
        "generato": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "campi": fields,
        "impianti": out,
    }
    if not provs and len(out) < 10000:
        raise ValueError(f"solo {len(out)} impianti con prezzi (di solito oltre 20.000): dati MIMIT incompleti")
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, args.out)
    n_m = sum(1 for s in out if s[11] is not None)
    print(f"OK: {len(out)} impianti ({n_m} con metano; {solo_lgnc} con solo L-GNC esclusi) -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
