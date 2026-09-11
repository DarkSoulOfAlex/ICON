"""Quanto costa mettere l'istante nella chiave di uno stato.

Nel grafo tempo-espanso uno stato a terra si puo' identificare con
``(fermata, istante, cambi)`` oppure con ``(fermata, cambi)``. La prima
formulazione sembra la piu' naturale - due arrivi alla stessa fermata in momenti
diversi *sono* stati diversi - ed e' quella sbagliata: la ricerca procede in ordine
di orario di arrivo, quindi il primo arrivo a una fermata con un dato numero di
cambi domina tutti quelli successivi, e tenerli separati moltiplica gli stati senza
cambiare la risposta.

**Perche' questo programma esiste, e perche' cosi' tardi.** Il numero era stato
misurato una volta e riportato nel documento, ma non lo produceva nessuno script:
viveva nel log di una sessione. E' lo stesso difetto della voce 70 - un numero vero
quando fu scritto e non piu' verificabile - e qui costa un minuto rimediarlo,
perche' la macchina per farlo c'era gia': ``cerca_primo_arrivo`` accetta
``istante_nella_chiave``.

Si usa **la stessa coppia dichiarata nel documento**, la prima risolta del campione
di Torino con il seme 20260826, e lo stesso archivio delle altre fasi. Cambiare uno
di questi tre farebbe un esperimento diverso, non una verifica.

    python scripts/chiave_di_stato.py
    python scripts/chiave_di_stato.py --citta torino --archivio 2026-08-26
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

RADICE = Path(__file__).resolve().parents[1]
for _percorso in (RADICE, RADICE / "scripts"):
    if str(_percorso) not in sys.path:
        sys.path.insert(0, str(_percorso))

import pandas as pd                                          # noqa: E402

from src.graph.search import cerca_primo_arrivo               # noqa: E402
from src.graph.time_expanded import costruisci                # noqa: E402
from src.gtfs.loader import carica_archivio                   # noqa: E402

FUSO = ZoneInfo("Europe/Rome")
ORA_PARTENZA = 8
ORIZZONTE = 120
SEME = 20260826
"""Il seme con cui il documento dichiara estratta la coppia: non si cambia."""

def velocita_massima(citta: str, risultati: Path) -> float:
    """La velocita' massima misurata sugli archi, da ``velocita_archi.csv``.

    E' quella che rende ammissibile l'euristica della Fase 2, ed e' **la stessa**
    con cui il resto di quel capitolo e' stato misurato. Al primo tentativo questo
    programma usava un limite lasco di 500 m/s, plausibile in astratto: dava
    1.512.712 stati contro i 1.464.312 del documento, cioe' un esperimento diverso
    invece di una verifica. Un parametro scelto per comodita' basta a rendere
    irriproducibile un numero che era giusto.
    """
    tavola = pd.read_csv(risultati / "velocita_archi.csv")
    riga = tavola[tavola["citta"] == citta]
    if riga.empty:
        raise SystemExit(f"nessuna velocita' misurata per {citta} in velocita_archi.csv")
    return float(riga["massimo_m_s"].iloc[0])


def archivio_scelto(citta: str, fino_a: str | None) -> Path:
    archivi = sorted((RADICE / "data" / "raw" / "gtfs" / citta).glob("*.zip"))
    if fino_a:
        archivi = [a for a in archivi if a.stem.split("_")[0] <= fino_a]
    if not archivi:
        raise SystemExit(f"nessun archivio GTFS per {citta} valido al {fino_a}")
    return archivi[-1]


def prima_coppia_risolta(grafo, inizio: int, velocita: float, quante: int = 200):
    """La prima coppia del campione su cui esista un cammino, col seme dichiarato."""
    from ricerca_confronto import coppie_casuali

    for origine, destinazione in coppie_casuali(grafo, quante, SEME):
        esito = cerca_primo_arrivo(grafo, origine, destinazione, inizio, velocita)
        if esito.trovato:
            return origine, destinazione
    raise SystemExit("nessuna coppia risolta nel campione")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--citta", default="torino")
    parser.add_argument("--archivio", default="2026-08-26", metavar="AAAA-MM-GG")
    parser.add_argument("--origine", default=None)
    parser.add_argument("--destinazione", default=None)
    parser.add_argument("--radice", type=Path, default=RADICE)
    argomenti = parser.parse_args(argv)

    percorso = archivio_scelto(argomenti.citta, argomenti.archivio)
    archivio = carica_archivio(percorso, con_stop_times=True)
    giorno = date.fromisoformat(percorso.stem.split("_")[0])
    inizio = int(datetime(giorno.year, giorno.month, giorno.day, ORA_PARTENZA, 0,
                          tzinfo=FUSO).timestamp())
    grafo = costruisci(archivio, argomenti.citta, giorno, inizio, ORIZZONTE)
    velocita = velocita_massima(argomenti.citta, argomenti.radice / "results")
    print(f"=== {argomenti.citta} ({percorso.name}), partenza {ORA_PARTENZA}:00, "
          f"orizzonte {ORIZZONTE} min, V {velocita:.2f} m/s ===", flush=True)

    if argomenti.origine and argomenti.destinazione:
        origine, destinazione = argomenti.origine, argomenti.destinazione
    else:
        origine, destinazione = prima_coppia_risolta(grafo, inizio, velocita)
    print(f"  coppia {origine} -> {destinazione} (seme {SEME})", flush=True)

    righe = []
    for etichetta, con_istante in (("(fermata, istante, cambi)", True),
                                   ("(fermata, cambi)", False)):
        esito = cerca_primo_arrivo(grafo, origine, destinazione, inizio, velocita,
                                   istante_nella_chiave=con_istante)
        righe.append({
            "citta": argomenti.citta, "archivio": percorso.name,
            "seme": SEME, "velocita_m_s": round(velocita, 4),
            "origine": origine, "destinazione": destinazione,
            "chiave": etichetta, "istante_nella_chiave": con_istante,
            "stati_espansi": esito.stati_espansi,
            "stati_generati": esito.stati_generati,
            "secondi": round(esito.tempo_secondi, 2),
            "orario_arrivo": esito.orario_arrivo,
            "cambi": esito.cambi,
            "trovato": esito.trovato,
        })
        print(f"  {etichetta:<28} {esito.stati_espansi:>10,} stati  "
              f"{esito.tempo_secondi:>7.2f} s  arrivo {esito.orario_arrivo}", flush=True)

    risultati = argomenti.radice / "results"
    risultati.mkdir(parents=True, exist_ok=True)
    destinazione_csv = risultati / "chiave_di_stato.csv"
    pd.DataFrame(righe).to_csv(destinazione_csv, index=False)
    print(f"\nscritto {destinazione_csv} ({len(righe)} righe)")

    if len(righe) == 2 and all(r["trovato"] for r in righe):
        a, b = righe
        print(f"  rapporto sugli stati {a['stati_espansi'] / max(1, b['stati_espansi']):.0f}x, "
              f"sul tempo {a['secondi'] / max(0.01, b['secondi']):.0f}x, "
              f"stesso arrivo: {a['orario_arrivo'] == b['orario_arrivo']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
