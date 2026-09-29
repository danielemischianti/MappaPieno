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


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pieno-kamiq/1.0 (uso personale)"})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anagrafica", default=URL_ANAGRAFICA)
    ap.add_argument("--prezzi", default=URL_PREZZI)
    ap.add_argument("--prov", default="", help="sigle provincia separate da virgola, es. RM,LT")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "prezzi.json"))
    args = ap.parse_args()
    provs = {p.strip().upper() for p in args.prov.split(",") if p.strip()}

    print("Scarico anagrafica…", file=sys.stderr)
    ext_a, h_a, r_a = rows(read_text(args.anagrafica))
    print("Scarico prezzi…", file=sys.stderr)
    ext_p, h_p, r_p = rows(read_text(args.prezzi))

    ia = {k: i for i, k in enumerate(h_a)}
    ip = {k: i for i, k in enumerate(h_p)}

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
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    tmp = args.out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, args.out)
    n_m = sum(1 for s in out if s[11] is not None)
    print(f"OK: {len(out)} impianti ({n_m} con metano; {solo_lgnc} con solo L-GNC esclusi) -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
