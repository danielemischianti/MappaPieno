# Pieno Kamiq

Mappa per trovare il distributore di **metano** o **benzina** più conveniente rispetto a dove sei,
con il costo reale del tragitto (pedaggi compresi) per una Skoda Kamiq 1.5 TGI G-TEC del 2020.

- Posizione dal GPS del telefono, da un indirizzo o tenendo premuto sulla mappa.
- Prezzi ufficiali MIMIT (Osservaprezzi carburanti), aggiornati ogni mattina.
- Percorsi stradali reali (OSRM / OpenStreetMap). I tratti a pedaggio sono tratteggiati in arancio;
  tra il percorso più veloce e le alternative viene scelto il più economico.
- Classifica per **costo totale** = pieno (13,8 kg di metano o 9 l di benzina) + tragitto (andata e ritorno, disattivabile).
- Per ogni distributore: costo del tragitto a metano (4,9 kg/100 km) e a benzina (5,9 l/100 km), pedaggi, link a Google Maps e Waze.
- Consumi, quantità di rifornimento, tariffa pedaggio e raggio si cambiano dal pannello "Auto e parametri".

## Pubblicarla gratis con GitHub Pages (consigliato, funziona dal telefono)

1. Crea un repository su GitHub (anche privato va bene con GitHub Pro; altrimenti pubblico) e carica tutti i file di questa cartella, compresa `.github/workflows/`.
2. Nel repo: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Vai su **Actions → "Aggiorna prezzi e pubblica" → Run workflow** per il primo aggiornamento.
4. Apri `https://<tuo-utente>.github.io/<nome-repo>/` sul telefono e aggiungila alla schermata Home.

Da quel momento la Action scarica i prezzi nuovi due volte al giorno e ripubblica la pagina da sola.
Nell'app il pulsante **Aggiorna** ricarica prezzi e posizione.

Per un file più leggero puoi limitare le province: nel workflow imposta `PROVINCE: "RM,LT,FR"`.

## In locale sul PC

```bash
python3 update.py            # oppure: python3 update.py --prov RM,LT
python3 -m http.server 8000
```
Poi apri http://localhost:8000 (il GPS del browser funziona solo su https o localhost).

## Come calcola

- **Tragitto a metano** = km × 4,9/100 × prezzo del metano al distributore di arrivo + pedaggi.
- **Tragitto a benzina** = km × 5,9/100 × prezzo benzina self al distributore di arrivo + pedaggi.
  Se il distributore non vende quel carburante si usa la mediana dei prezzi entro 40 km.
- **Pedaggi**: km su autostrade a pagamento (riconosciute dalla sigla A1, A24…; escluse le gratuite come GRA/A90, A91, A2, A19, A29) × tariffa (predefinita 0,080 €/km, media classe A).
  È una stima: tratte come A24/A25 costano di più al km, tangenziali e GRA sono gratuite.
- I percorsi reali vengono calcolati per i migliori 8 candidati (modificabile) e per il più vicino;
  gli altri mostrano una stima con l'etichetta "stima".
- I prezzi non comunicati da più di 7 giorni sono segnalati, quelli fermi da oltre 30 giorni esclusi.

## Fonti e servizi
- Prezzi: MIMIT, open data Osservaprezzi carburanti (`anagrafica_impianti_attivi.csv`, `prezzo_alle_8.csv`).
- Mappa: tile OpenStreetMap. Percorsi: server dimostrativo OSRM (`router.project-osrm.org`), adatto a uso personale leggero.
- Ricerca indirizzi: Nominatim (OpenStreetMap).
